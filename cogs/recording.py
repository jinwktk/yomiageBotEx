"""
録音・リプレイ機能Cog
"""

import asyncio
import logging
import random
import time
import io
import re
import os
import zipfile
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from collections import defaultdict
from contextlib import suppress
from pathlib import Path

import discord
from discord.ext import commands

from utils.real_audio_recorder import RealTimeAudioRecorder
from utils.audio_processor import AudioProcessor
from utils.direct_audio_capture import direct_audio_capture
from utils.recording_callback_manager import recording_callback_manager
from utils.manual_recording_manager import ManualRecordingManager, ManualRecordingError


@dataclass
class ReplayEntry:
    guild_id: int
    user_id: Optional[int]
    duration: float
    filename: str
    normalize: bool
    size: int
    created_at: datetime
    data: bytes
    path: Path


class RecordingCog(commands.Cog):
    """録音・リプレイ機能を提供するCog"""
    
    def __init__(self, bot: commands.Bot, config: Dict[str, Any]):
        self.bot = bot
        self.config = config
        self.logger = logging.getLogger(__name__)
        # 一時的にNoneを渡す（後で適切に修正が必要）
        self.recording_manager = RealTimeAudioRecorder(None)
        recording_config = config.get("recording", {})
        self.recording_enabled = recording_config.get("enabled", False)
        self.prefer_replay_buffer_manager = recording_config.get("prefer_replay_buffer_manager", True)
        self._replay_buffer_manager_override = None
        
        # 初期化時の設定値をログ出力
        self.logger.info(f"Recording: Initializing with recording_enabled: {self.recording_enabled}")
        self.logger.info(f"Recording: Config recording section: {config.get('recording', {})}")
        
        # ギルドごとの録音シンク（シミュレーション用）
        self.recording_sinks: Dict[int, SimpleRecordingSink] = {}
        
        # リアルタイム音声録音管理
        self.real_time_recorder = RealTimeAudioRecorder(self.recording_manager)
        
        # 録音開始のロック機構（Guild別）
        self.recording_locks: Dict[int, asyncio.Lock] = {}
        
        # 音声処理
        self.audio_processor = AudioProcessor(config)
        
        # クリーンアップタスクは後で開始
        self.cleanup_task_started = False

        # リプレイ履歴（デバッグ用途）
        self.replay_history: Dict[int, List["ReplayEntry"]] = defaultdict(list)
        self.replay_retention = timedelta(hours=24)
        self.replay_max_entries = 5
        project_root = Path(__file__).resolve().parents[1]
        self.replay_dir_base = project_root / "recordings" / "replay"
        self.replay_dir_base.mkdir(parents=True, exist_ok=True)
        self.manual_recording_dir_base = project_root / "recordings" / "manual"
        self.manual_recording_dir_base.mkdir(parents=True, exist_ok=True)
        self.manual_recording_manager = ManualRecordingManager(self.manual_recording_dir_base)
        self.manual_recording_context: Dict[int, Dict[str, Any]] = {}

    def _cleanup_replay_history(self, guild_id: Optional[int] = None):
        """リプレイ履歴から期限切れ・過剰なエントリを削除"""
        now = datetime.now()
        target_guilds = [guild_id] if guild_id is not None else list(self.replay_history.keys())

        for gid in target_guilds:
            entries = self.replay_history.get(gid)
            if not entries:
                self.replay_history.pop(gid, None)
                continue

            original_entries = list(entries)
            entries[:] = [entry for entry in entries if now - entry.created_at <= self.replay_retention]

            if len(entries) > self.replay_max_entries:
                entries[:] = entries[-self.replay_max_entries:]

            removed = [entry for entry in original_entries if entry not in entries]
            for entry in removed:
                with suppress(FileNotFoundError, OSError):
                    entry.path.unlink(missing_ok=True)

            if not entries:
                self.replay_history.pop(gid, None)

    def _store_replay_result(
        self,
        guild_id: int,
        user_id: Optional[int],
        duration: float,
        filename: str,
        normalize: bool,
        data: bytes,
    ):
        """生成したリプレイ音声を一時保持"""
        guild_dir = self.replay_dir_base / str(guild_id)
        guild_dir.mkdir(parents=True, exist_ok=True)

        safe_filename = re.sub(r"[^A-Za-z0-9_.-]", "_", filename)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = guild_dir / safe_filename
        if path.exists():
            path = guild_dir / f"{timestamp}_{safe_filename}"

        with open(path, "wb") as fp:
            fp.write(data)

        entry = ReplayEntry(
            guild_id=guild_id,
            user_id=user_id,
            duration=duration,
            filename=filename,
            normalize=normalize,
            size=len(data),
            created_at=datetime.now(),
            data=data,
            path=path,
        )
        self.replay_history[guild_id].append(entry)
        self._cleanup_replay_history(guild_id)

    def _store_manual_recording(
        self,
        guild_id: int,
        filename: str,
        data: bytes,
    ) -> Path:
        guild_dir = self.manual_recording_dir_base / str(guild_id)
        guild_dir.mkdir(parents=True, exist_ok=True)

        safe_filename = re.sub(r"[^A-Za-z0-9_.-]", "_", filename)
        path = guild_dir / safe_filename
        if path.exists():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = guild_dir / f"{timestamp}_{safe_filename}"

        with open(path, "wb") as fp:
            fp.write(data)
        return path

    def _store_replay_debug_stages(
        self,
        guild_id: int,
        base_name: str,
        raw_audio: bytes,
        normalized_audio: Optional[bytes],
        processed_audio: Optional[bytes],
    ) -> Dict[str, Path]:
        """リプレイの各工程音声を保存"""
        guild_debug_dir = self.replay_dir_base / str(guild_id) / "debug"
        guild_debug_dir.mkdir(parents=True, exist_ok=True)

        safe_base_name = re.sub(r"[^A-Za-z0-9_.-]", "_", base_name)

        normalized_stage = normalized_audio or raw_audio
        processed_stage = processed_audio or normalized_stage

        stage_payloads = {
            "raw": raw_audio,
            "normalized": normalized_stage,
            "processed": processed_stage,
        }

        stage_paths: Dict[str, Path] = {}
        for index, (stage_name, payload) in enumerate(stage_payloads.items(), start=1):
            stage_path = guild_debug_dir / f"{safe_base_name}_{index:02d}_{stage_name}.wav"
            with open(stage_path, "wb") as fp:
                fp.write(payload)
            stage_paths[stage_name] = stage_path

        zip_path = guild_debug_dir / f"{safe_base_name}_stages.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for stage_name in ("raw", "normalized", "processed"):
                file_path = stage_paths[stage_name]
                zip_file.write(file_path, arcname=file_path.name)
        stage_paths["zip"] = zip_path

        return stage_paths

    async def _maybe_send_replay_debug_stages(
        self,
        ctx: discord.ApplicationContext,
        enabled: bool,
        guild_id: int,
        base_name: str,
        raw_audio: bytes,
        stage_outputs: Dict[str, bytes],
    ):
        """デバッグ有効時に工程別音声を保存・通知"""
        if not enabled:
            return

        stage_paths = self._store_replay_debug_stages(
            guild_id=guild_id,
            base_name=base_name,
            raw_audio=raw_audio,
            normalized_audio=stage_outputs.get("normalized"),
            processed_audio=stage_outputs.get("processed"),
        )

        lines = [
            "🧪 工程別音声を保存しました。",
            f"- 生データ: `{stage_paths['raw']}`",
            f"- 正規化後: `{stage_paths['normalized']}`",
            f"- 加工後: `{stage_paths['processed']}`",
            f"- ZIP: `{stage_paths['zip']}`",
        ]

        zip_size = stage_paths["zip"].stat().st_size
        if zip_size <= 24 * 1024 * 1024:
            with open(stage_paths["zip"], "rb") as fp:
                await ctx.followup.send(
                    content="\n".join(lines),
                    file=discord.File(io.BytesIO(fp.read()), filename=stage_paths["zip"].name),
                    ephemeral=True,
                )
        else:
            lines.append("（ZIPサイズが24MBを超えるため、ファイル添付は省略しました）")
            await ctx.followup.send(content="\n".join(lines), ephemeral=True)
    
    def cog_unload(self):
        """Cogアンロード時のクリーンアップ"""
        for sink in self.recording_sinks.values():
            sink.cleanup()
        self.recording_sinks.clear()
        
        # リアルタイム録音のクリーンアップ
        self.real_time_recorder.cleanup()
    
    async def rate_limit_delay(self):
        """レート制限対策の遅延"""
        delay = random.uniform(*self.config["bot"]["rate_limit_delay"])
        await asyncio.sleep(delay)
    
    def get_recording_sink(self, guild_id: int):
        """ギルド用の録音シンクを取得（py-cord WaveSink使用）"""
        return discord.sinks.WaveSink()
    
    @commands.Cog.listener()
    async def on_ready(self):
        """Bot準備完了時の処理"""
        # RealTimeAudioRecorderにはstart_cleanup_taskメソッドがないため削除
        self.cleanup_task_started = True
        self.logger.info("Recording: Ready for recording operations")
    
    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """ボイス状態変更時の録音管理"""
        self.logger.info(f"Recording: Voice state update for {member.display_name}")
        self.logger.info(f"Recording: Recording enabled: {self.recording_enabled}")
        
        if not self.recording_enabled:
            self.logger.warning("Recording: Recording disabled in config")
            return
        
        if member.bot:  # ボット自身の変更は無視
            return
        
        guild = member.guild
        voice_client = guild.voice_client
        
        self.logger.info(f"Recording: Voice client connected: {voice_client is not None and voice_client.is_connected()}")
        
        if not voice_client or not voice_client.is_connected():
            self.logger.warning(f"Recording: No voice client or not connected for {guild.name}")
            return
        
        # ボットと同じチャンネルでの変更のみ処理
        bot_channel = voice_client.channel
        self.logger.info(f"Recording: Bot channel: {bot_channel.name if bot_channel else 'None'}")
        self.logger.info(f"Recording: Before channel: {before.channel.name if before.channel else 'None'}")
        self.logger.info(f"Recording: After channel: {after.channel.name if after.channel else 'None'}")
        
        # ユーザーがボットのいるチャンネルに参加した場合は録音開始
        if before.channel != bot_channel and after.channel == bot_channel:
            self.logger.info(f"Recording: User {member.display_name} joined bot channel {bot_channel.name}")
            
            # リアルタイム録音を開始
            try:
                await self.real_time_recorder.start_recording(guild.id, voice_client)
                self.logger.info(f"Recording: Started real-time recording for {bot_channel.name}")
            except Exception as e:
                self.logger.error(f"Recording: Failed to start real-time recording: {e}")
                # フォールバック録音は非対応（WaveSink単体では録音開始不可）
                self.logger.warning("Recording: Fallback simulation recording is unavailable on this runtime")
        
        # チャンネルが空になった場合は録音停止
        elif before.channel == bot_channel and after.channel != bot_channel:
            self.logger.info(f"Recording: User {member.display_name} left bot channel {bot_channel.name}")
            # ボット以外のメンバー数をチェック
            members_count = len([m for m in bot_channel.members if not m.bot])
            self.logger.info(f"Recording: Members remaining: {members_count}")
            if members_count == 0:
                # リアルタイム録音を停止
                try:
                    await self.real_time_recorder.stop_recording(guild.id, voice_client)
                    self.logger.info(f"Recording: Stopped real-time recording for {bot_channel.name}")
                except Exception as e:
                    self.logger.error(f"Recording: Failed to stop real-time recording: {e}")
    
    async def handle_bot_joined_with_user(self, guild: discord.Guild, member: discord.Member):
        """ボットがVCに参加した際、既にいるユーザーがいる場合の録音開始処理"""
        try:
            # Guild別のロックを取得・作成
            if guild.id not in self.recording_locks:
                self.recording_locks[guild.id] = asyncio.Lock()
            
            # ロックを使用して同時実行を防ぐ
            async with self.recording_locks[guild.id]:
                # 複数回チェックして接続の安定性を確保
                voice_client = None
                for attempt in range(5):
                    voice_client = guild.voice_client
                    if voice_client and voice_client.is_connected():
                        # 追加の安定性チェック
                        await asyncio.sleep(0.2)
                        if voice_client.is_connected():
                            break
                    await asyncio.sleep(0.5)
                
                if voice_client and voice_client.is_connected():
                    self.logger.info(f"Recording: Bot joined, starting recording for user {member.display_name}")
                    
                    # さらに短い安定化待機
                    await asyncio.sleep(0.3)
                    
                    # 最終接続確認
                    if not voice_client.is_connected():
                        self.logger.warning(f"Recording: Voice client disconnected before starting recording for {member.display_name}")
                        return
                    
                    # リアルタイム録音を開始
                    try:
                        await self.real_time_recorder.start_recording(guild.id, voice_client)
                        self.logger.info(f"Recording: Started real-time recording for {voice_client.channel.name}")
                        
                        # 録音状況デバッグ（一時的に無効化 - パフォーマンス問題回避）
                        await asyncio.sleep(1)  # 録音開始を待つ
                        # self.real_time_recorder.debug_recording_status(guild.id)
                    except Exception as e:
                        self.logger.error(f"Recording: Failed to start real-time recording: {e}")
                        # フォールバック: シミュレーション録音
                        try:
                            sink = self.get_recording_sink(guild.id)
                            if not sink.is_recording:
                                sink.start_recording()
                                self.logger.info(f"Recording: Started fallback simulation recording for {voice_client.channel.name}")
                        except Exception as fallback_error:
                            self.logger.error(f"Recording: Fallback recording also failed: {fallback_error}")
                else:
                    self.logger.warning(f"Recording: No stable voice client when trying to start recording for {member.display_name}")
        except Exception as e:
            self.logger.error(f"Recording: Failed to handle bot joined with user: {e}")
    
    @discord.slash_command(name="replay", description="最近の音声を録音ファイルとして投稿します（直接キャプチャ）")
    async def replay_command(
        self, 
        ctx: discord.ApplicationContext, 
        duration: discord.Option(float, "録音する時間（秒）", default=30.0, min_value=5.0, max_value=300.0) = 30.0,
        user: discord.Option(discord.Member, "対象ユーザー（省略時は全体）", required=False) = None,
        normalize: discord.Option(bool, "音声正規化の有効/無効", default=True, required=False) = True,
        debug_audio_stages: discord.Option(bool, "工程別音声（生/正規化後/加工後）を保存する", default=False, required=False) = False,
    ):
        """過去の音声をWAVファイルとして出力"""
        if not self.recording_enabled:
            await ctx.respond("⚠️ 録音機能が無効です。", ephemeral=True)
            return
        
        await ctx.respond("🎵 録音データを取得しています...", ephemeral=True)
        self.logger.info(
            "Replay request: guild=%s, duration=%ss, user=%s, normalize=%s, debug_audio_stages=%s",
            ctx.guild.id,
            duration,
            user.id if user else "all",
            normalize,
            debug_audio_stages,
        )

        asyncio.create_task(self._process_replay_async(ctx, duration, user, normalize, debug_audio_stages))
    
    async def _process_replay_async(self, ctx, duration: float, user, normalize: bool, debug_audio_stages: bool = False):
        """replayコマンドの重い処理を非同期で実行"""
        try:
            import io
            import asyncio
            from datetime import datetime

            # まずReplayBufferManager（新システム）が利用可能なら必ず試行
            if self.prefer_replay_buffer_manager:
                replay_result = await self._process_new_replay_async(
                    ctx,
                    duration,
                    user,
                    normalize,
                    debug_audio_stages=debug_audio_stages,
                    suppress_no_data_message=True,
                )
                if replay_result:
                    return

            # リアルタイム録音データから直接バッファを取得（Guild別）
            guild_id = ctx.guild.id
            
            # 録音中の場合は強制的にチェックポイントを作成
            if guild_id in self.real_time_recorder.connections:
                vc = self.real_time_recorder.connections[guild_id]
                if hasattr(vc, 'recording') and vc.recording:
                    self.logger.info(f"Recording is active, creating checkpoint before replay")
                    checkpoint_success = await self.real_time_recorder.force_recording_checkpoint(guild_id)
                    if checkpoint_success:
                        self.logger.info(f"Checkpoint created successfully")
                    else:
                        self.logger.warning(f"Failed to create checkpoint, using existing buffers")
            
            # 新しい時間範囲ベースの音声データ取得を試行（タイムアウト付き）
            if hasattr(self.real_time_recorder, 'get_audio_for_time_range'):
                # まず現在のGuildから音声データを取得（10秒タイムアウト）
                try:
                    time_range_audio = await asyncio.wait_for(
                        asyncio.to_thread(self.real_time_recorder.get_audio_for_time_range, guild_id, duration, user.id if user else None),
                        timeout=10.0
                    )
                except asyncio.TimeoutError:
                    self.logger.error(f"Recording: Timeout getting audio for guild {guild_id}")
                    await ctx.followup.send("⚠️ 音声データの取得がタイムアウトしました。", ephemeral=True)
                    return
                
                # 音声リレー機能が有効な場合、全Guildから音声データを検索
                if not time_range_audio or (user and user.id not in time_range_audio):
                    self.logger.info(f"Recording: No audio found in current guild {guild_id}, searching all guilds...")
                    # 安全にキーのリストを取得（辞書が変更されても問題ない）
                    try:
                        guild_ids = list(self.real_time_recorder.continuous_buffers.keys())
                        for search_guild_id in guild_ids:
                            if search_guild_id != guild_id:
                                try:
                                    # 各Guild検索も5秒タイムアウト
                                    search_audio = await asyncio.wait_for(
                                        asyncio.to_thread(self.real_time_recorder.get_audio_for_time_range, search_guild_id, duration, user.id if user else None),
                                        timeout=5.0
                                    )
                                    if search_audio:
                                        self.logger.info(f"Recording: Found audio data in guild {search_guild_id}")
                                        time_range_audio = search_audio
                                        break
                                except asyncio.TimeoutError:
                                    self.logger.warning(f"Recording: Timeout searching guild {search_guild_id}, skipping")
                                    continue
                    except Exception as e:
                        self.logger.error(f"Recording: Error searching all guilds for audio: {e}")
                
                if user:
                    # 特定ユーザーの音声
                    if user.id not in time_range_audio or not time_range_audio[user.id]:
                        hint = ""
                        health = self.real_time_recorder.get_buffer_health_summary(guild_id, user.id)
                        if health["entries"]:
                            hint = f"\n（最後の記録は {health['entries'][0]['seconds_since_last']:.1f} 秒前）"
                        await ctx.followup.send(f"⚠️ {user.mention} の過去{duration}秒間の音声データが見つかりません。{hint}", ephemeral=True)
                        return
                    
                    audio_data = time_range_audio[user.id]
                    audio_buffer = io.BytesIO(audio_data)
                    
                    # 一時ファイルに保存してノーマライズ処理
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                    filename = f"recording_user{user.id}_{duration}s_{timestamp}.wav"
                    
                    stage_outputs: Dict[str, bytes] = {}
                    processed_data = await self._process_audio_buffer(
                        audio_buffer,
                        normalize=normalize,
                        debug_stage_output=stage_outputs if debug_audio_stages else None,
                    )
                    self._store_replay_result(
                        guild_id=ctx.guild.id,
                        user_id=user.id,
                        duration=duration,
                        filename=filename,
                        normalize=normalize,
                        data=processed_data,
                    )

                    await ctx.followup.send(
                        f"🎵 {user.mention} の録音です（過去{duration}秒分、{'ノーマライズ済み' if normalize else '無加工'}）",
                        file=discord.File(io.BytesIO(processed_data), filename=filename),
                        ephemeral=True
                    )
                    await self._maybe_send_replay_debug_stages(
                        ctx=ctx,
                        enabled=debug_audio_stages,
                        guild_id=ctx.guild.id,
                        base_name=filename.rsplit(".", 1)[0],
                        raw_audio=audio_data,
                        stage_outputs=stage_outputs,
                    )
                    return
                
                else:
                    # 全員の音声をミキシング（重ね合わせ）
                    if not time_range_audio:
                        await ctx.followup.send(f"⚠️ 過去{duration}秒間の録音データがありません。", ephemeral=True)
                        return
                    
                    # 音声ミキシング処理
                    try:
                        mixed_audio = self._mix_multiple_audio_streams(time_range_audio)
                        if not mixed_audio:
                            await ctx.followup.send(f"⚠️ 音声ミキシング処理に失敗しました。", ephemeral=True)
                            return
                        
                        combined_audio = io.BytesIO(mixed_audio)
                        user_count = len(time_range_audio)
                        
                    except Exception as mix_error:
                        self.logger.error(f"Audio mixing failed: {mix_error}")
                        # フォールバック: 最初のユーザーのみを使用
                        if time_range_audio:
                            first_audio = list(time_range_audio.values())[0]
                            combined_audio = io.BytesIO(first_audio)
                            user_count = 1
                            await ctx.followup.send(f"⚠️ ミキシングに失敗、最初のユーザーのみ再生します。", ephemeral=True)
                        else:
                            return
                    
                    # 一時ファイルに保存してノーマライズ処理
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                    filename = f"recording_all_{user_count}users_{duration}s_{timestamp}.wav"
                    
                    raw_all_audio = combined_audio.getvalue()
                    combined_audio.seek(0)
                    stage_outputs: Dict[str, bytes] = {}
                    processed_data = await self._process_audio_buffer(
                        combined_audio,
                        normalize=normalize,
                        debug_stage_output=stage_outputs if debug_audio_stages else None,
                    )
                    self._store_replay_result(
                        guild_id=ctx.guild.id,
                        user_id=None,
                        duration=duration,
                        filename=filename,
                        normalize=normalize,
                        data=processed_data,
                    )

                    await ctx.followup.send(
                        f"🎵 全員の録音です（過去{duration}秒分、{user_count}人、{'ノーマライズ済み' if normalize else '無加工'}）",
                        file=discord.File(io.BytesIO(processed_data), filename=filename),
                        ephemeral=True
                    )
                    await self._maybe_send_replay_debug_stages(
                        ctx=ctx,
                        enabled=debug_audio_stages,
                        guild_id=ctx.guild.id,
                        base_name=filename.rsplit(".", 1)[0],
                        raw_audio=raw_all_audio,
                        stage_outputs=stage_outputs,
                    )
                    return
            
            # フォールバック：従来の方式
            user_audio_buffers = self.real_time_recorder.get_user_audio_buffers(guild_id, user.id if user else None)
            
            # バッファクリーンアップ（Guild別）
            await self.real_time_recorder.clean_old_buffers(guild_id)
            
            if user:
                # 特定ユーザーの音声
                if user.id not in user_audio_buffers or not user_audio_buffers[user.id]:
                    await ctx.followup.send(f"⚠️ {user.mention} の音声データが見つかりません。", ephemeral=True)
                    return
                
                # 最新のバッファを取得
                sorted_buffers = sorted(user_audio_buffers[user.id], key=lambda x: x[1])
                if not sorted_buffers:
                    await ctx.followup.send(f"⚠️ {user.mention} の音声データがありません。", ephemeral=True)
                    return
                
                # 最新のバッファを結合
                audio_buffer = io.BytesIO()
                for buffer, timestamp in sorted_buffers[-5:]:  # 最新5個
                    buffer.seek(0)
                    audio_buffer.write(buffer.read())
                
                audio_buffer.seek(0)
                
                # 一時ファイルに保存してノーマライズ処理
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = f"recording_user{user.id}_{timestamp}.wav"
                
                raw_user_audio = audio_buffer.getvalue()
                audio_buffer.seek(0)
                stage_outputs: Dict[str, bytes] = {}
                processed_data = await self._process_audio_buffer(
                    audio_buffer,
                    normalize=normalize,
                    debug_stage_output=stage_outputs if debug_audio_stages else None,
                )
                self._store_replay_result(
                    guild_id=ctx.guild.id,
                    user_id=user.id,
                    duration=duration,
                    filename=filename,
                    normalize=normalize,
                    data=processed_data,
                )

                await ctx.followup.send(
                    f"🎵 {user.mention} の録音です（約{duration}秒分、{'ノーマライズ済み' if normalize else '無加工'}）",
                    file=discord.File(io.BytesIO(processed_data), filename=filename),
                    ephemeral=True
                )
                await self._maybe_send_replay_debug_stages(
                    ctx=ctx,
                    enabled=debug_audio_stages,
                    guild_id=ctx.guild.id,
                    base_name=filename.rsplit(".", 1)[0],
                    raw_audio=raw_user_audio,
                    stage_outputs=stage_outputs,
                )
                
            else:
                # 全員の音声をマージ
                if not user_audio_buffers:
                    await ctx.followup.send("⚠️ 録音データがありません。", ephemeral=True)
                    return
                
                # 全ユーザーの音声データを収集・マージ
                all_audio_data = []
                user_count = 0
                
                for user_id, buffers in user_audio_buffers.items():
                    if not buffers:
                        continue
                        
                    # 最新5個のバッファを取得
                    sorted_buffers = sorted(buffers, key=lambda x: x[1])[-5:]
                    user_count += 1
                    
                    # ユーザーごとの音声データを結合
                    user_audio = io.BytesIO()
                    for buffer, timestamp in sorted_buffers:
                        buffer.seek(0)
                        user_audio.write(buffer.read())
                    
                    if user_audio.tell() > 0:  # データがある場合のみ追加
                        user_audio.seek(0)
                        all_audio_data.append(user_audio)
                
                if not all_audio_data:
                    await ctx.followup.send("⚠️ 有効な録音データがありません。", ephemeral=True)
                    return
                
                # 全員の音声を正しくミックス
                try:
                    mixed_audio = self._mix_multiple_audio_streams(all_audio_data)
                    if mixed_audio is None:
                        await ctx.followup.send("⚠️ 音声ミキシング処理に失敗しました。", ephemeral=True)
                        return
                    
                    merged_audio = io.BytesIO(mixed_audio)
                except Exception as e:
                    self.logger.error(f"Audio mixing failed: {e}", exc_info=True)
                    await ctx.followup.send("⚠️ 音声ミキシング処理に失敗しました。", ephemeral=True)
                    return
                
                # マージした音声をノーマライズ処理
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = f"recording_all_{user_count}users_{timestamp}.wav"
                
                raw_merged_audio = merged_audio.getvalue()
                merged_audio.seek(0)
                stage_outputs: Dict[str, bytes] = {}
                processed_data = await self._process_audio_buffer(
                    merged_audio,
                    normalize=normalize,
                    debug_stage_output=stage_outputs if debug_audio_stages else None,
                )
                self._store_replay_result(
                    guild_id=ctx.guild.id,
                    user_id=None,
                    duration=duration,
                    filename=filename,
                    normalize=normalize,
                    data=processed_data,
                )

                await ctx.followup.send(
                    f"🎵 全員の録音です（{user_count}人分、{duration}秒分、{'ノーマライズ済み' if normalize else '無加工'}）",
                    file=discord.File(io.BytesIO(processed_data), filename=filename),
                    ephemeral=True
                )
                await self._maybe_send_replay_debug_stages(
                    ctx=ctx,
                    enabled=debug_audio_stages,
                    guild_id=ctx.guild.id,
                    base_name=filename.rsplit(".", 1)[0],
                    raw_audio=raw_merged_audio,
                    stage_outputs=stage_outputs,
                )
            
            self.logger.info(f"Replaying {duration}s audio (user: {user}) for {ctx.user} in {ctx.guild.name}")
            
        except Exception as e:
            self.logger.error(f"Failed to replay audio: {e}", exc_info=True)
            await ctx.followup.send(
                f"⚠️ リプレイに失敗しました: {str(e)}", ephemeral=True
            )

    @discord.slash_command(name="replay_history", description="最近生成したリプレイ音声を表示します（管理者向け）")
    async def replay_history_command(
        self,
        ctx: discord.ApplicationContext,
        slot: discord.Option(int, "ダウンロードする番号（一覧表示のみの場合は未指定）", required=False, min_value=1, max_value=5) = None,
    ):
        await self.rate_limit_delay()
        self._cleanup_replay_history(ctx.guild.id)
        entries = self.replay_history.get(ctx.guild.id, [])

        if not entries:
            await ctx.respond("📂 リプレイ履歴は空です。最近 `/replay` を実行してください。", ephemeral=True)
            return

        entries_sorted = sorted(entries, key=lambda e: e.created_at, reverse=True)

        if slot is not None:
            if slot > len(entries_sorted):
                await ctx.respond(f"⚠️ 指定した番号 {slot} は存在しません。現在 {len(entries_sorted)} 件です。", ephemeral=True)
                return
            entry = entries_sorted[slot - 1]
            if not entry.path.exists():
                await ctx.respond("⚠️ 音声ファイルが見つかりませんでした。", ephemeral=True)
                return
            with open(entry.path, "rb") as fp:
                data = fp.read()
            await ctx.respond(
                content=f"🎵 {entry.filename} を送信します（{entry.duration:.1f}秒, {'ノーマライズ済み' if entry.normalize else '無加工'}）。",
                file=discord.File(io.BytesIO(data), filename=entry.filename),
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="🎞️ 最近生成したリプレイ",
            color=discord.Color.teal(),
        )
        for index, entry in enumerate(entries_sorted[: self.replay_max_entries], start=1):
            emoji = "✅" if entry.normalize else "⚠️"
            embed.add_field(
                name=f"{index}. {entry.filename}",
                value=(
                    f"時間: {entry.created_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"長さ: {entry.duration:.1f}秒 / サイズ: {entry.size/1024/1024:.2f}MB\n"
                    f"対象: {f'<@{entry.user_id}>' if entry.user_id else '全員'} / {emoji} "
                    f"{'ノーマライズ' if entry.normalize else '無加工'}"
                ),
                inline=False,
            )
        embed.set_footer(text="番号を指定すると個別にダウンロードできます。例: /replay_history slot:1")
        await ctx.respond(embed=embed, ephemeral=True)

    @discord.slash_command(name="recordings", description="最近の録音リストを表示します")
    async def recordings_command(self, ctx: discord.ApplicationContext):
        """録音リストを表示するコマンド"""
        await self.rate_limit_delay()
        
        if not self.recording_enabled:
            await ctx.respond(
                "❌ 録音機能は現在無効になっています。",
                ephemeral=True
            )
            return
        
        try:
            recordings = await self.recording_manager.list_recent_recordings(
                guild_id=ctx.guild.id,
                limit=5
            )
            
            if not recordings:
                await ctx.respond(
                    "📂 録音ファイルはありません。",
                    ephemeral=True
                )
                return
            
            # 録音リストを整形
            embed = discord.Embed(
                title="🎵 最近の録音",
                color=discord.Color.blue()
            )
            
            for i, recording in enumerate(recordings, 1):
                created_at = recording["created_at"][:19].replace("T", " ")
                file_size_mb = recording["file_size"] / (1024 * 1024)
                
                embed.add_field(
                    name=f"{i}. 録音 {recording['id'][:8]}",
                    value=f"時刻: {created_at}\n"
                          f"長さ: {recording['duration']:.1f}秒\n"
                          f"サイズ: {file_size_mb:.2f}MB",
                    inline=True
                )
            
            embed.set_footer(text="録音は1時間後に自動削除されます")
            
            await ctx.respond(embed=embed, ephemeral=True)
            
        except Exception as e:
            self.logger.error(f"Failed to list recordings: {e}")
            await ctx.respond(
                "❌ 録音リストの取得に失敗しました。",
                ephemeral=True
            )


    @discord.slash_command(name="start_record", description="手動で録音を開始します（WAV形式）")
    async def start_record_command(
        self,
        ctx: discord.ApplicationContext,
        normalize: discord.Option(bool, "音声を正規化するかどうか", default=True, required=False) = True,
    ):
        await self.rate_limit_delay()

        if not self.recording_enabled:
            await ctx.respond("⚠️ 録音機能が無効です。`config.yaml` を確認してください。", ephemeral=True)
            return

        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.respond("⚠️ ボイスチャンネルに参加してから実行してください。", ephemeral=True)
            return

        voice_client = ctx.guild.voice_client
        if not voice_client or not voice_client.is_connected():
            await ctx.respond("⚠️ ボットがボイスチャンネルに接続していません。先に `/join` を実行してください。", ephemeral=True)
            return

        if voice_client.channel != ctx.author.voice.channel:
            await ctx.respond("⚠️ ボットと同じボイスチャンネルで実行する必要があります。", ephemeral=True)
            return

        if self.manual_recording_manager.has_session(ctx.guild.id):
            await ctx.respond("⚠️ すでに手動録音を実行中です。`/stop_record` で停止してください。", ephemeral=True)
            return

        resume_real_time = False
        try:
            if self.real_time_recorder.recording_status.get(ctx.guild.id):
                resume_real_time = True
                await self.real_time_recorder.force_recording_checkpoint(ctx.guild.id)
                await self.real_time_recorder.stop_recording(ctx.guild.id, voice_client)
        except Exception as e:
            self.logger.warning(f"Manual recording: failed to pause real-time recorder: {e}")

        try:
            await self.manual_recording_manager.start_session(
                guild_id=ctx.guild.id,
                voice_client=voice_client,
                initiated_by=ctx.author.id,
                metadata={
                    "normalize": normalize,
                    "channel_id": voice_client.channel.id if voice_client.channel else None,
                },
            )
            self.manual_recording_context[ctx.guild.id] = {
                "normalize": normalize,
                "resume_real_time": resume_real_time,
                "initiated_by": ctx.author.id,
                "channel_id": voice_client.channel.id if voice_client.channel else None,
            }
            await ctx.respond(
                "⏺️ 手動録音を開始しました。終了する際は `/stop_record` を実行してください。",
                ephemeral=True,
            )
        except ManualRecordingError as e:
            self.logger.error(f"Manual recording: failed to start: {e}")
            if resume_real_time:
                try:
                    await self.real_time_recorder.start_recording(ctx.guild.id, voice_client)
                except Exception as resume_error:
                    self.logger.error(f"Manual recording: failed to resume real-time recorder: {resume_error}")
            await ctx.respond("❌ 手動録音の開始に失敗しました。ログを確認してください。", ephemeral=True)

    @discord.slash_command(name="stop_record", description="手動録音を停止してWAVファイルを出力します")
    async def stop_record_command(self, ctx: discord.ApplicationContext):
        if not self.recording_enabled:
            await ctx.respond("⚠️ 録音機能が無効です。", ephemeral=True)
            return

        if not self.manual_recording_manager.has_session(ctx.guild.id):
            await ctx.respond("⚠️ 手動録音は開始されていません。`/start_record` を先に実行してください。", ephemeral=True)
            return

        await ctx.defer(ephemeral=True)

        context_info = self.manual_recording_context.get(ctx.guild.id, {})
        normalize = context_info.get("normalize", True)
        resume_real_time = context_info.get("resume_real_time", False)

        try:
            result = await self.manual_recording_manager.stop_session(guild_id=ctx.guild.id)
        except ManualRecordingError as e:
            self.logger.error(f"Manual recording: failed to stop: {e}")
            await ctx.followup.send("❌ 手動録音の停止に失敗しました。ログを確認してください。", ephemeral=True)
            return
        finally:
            self.manual_recording_context.pop(ctx.guild.id, None)

        if not result.audio_map:
            await ctx.followup.send("⚠️ 録音データが取得できませんでした。音声が発生していたか確認してください。", ephemeral=True)
            return

        processed_per_user: Dict[int, bytes] = {}
        try:
            for user_id, wav_bytes in result.audio_map.items():
                processed_per_user[user_id] = await self._process_audio_buffer(
                    io.BytesIO(wav_bytes),
                    normalize=normalize,
                )
        except Exception as e:
            self.logger.error(f"Manual recording: audio processing failed: {e}", exc_info=True)
            await ctx.followup.send("❌ 音声処理に失敗しました。", ephemeral=True)
            processed_per_user = {
                user_id: data for user_id, data in result.audio_map.items() if data
            }

        if not processed_per_user:
            await ctx.followup.send("⚠️ 取得した音声が空でした。", ephemeral=True)
            return

        if len(processed_per_user) == 1:
            combined_audio = next(iter(processed_per_user.values()))
        else:
            combined_audio = self._mix_multiple_audio_streams(processed_per_user)
            if not combined_audio:
                combined_audio = next(iter(processed_per_user.values()))

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        user_count = len(processed_per_user)
        max_duration = max(result.durations.values(), default=0.0)
        combined_filename = f"manual_record_{user_count}users_{max_duration:.0f}s_{timestamp}.wav"

        combined_path = self._store_manual_recording(ctx.guild.id, combined_filename, combined_audio)

        files = [
            discord.File(io.BytesIO(combined_audio), filename=combined_filename),
        ]

        zip_bytes = None
        if user_count > 1:
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                for user_id, audio_bytes in processed_per_user.items():
                    member = ctx.guild.get_member(user_id)
                    suffix = member.display_name if member else f"user{user_id}"
                    zip_file.writestr(f"{suffix}_{timestamp}.wav", audio_bytes)
            zip_bytes = zip_buffer.getvalue()
            if len(zip_bytes) <= 24 * 1024 * 1024:
                zip_filename = f"manual_record_users_{timestamp}.zip"
                self._store_manual_recording(ctx.guild.id, zip_filename, zip_bytes)
                files.append(discord.File(io.BytesIO(zip_bytes), filename=zip_filename))
            else:
                self.logger.warning("Manual recording ZIP exceeds 24MB, skipping attachment.")

        user_mentions = []
        for user_id in processed_per_user.keys():
            member = ctx.guild.get_member(user_id)
            user_mentions.append(member.mention if member else f"<@{user_id}>")

        description_lines = [
            f"🎙️ 手動録音が完了しました（{user_count}人, 約{max_duration:.1f}秒, {'ノーマライズ済み' if normalize else '無加工'}）。",
            f"保存先: `{combined_path}`",
        ]
        if user_mentions:
            description_lines.append(f"対象ユーザー: {', '.join(user_mentions)}")

        await ctx.followup.send(
            content="\n".join(description_lines),
            files=files,
            ephemeral=True,
        )

        if resume_real_time and ctx.guild.voice_client:
            try:
                await self.real_time_recorder.start_recording(ctx.guild.id, ctx.guild.voice_client)
            except Exception as e:
                self.logger.error(f"Manual recording: failed to resume real-time recorder after stop: {e}")
    async def _process_audio_buffer(
        self,
        audio_buffer,
        normalize: bool = True,
        debug_stage_output: Optional[Dict[str, bytes]] = None,
    ) -> bytes:
        """音声バッファをノーマライズ処理（ファイルサイズ制限付き）"""
        try:
            import tempfile
            import os

            MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_input:
                audio_buffer.seek(0)
                original_data = audio_buffer.read()

                if len(original_data) > MAX_FILE_SIZE:
                    self.logger.warning(
                        "Audio file too large: %.1fMB > 20MB limit",
                        len(original_data) / 1024 / 1024,
                    )
                    compression_ratio = MAX_FILE_SIZE / len(original_data)
                    compressed_size = int(len(original_data) * compression_ratio * 0.9)
                    compressed_data = original_data[:compressed_size]
                    self.logger.info(
                        "Compressed audio from %.1fMB to %.1fMB",
                        len(original_data) / 1024 / 1024,
                        len(compressed_data) / 1024 / 1024,
                    )
                    temp_input.write(compressed_data)
                else:
                    temp_input.write(original_data)

                temp_input_path = temp_input.name
                if debug_stage_output is not None:
                    debug_stage_output["raw"] = original_data

            processed_data: Optional[bytes] = None
            normalized_data: Optional[bytes] = None

            normalized_path = None
            if normalize:
                normalized_path = await self.audio_processor.normalize_audio(temp_input_path)

            if normalized_path and normalized_path != temp_input_path:
                with open(normalized_path, "rb") as f:
                    normalized_data = f.read()
                    processed_data = normalized_data

                if len(processed_data) > MAX_FILE_SIZE:
                    self.logger.warning(
                        "Normalized file still too large: %.1fMB",
                        len(processed_data) / 1024 / 1024,
                    )
                    compression_ratio = MAX_FILE_SIZE / len(processed_data)
                    compressed_size = int(len(processed_data) * compression_ratio * 0.9)
                    processed_data = processed_data[:compressed_size]
                    self.logger.info(
                        "Re-compressed to %.1fMB", len(processed_data) / 1024 / 1024
                    )

                self.audio_processor.cleanup_temp_files(normalized_path)
            else:
                with open(temp_input_path, "rb") as f:
                    processed_data = f.read()
                    normalized_data = processed_data

                if len(processed_data) > MAX_FILE_SIZE:
                    compression_ratio = MAX_FILE_SIZE / len(processed_data)
                    compressed_size = int(len(processed_data) * compression_ratio * 0.9)
                    processed_data = processed_data[:compressed_size]
                    self.logger.info(
                        "Final compression to %.1fMB", len(processed_data) / 1024 / 1024
                    )

            self.audio_processor.cleanup_temp_files(temp_input_path)

            final_size_mb = len(processed_data) / 1024 / 1024
            self.logger.info("Final audio file size: %.1fMB", final_size_mb)

            if debug_stage_output is not None:
                debug_stage_output["normalized"] = normalized_data or processed_data
                debug_stage_output["processed"] = processed_data

            if len(processed_data) > MAX_FILE_SIZE:
                raise Exception(
                    f"Audio file still too large after compression: {final_size_mb:.1f}MB"
                )

            return processed_data

        except Exception as e:
            self.logger.error(f"Audio processing failed: {e}")
            audio_buffer.seek(0)
            original_data = audio_buffer.read()

            MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB
            if len(original_data) > MAX_FILE_SIZE:
                compression_ratio = MAX_FILE_SIZE / len(original_data)
                compressed_size = int(len(original_data) * compression_ratio * 0.8)
                compressed_data = original_data[:compressed_size]
                if debug_stage_output is not None:
                    debug_stage_output["raw"] = original_data
                    debug_stage_output["normalized"] = original_data
                    debug_stage_output["processed"] = compressed_data
                self.logger.warning(
                    "Emergency compression: %.1fMB -> %.1fMB",
                    len(original_data) / 1024 / 1024,
                    len(compressed_data) / 1024 / 1024,
                )
                return compressed_data

            if debug_stage_output is not None:
                debug_stage_output["raw"] = original_data
                debug_stage_output["normalized"] = original_data
                debug_stage_output["processed"] = original_data
            return original_data
    
    async def _process_new_replay_async(
        self,
        ctx,
        duration: float,
        user,
        normalize: bool,
        debug_audio_stages: bool = False,
        suppress_no_data_message: bool = False,
    ):
        """新システム（ReplayBufferManager）でのreplayコマンド処理。成功時はTrueを返す"""
        try:
            from utils.replay_buffer_manager import replay_buffer_manager
            
            # 外部からテスト用に上書きされたマネージャーがあれば優先使用
            manager = getattr(self, "_replay_buffer_manager_override", None) or replay_buffer_manager

            if not manager:
                await ctx.followup.send(content="❌ ReplayBufferManagerが利用できません。", ephemeral=True)
                return False
            
            start_time = time.time()
            self.logger.info(f"Starting new replay processing: duration={duration}s, normalize={normalize}")
            
            # ReplayBufferManagerから音声データを取得
            result = await manager.get_replay_audio(
                guild_id=ctx.guild.id,
                duration_seconds=duration,
                user_id=user.id if user else None,
                normalize=False,
                mix_users=True
            )
            
            if not result:
                if not suppress_no_data_message:
                    user_mention = f"@{user.display_name}" if user else "全ユーザー"
                    await ctx.followup.send(
                        content=f"❌ {user_mention} の過去{duration:.1f}秒間の音声データが見つかりません。\n"
                                "ボイスチャンネルで音声が発生してから、少し時間をおいて再度お試しください。",
                        ephemeral=True
                    )
                return False
            
            # 統計情報をログ出力
            processing_time = time.time() - start_time
            self.logger.info(f"New replay generation completed: {result.file_size} bytes, {result.total_duration:.1f}s, {result.user_count} users, {processing_time:.2f}s processing time")
            
            # ファイル名生成
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            if user:
                filename = f"replay_{user.display_name}_{duration:.0f}s_{timestamp}.wav"
                description = f"@{user.display_name} の録音です（過去{duration:.1f}秒分"
            else:
                filename = f"replay_all_{result.user_count}users_{duration:.0f}s_{timestamp}.wav"
                description = f"全員の録音です（過去{duration:.1f}秒分、{result.user_count}人"
            
            if normalize:
                description += "、正規化済み"
            description += "）"
            
            # 最終出力は既存の音声処理パイプラインへ統一
            stage_outputs: Dict[str, bytes] = {}
            processed_audio = await self._process_audio_buffer(
                io.BytesIO(result.audio_data),
                normalize=normalize,
                debug_stage_output=stage_outputs if debug_audio_stages else None,
            )

            # ファイルサイズチェック（Discord制限: 25MB）
            file_size_mb = len(processed_audio) / (1024 * 1024)
            if file_size_mb > 24:  # 余裕を持って24MBで制限
                await ctx.followup.send(
                    content=f"❌ ファイルサイズが大きすぎます: {file_size_mb:.1f}MB\n"
                            f"短い時間（{duration/2:.0f}秒以下）で再試行してください。",
                    ephemeral=True
                )
                return False
            
            self._store_replay_result(
                guild_id=ctx.guild.id,
                user_id=user.id if user else None,
                duration=duration,
                filename=filename,
                normalize=normalize,
                data=processed_audio,
            )

            # Discordファイルとして送信
            file = discord.File(io.BytesIO(processed_audio), filename=filename)
            
            # レスポンス更新（ファイル添付）
            embed = discord.Embed(
                title="🎵 録音完了（新システム）",
                description=description,
                color=discord.Color.green()
            )
            
            embed.add_field(
                name="📊 詳細情報",
                value=f"ファイルサイズ: {file_size_mb:.2f}MB\n"
                      f"音声長: {result.total_duration:.1f}秒\n"
                      f"サンプルレート: {result.sample_rate}Hz\n"
                      f"チャンネル数: {result.channels}\n"
                      f"処理時間: {processing_time:.2f}秒",
                inline=False
            )
            
            embed.set_footer(text=f"新録音システム • {timestamp}")
            
            await ctx.followup.send(
                content="",
                embed=embed,
                file=file,
                ephemeral=True
            )
            await self._maybe_send_replay_debug_stages(
                ctx=ctx,
                enabled=debug_audio_stages,
                guild_id=ctx.guild.id,
                base_name=filename.rsplit(".", 1)[0],
                raw_audio=result.audio_data,
                stage_outputs=stage_outputs,
            )
            
            self.logger.info(f"New replay sent successfully: {filename}")
            return True
            
        except Exception as e:
            self.logger.error(f"New replay processing failed: {e}", exc_info=True)
            try:
                await ctx.followup.send(
                    content=f"❌ 新システムでの録音処理中にエラーが発生しました: {str(e)}\n"
                            "古いシステムでの処理をお試しください。",
                    ephemeral=True
                )
            except Exception as edit_error:
                self.logger.error(f"Failed to edit response after error: {edit_error}")
            return False
    
    def _mix_multiple_audio_streams(self, user_audio_dict: dict) -> bytes:
        """複数ユーザーの音声をミキシング（重ね合わせ）"""
        import numpy as np
        import wave
        import io
        
        try:
            self.logger.info(f"Mixing audio from {len(user_audio_dict)} users")
            
            # 各ユーザーの音声データを取得し、numpy配列に変換
            audio_arrays = []
            max_length = 0
            sample_rate = None
            channels = None
            
            for user_id, audio_data in user_audio_dict.items():
                if not audio_data or len(audio_data) < 44:  # WAVヘッダーサイズチェック
                    self.logger.warning(f"User {user_id}: Invalid audio data (size: {len(audio_data)})")
                    continue
                
                try:
                    # WAVデータの先頭部分をデバッグ出力
                    header = audio_data[:12] if len(audio_data) >= 12 else audio_data
                    self.logger.info(f"User {user_id}: Audio header: {header[:8]} (first 8 bytes)")
                    self.logger.info(f"User {user_id}: Audio size: {len(audio_data)} bytes")
                    
                    # RIFFヘッダーチェック
                    if not audio_data.startswith(b'RIFF'):
                        self.logger.error(f"User {user_id}: Invalid WAV format - missing RIFF header")
                        self.logger.debug(f"User {user_id}: Data starts with: {audio_data[:16]}")
                        continue
                    
                    # WAVデータを解析
                    audio_io = io.BytesIO(audio_data)
                    with wave.open(audio_io, 'rb') as wav:
                        frames = wav.readframes(-1)
                        params = wav.getparams()
                        self.logger.info(f"User {user_id}: WAV params - frames: {len(frames)} bytes, rate: {params.framerate}, channels: {params.nchannels}, frames_total: {params.nframes}")
                        
                        if sample_rate is None:
                            sample_rate = params.framerate
                            channels = params.nchannels
                        elif sample_rate != params.framerate or channels != params.nchannels:
                            self.logger.warning(f"User {user_id}: Audio format mismatch (sr: {params.framerate}, ch: {params.nchannels})")
                            continue
                        
                        # バイトデータをnumpy配列に変換（16bit前提）
                        audio_array = np.frombuffer(frames, dtype=np.int16)
                        
                        # ステレオの場合はモノラルに変換
                        if channels == 2:
                            audio_array = audio_array.reshape(-1, 2)
                            audio_array = np.mean(audio_array, axis=1).astype(np.int16)
                        
                        audio_arrays.append(audio_array)
                        max_length = max(max_length, len(audio_array))
                        
                        self.logger.info(f"User {user_id}: {len(audio_array)} samples, {params.framerate}Hz")
                
                except Exception as wav_error:
                    self.logger.error(f"Failed to process audio for user {user_id}: {wav_error}")
                    continue
            
            if not audio_arrays:
                self.logger.error("No valid audio arrays to mix")
                return b""
            
            if len(audio_arrays) == 1:
                # 1人だけの場合はそのまま返す
                mixed_array = audio_arrays[0]
            else:
                # 全配列を同じ長さにパディング
                padded_arrays = []
                for arr in audio_arrays:
                    if len(arr) < max_length:
                        padded = np.zeros(max_length, dtype=np.int16)
                        padded[:len(arr)] = arr
                        padded_arrays.append(padded)
                    else:
                        padded_arrays.append(arr[:max_length])
                
                # 音声をミキシング（平均値を取って音量調整）
                mixed_array = np.zeros(max_length, dtype=np.float32)
                
                for arr in padded_arrays:
                    mixed_array += arr.astype(np.float32)
                
                # 平均値を取って音量を調整（クリッピング防止）
                mixed_array = mixed_array / len(padded_arrays)
                
                # 音量を少し上げる（70%程度）
                mixed_array *= 0.7
                
                # クリッピング防止
                mixed_array = np.clip(mixed_array, -32767, 32767)
                mixed_array = mixed_array.astype(np.int16)
            
            # WAVファイルとして出力
            output = io.BytesIO()
            with wave.open(output, 'wb') as wav_out:
                wav_out.setnchannels(1)  # モノラル
                wav_out.setsampwidth(2)  # 16bit
                wav_out.setframerate(sample_rate)
                wav_out.writeframes(mixed_array.tobytes())
            
            mixed_wav = output.getvalue()
            self.logger.info(f"Mixed audio created: {len(mixed_wav)} bytes, {len(mixed_array)} samples")
            
            return mixed_wav
            
        except ImportError:
            self.logger.error("NumPy not available, audio mixing disabled")
            # フォールバック: 最初のユーザーの音声のみ返す
            if user_audio_dict:
                return list(user_audio_dict.values())[0]
            return b""
        
        except Exception as e:
            self.logger.error(f"Audio mixing failed: {e}", exc_info=True)
            # フォールバック: 最初のユーザーの音声のみ返す
            if user_audio_dict:
                return list(user_audio_dict.values())[0]
            return b""
    
    @discord.slash_command(name="recording_callback_test", description="RecordingCallbackManagerの状態をテストします")
    async def recording_callback_test(self, ctx):
        """RecordingCallbackManagerの状態をテスト"""
        try:
            from utils.recording_callback_manager import recording_callback_manager
            
            # バッファ状態を取得
            status = recording_callback_manager.get_buffer_status()
            
            # 最近の音声データを取得してテスト
            guild_id = ctx.guild.id
            recent_audio = await recording_callback_manager.get_recent_audio(guild_id, duration_seconds=10.0)
            
            # レスポンス作成
            embed = discord.Embed(
                title="🔍 RecordingCallbackManager テスト結果",
                color=discord.Color.green()
            )
            
            embed.add_field(
                name="システム状態",
                value=f"初期化: {'✅' if status.get('initialized', False) else '❌'}\n"
                      f"ギルド数: {status.get('total_guilds', 0)}\n" 
                      f"ユーザー数: {status.get('total_users', 0)}\n"
                      f"音声チャンク数: {status.get('total_chunks', 0)}",
                inline=False
            )
            
            embed.add_field(
                name="最近の音声データ",
                value=f"過去10秒間: {len(recent_audio)}チャンク\n"
                      f"合計データサイズ: {sum(len(chunk.data) for chunk in recent_audio):,}バイト",
                inline=False
            )
            
            if recent_audio:
                # 最新チャンクの詳細
                latest = recent_audio[-1]
                embed.add_field(
                    name="最新音声チャンク",
                    value=f"ユーザーID: {latest.user_id}\n"
                          f"サイズ: {len(latest.data):,}バイト\n"
                          f"長さ: {latest.duration:.2f}秒\n"
                          f"サンプルレート: {latest.sample_rate}Hz",
                    inline=False
                )
            
            embed.set_footer(text=f"テスト時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            
            await ctx.respond(embed=embed, ephemeral=True)
            
        except ImportError:
            await ctx.respond(
                "❌ RecordingCallbackManagerが利用できません。\n"
                "録音システムが正しく初期化されているか確認してください。",
                ephemeral=True
            )
        except Exception as e:
            self.logger.error(f"RecordingCallbackManager test failed: {e}")
            await ctx.respond(
                f"❌ テストが失敗しました: {e}",
                ephemeral=True
            )
    
    @discord.slash_command(name="replay_buffer_test", description="ReplayBufferManagerの状態をテストします")
    async def replay_buffer_test(self, ctx):
        """ReplayBufferManagerの状態をテスト"""
        try:
            from utils.replay_buffer_manager import replay_buffer_manager
            
            if not replay_buffer_manager:
                await ctx.respond(
                    "❌ ReplayBufferManagerが初期化されていません。",
                    ephemeral=True
                )
                return
            
            # 統計情報を取得
            stats = await replay_buffer_manager.get_stats()
            
            # テスト用の音声データ取得を試行
            guild_id = ctx.guild.id
            test_result = await replay_buffer_manager.get_replay_audio(
                guild_id=guild_id,
                duration_seconds=5.0,
                user_id=None,
                normalize=True,
                mix_users=True
            )
            
            # レスポンス作成
            embed = discord.Embed(
                title="🔍 ReplayBufferManager テスト結果",
                color=discord.Color.blue()
            )
            
            embed.add_field(
                name="📈 統計情報",
                value=f"総リクエスト数: {stats.get('total_requests', 0)}\n"
                      f"成功リクエスト: {stats.get('successful_requests', 0)}\n"
                      f"失敗リクエスト: {stats.get('failed_requests', 0)}\n"
                      f"キャッシュヒット: {stats.get('cache_hits', 0)}\n"
                      f"平均処理時間: {stats.get('average_generation_time', 0):.3f}秒",
                inline=False
            )
            
            embed.add_field(
                name="💾 システム状態",
                value=f"キャッシュサイズ: {stats.get('cache_size', 0)}\n"
                      f"処理中リクエスト: {stats.get('active_requests', 0)}",
                inline=False
            )
            
            if test_result:
                embed.add_field(
                    name="🎵 テスト音声データ",
                    value=f"ファイルサイズ: {test_result.file_size:,}バイト\n"
                          f"音声長: {test_result.total_duration:.2f}秒\n"
                          f"ユーザー数: {test_result.user_count}\n"
                          f"サンプルレート: {test_result.sample_rate}Hz\n"
                          f"チャンネル数: {test_result.channels}",
                    inline=False
                )
                embed.color = discord.Color.green()
            else:
                embed.add_field(
                    name="⚠️ テスト結果",
                    value="過去5秒間の音声データが見つかりませんでした。\n"
                          "音声リレーが動作しているか確認してください。",
                    inline=False
                )
                embed.color = discord.Color.orange()
            
            embed.set_footer(text=f"テスト時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            
            await ctx.respond(embed=embed, ephemeral=True)
            
        except ImportError:
            await ctx.respond(
                "❌ ReplayBufferManagerが利用できません。\n"
                "新しい録音システムが正しく初期化されているか確認してください。",
                ephemeral=True
            )
        except Exception as e:
            self.logger.error(f"ReplayBufferManager test failed: {e}")
            await ctx.respond(
                f"❌ テストが失敗しました: {e}",
                ephemeral=True
            )

    @discord.slash_command(name="replay_diag", description="リプレイ用の録音状態を診断します")
    async def replay_diag(
        self,
        ctx,
        user: discord.Option(discord.Member, "対象ユーザー（省略時は全員）", required=False) = None,
        duration: discord.Option(float, "確認する時間範囲（秒）", default=30.0, min_value=5.0, max_value=300.0) = 30.0,
    ):
        """リプレイ前に音声バッファの状況を確認する診断コマンド"""
        await ctx.defer(ephemeral=True)
        guild_id = ctx.guild.id

        recorder_summary = self.real_time_recorder.get_buffer_health_summary(
            guild_id, user.id if user else None
        )
        recorder_lines = []
        if recorder_summary["entries"]:
            for entry in recorder_summary["entries"]:
                mention = f"<@{entry['user_id']}>"
                recorder_lines.append(
                    f"{mention}: {entry['chunk_count']}チャンク / 最終 {entry['seconds_since_last']:.1f}秒前"
                )
        else:
            target_label = user.mention if user else "ギルド全体"
            recorder_lines.append(f"{target_label} の連続バッファにデータがありません")

        callback_lines = []
        recent_chunks = []
        try:
            from utils.recording_callback_manager import recording_callback_manager

            if recording_callback_manager and recording_callback_manager.is_initialized:
                callback_lines.append("初期化状態: ✅")
                recent_chunks = await recording_callback_manager.get_recent_audio(
                    guild_id=guild_id,
                    duration_seconds=duration,
                    user_id=user.id if user else None,
                )
            else:
                callback_lines.append("初期化状態: ❌")
        except Exception as e:
            callback_lines.append(f"情報取得に失敗: {e}")

        if recent_chunks:
            latest = recent_chunks[-1]
            age = max(0.0, time.time() - latest.timestamp)
            callback_lines.append(f"過去{duration:.0f}秒のチャンク: {len(recent_chunks)}件")
            callback_lines.append(f"最終チャンク: <@{latest.user_id}> / {age:.1f}秒前")
        else:
            callback_lines.append(f"過去{duration:.0f}秒で取得できたチャンクはありません")

        embed = discord.Embed(
            title="🔍 リプレイ診断",
            description="`/replay` 実行前の録音状態を確認しました。",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="RealTimeAudioRecorder", value="\n".join(recorder_lines), inline=False)
        embed.add_field(name="RecordingCallbackManager", value="\n".join(callback_lines), inline=False)
        embed.set_footer(text="チャンクが0件の場合はボイスチャット側で音声が出ているか確認してください。")

        await ctx.followup.send(embed=embed, ephemeral=True)

    @discord.slash_command(name="replay_probe", description="録音バッファの最新音声を診断用に取得します")
    async def replay_probe(
        self,
        ctx,
        user: discord.Option(discord.Member, "対象ユーザー（省略時は全員）", required=False) = None,
        duration: discord.Option(float, "確認する時間範囲（秒）", default=10.0, min_value=5.0, max_value=60.0) = 10.0,
    ):
        """RecordingCallbackManagerから最新チャンクを取得し診断用WAVを返す"""
        await ctx.defer(ephemeral=True)

        try:
            manager = recording_callback_manager
            if not manager or not manager.is_initialized:
                await ctx.followup.send(
                    "❌ RecordingCallbackManager が初期化されていません。\n"
                    "録音機能が有効で、ボイスチャンネルで音声が発生しているか確認してください。",
                    ephemeral=True,
                )
                return

            chunks = await manager.get_recent_audio(
                guild_id=ctx.guild.id,
                duration_seconds=duration,
                user_id=user.id if user else None,
            )

            if not chunks:
                await ctx.followup.send(
                    "⚠️ 診断用の音声チャンクを取得できませんでした。\n"
                    "録音機能が有効で、ボイスチャンネルで音声が発生しているか確認してください。",
                    ephemeral=True,
                )
                return

            latest = chunks[-1]
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"probe_{latest.user_id}_{duration:.0f}s_{timestamp}.wav"
            discord_file = discord.File(io.BytesIO(latest.data), filename=filename)
            await ctx.followup.send(
                f"🎧 音声サンプル（ユーザーID: {latest.user_id}, {latest.duration:.2f}s）",
                files=[discord_file],
                ephemeral=True,
            )
        except Exception as e:
            self.logger.error(f"Replay probe failed: {e}", exc_info=True)
            await ctx.followup.send(f"❌ 診断に失敗しました: {e}", ephemeral=True)

    async def _process_direct_capture_replay_async(self, ctx, duration: float, user, normalize: bool):
        """直接音声キャプチャシステムでのreplayコマンド処理"""
        try:
            from datetime import datetime
            
            self.logger.info(f"Starting direct capture replay: guild={ctx.guild.id}, duration={duration}s")
            
            # DirectAudioCaptureを初期化（必要に応じて）
            if direct_audio_capture.bot is None:
                direct_audio_capture.bot = self.bot
            
            # 音声キャプチャを開始（まだ開始されていない場合）
            capture_success = await direct_audio_capture.start_capture(ctx.guild.id)
            if not capture_success:
                await ctx.followup.send(
                    "❌ 音声キャプチャの開始に失敗しました。ボットがボイスチャンネルに接続していることを確認してください。",
                    ephemeral=True
                )
                return
            
            # キャプチャ状況を確認
            status = direct_audio_capture.get_status()
            self.logger.info(f"Direct capture status: {status}")
            
            # キャプチャが十分なデータを生成するまで待機（少なくとも4秒）
            self.logger.info(f"Direct capture: Waiting for audio data generation...")
            await asyncio.sleep(4.0)
            
            # 音声データを取得
            audio_chunks = await direct_audio_capture.get_recent_audio(
                guild_id=ctx.guild.id,
                duration_seconds=duration,
                user_id=user.id if user else None
            )
            
            if not audio_chunks:
                # エラーメッセージは音声リレーを隠した親切な内容
                await ctx.followup.send(
                    f"❌ {user.mention if user else '@全員'} の過去{duration}秒間の音声データが見つかりません。\n"
                    "ボイスチャンネルで音声が発生してから、少し時間をおいて再度お試しください。",
                    ephemeral=True
                )
                return
            
            # WAVファイルを作成
            wav_data = await direct_audio_capture.create_wav_file(audio_chunks)
            if not wav_data:
                await ctx.followup.send(
                    "❌ 音声ファイルの作成に失敗しました。音声データが破損している可能性があります。",
                    ephemeral=True
                )
                return
            
            # 正規化処理（オプション）
            if normalize:
                try:
                    # 一時ファイルに保存して正規化
                    import tempfile
                    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
                        temp_file.write(wav_data)
                        temp_path = temp_file.name
                    
                    # 正規化実行
                    normalized_path = await self.audio_processor.normalize_audio(temp_path)
                    
                    if normalized_path:
                        # 正規化されたファイルを読み込み
                        with open(normalized_path, 'rb') as f:
                            wav_data = f.read()
                        
                        # 一時ファイル削除
                        import os
                        os.unlink(temp_path)
                        if normalized_path != temp_path:
                            os.unlink(normalized_path)
                        
                        self.logger.info(f"Direct capture: Audio normalized successfully")
                    else:
                        # 正規化失敗時は一時ファイルのみ削除
                        import os
                        os.unlink(temp_path)
                        self.logger.warning(f"Direct capture: Normalization failed, using original audio")
                        
                except Exception as norm_e:
                    self.logger.warning(f"Direct capture: Normalization failed: {norm_e}, using original audio")
            
            # ファイル名を生成
            timestamp = datetime.now().strftime("%m%d_%H%M%S")
            if user:
                filename = f"recording_{user.display_name}_{duration}s_{timestamp}.wav"
            else:
                user_count = len(set(chunk.user_id for chunk in audio_chunks))
                filename = f"recording_all_{user_count}users_{duration}s_{timestamp}.wav"
            
            # Discord制限内かチェック
            if len(wav_data) > 25 * 1024 * 1024:  # 25MB
                await ctx.followup.send(
                    f"⚠️ 音声ファイルが大きすぎます（{len(wav_data)//1024//1024}MB）。\n"
                    f"時間を短く設定するか、特定のユーザーを指定してください。",
                    ephemeral=True
                )
                return
            
            self._store_replay_result(
                guild_id=ctx.guild.id,
                user_id=user.id if user else None,
                duration=duration,
                filename=filename,
                normalize=normalize,
                data=wav_data,
            )

            # ファイルとして送信
            import io
            file_obj = discord.File(
                io.BytesIO(wav_data),
                filename=filename
            )
            
            # 成功メッセージと共に送信
            total_duration = sum(chunk.duration for chunk in audio_chunks)
            chunk_count = len(audio_chunks)
            
            message = (
                f"🎵 **音声録音完了** (`{filename}`)\n"
                f"📊 **音声情報**: {total_duration:.1f}秒間, {chunk_count}チャンク\n"
                f"💾 **ファイルサイズ**: {len(wav_data)//1024}KB\n"
                f"🔧 **処理**: {'ノーマライズ済み' if normalize else '無加工'}\n"
                f"🎯 **対象**: {user.mention if user else '全員'}"
            )
            
            await ctx.followup.send(
                content=message,
                file=file_obj,
                ephemeral=True
            )
            
            self.logger.info(f"Direct capture replay completed: {len(wav_data)} bytes, {total_duration:.1f}s")
            
        except Exception as e:
            self.logger.error(f"Direct capture replay failed: {e}", exc_info=True)
            await ctx.followup.send(
                f"❌ 音声処理中にエラーが発生しました: {e}",
                ephemeral=True
            )


def setup(bot):
    """Cogのセットアップ"""
    bot.add_cog(RecordingCog(bot, bot.config))
