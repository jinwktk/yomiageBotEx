"""
録音・リプレイ機能Cog
"""

import asyncio
import logging
import random
from typing import Dict, Any

import discord
from discord.ext import commands

from utils.real_audio_recorder import RealTimeAudioRecorder
from utils.audio_processor import AudioProcessor


class RecordingCog(commands.Cog):
    """録音・リプレイ機能を提供するCog"""
    
    def __init__(self, bot: commands.Bot, config: Dict[str, Any]):
        self.bot = bot
        self.config = config
        self.logger = logging.getLogger(__name__)
        # 一時的にNoneを渡す（後で適切に修正が必要）
        self.recording_manager = RealTimeAudioRecorder(None)
        self.recording_enabled = config.get("recording", {}).get("enabled", False)
        
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
                # フォールバック: シミュレーション録音
                sink = self.get_recording_sink(guild.id)
                if not sink.is_recording:
                    sink.start_recording()
                    self.logger.info(f"Recording: Started fallback simulation recording for {bot_channel.name}")
        
        # チャンネルが空になった場合は録音停止
        elif before.channel == bot_channel and after.channel != bot_channel:
            self.logger.info(f"Recording: User {member.display_name} left bot channel {bot_channel.name}")
            # ボット以外のメンバー数をチェック
            members_count = len([m for m in bot_channel.members if not m.bot])
            self.logger.info(f"Recording: Members remaining: {members_count}")
            if members_count == 0:
                # リアルタイム録音を停止
                try:
                    self.real_time_recorder.stop_recording(guild.id, voice_client)
                    self.logger.info(f"Recording: Stopped real-time recording for {bot_channel.name}")
                except Exception as e:
                    self.logger.error(f"Recording: Failed to stop real-time recording: {e}")
                
                # シミュレーション録音も停止
                sink = self.get_recording_sink(guild.id)
                if sink.is_recording:
                    sink.stop_recording()
                    self.logger.info(f"Recording: Stopped simulation recording for {bot_channel.name}")
    
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
    
    @discord.slash_command(name="replay", description="最近の音声を録音ファイルとして投稿します")
    async def replay_command(
        self, 
        ctx: discord.ApplicationContext, 
        duration: discord.Option(float, "録音する時間（秒）", default=30.0, min_value=5.0, max_value=300.0) = 30.0,
        user: discord.Option(discord.Member, "対象ユーザー（省略時は全体）", required=False) = None
    ):
        """録音をリプレイ（bot_simple.pyの実装を統合）"""
        if not self.recording_enabled:
            await ctx.respond("⚠️ 録音機能が無効です。", ephemeral=True)
            return
        
        if not ctx.guild.voice_client:
            await ctx.respond("⚠️ 現在録音中ではありません。", ephemeral=True)
            return
        
        # 処理中であることを即座に応答
        await ctx.respond("🎵 録音を処理中です...", ephemeral=True)
        
        # 重い処理を別タスクで実行してボットのブロックを回避
        asyncio.create_task(self._process_replay_async(ctx, duration, user))
    
    async def _process_replay_async(self, ctx, duration: float, user):
        """replayコマンドの重い処理を非同期で実行"""
        try:
            import io
            from datetime import datetime
            
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
            
            # 新しい時間範囲ベースの音声データ取得を試行
            if hasattr(self.real_time_recorder, 'get_audio_for_time_range'):
                # 連続バッファから指定時間分の音声を取得
                time_range_audio = self.real_time_recorder.get_audio_for_time_range(guild_id, duration, user.id if user else None)
                
                if user:
                    # 特定ユーザーの音声
                    if user.id not in time_range_audio or not time_range_audio[user.id]:
                        await ctx.followup.send(f"⚠️ {user.mention} の過去{duration}秒間の音声データが見つかりません。", ephemeral=True)
                        return
                    
                    audio_data = time_range_audio[user.id]
                    audio_buffer = io.BytesIO(audio_data)
                    
                    # 一時ファイルに保存してノーマライズ処理
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                    filename = f"recording_user{user.id}_{duration}s_{timestamp}.wav"
                    
                    processed_buffer = await self._process_audio_buffer(audio_buffer)
                    
                    await ctx.followup.send(
                        f"🎵 {user.mention} の録音です（過去{duration}秒分、ノーマライズ済み）",
                        file=discord.File(processed_buffer, filename=filename),
                        ephemeral=True
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
                    
                    processed_buffer = await self._process_audio_buffer(combined_audio)
                    
                    await ctx.followup.send(
                        f"🎵 全員の録音です（過去{duration}秒分、{user_count}人、ノーマライズ済み）",
                        file=discord.File(processed_buffer, filename=filename),
                        ephemeral=True
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
                
                processed_buffer = await self._process_audio_buffer(audio_buffer)
                
                await ctx.followup.send(
                    f"🎵 {user.mention} の録音です（約{duration}秒分、ノーマライズ済み）",
                    file=discord.File(processed_buffer, filename=filename),
                    ephemeral=True
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
                
                processed_buffer = await self._process_audio_buffer(merged_audio)
                
                await ctx.followup.send(
                    f"🎵 全員の録音です（{user_count}人分、{duration}秒分、ノーマライズ済み）",
                    file=discord.File(processed_buffer, filename=filename),
                    ephemeral=True
                )
            
            self.logger.info(f"Replaying {duration}s audio (user: {user}) for {ctx.user} in {ctx.guild.name}")
            
        except Exception as e:
            self.logger.error(f"Failed to replay audio: {e}", exc_info=True)
            await ctx.followup.send(f"⚠️ リプレイに失敗しました: {str(e)}", ephemeral=True)
    
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
    
    
    async def _process_audio_buffer(self, audio_buffer):
        """音声バッファをノーマライズ処理（ファイルサイズ制限付き）"""
        try:
            import tempfile
            import os
            
            # ファイルサイズ制限（Discordの上限: 25MB、余裕を持って20MB）
            MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB
            
            # 一時ファイルに保存
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_input:
                audio_buffer.seek(0)
                original_data = audio_buffer.read()
                
                # ファイルサイズチェック
                if len(original_data) > MAX_FILE_SIZE:
                    self.logger.warning(f"Audio file too large: {len(original_data)/1024/1024:.1f}MB > 20MB limit")
                    
                    # 音声データを圧縮/切り取り
                    compression_ratio = MAX_FILE_SIZE / len(original_data)
                    compressed_size = int(len(original_data) * compression_ratio * 0.9)  # 90%まで圧縮
                    
                    # 単純に先頭部分を切り取り（より高度な処理も可能）
                    compressed_data = original_data[:compressed_size]
                    self.logger.info(f"Compressed audio from {len(original_data)/1024/1024:.1f}MB to {len(compressed_data)/1024/1024:.1f}MB")
                    
                    temp_input.write(compressed_data)
                else:
                    temp_input.write(original_data)
                
                temp_input_path = temp_input.name
            
            # ノーマライズ処理
            normalized_path = await self.audio_processor.normalize_audio(temp_input_path)
            
            if normalized_path and normalized_path != temp_input_path:
                # ノーマライズされたファイルを読み込み
                with open(normalized_path, 'rb') as f:
                    processed_data = f.read()
                
                # 再度サイズチェック
                if len(processed_data) > MAX_FILE_SIZE:
                    self.logger.warning(f"Normalized file still too large: {len(processed_data)/1024/1024:.1f}MB")
                    # 圧縮比率を再計算
                    compression_ratio = MAX_FILE_SIZE / len(processed_data)
                    compressed_size = int(len(processed_data) * compression_ratio * 0.9)
                    processed_data = processed_data[:compressed_size]
                    self.logger.info(f"Re-compressed to {len(processed_data)/1024/1024:.1f}MB")
                
                # 処理済みファイルをクリーンアップ
                self.audio_processor.cleanup_temp_files(normalized_path)
            else:
                # ノーマライズに失敗した場合は元のデータを使用
                with open(temp_input_path, 'rb') as f:
                    processed_data = f.read()
                
                # サイズチェック
                if len(processed_data) > MAX_FILE_SIZE:
                    compression_ratio = MAX_FILE_SIZE / len(processed_data)
                    compressed_size = int(len(processed_data) * compression_ratio * 0.9)
                    processed_data = processed_data[:compressed_size]
                    self.logger.info(f"Final compression to {len(processed_data)/1024/1024:.1f}MB")
            
            # 入力ファイルをクリーンアップ
            self.audio_processor.cleanup_temp_files(temp_input_path)
            
            # 最終サイズ確認
            final_size_mb = len(processed_data) / 1024 / 1024
            self.logger.info(f"Final audio file size: {final_size_mb:.1f}MB")
            
            if len(processed_data) > MAX_FILE_SIZE:
                raise Exception(f"Audio file still too large after compression: {final_size_mb:.1f}MB")
            
            # 処理済みデータをBytesIOで返す
            import io
            return io.BytesIO(processed_data)
            
        except Exception as e:
            self.logger.error(f"Audio processing failed: {e}")
            # エラー時は元のバッファを返す（但しサイズ制限適用）
            audio_buffer.seek(0)
            original_data = audio_buffer.read()
            
            MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB
            if len(original_data) > MAX_FILE_SIZE:
                # 緊急時の圧縮
                compression_ratio = MAX_FILE_SIZE / len(original_data)
                compressed_size = int(len(original_data) * compression_ratio * 0.8)
                compressed_data = original_data[:compressed_size]
                self.logger.warning(f"Emergency compression: {len(original_data)/1024/1024:.1f}MB -> {len(compressed_data)/1024/1024:.1f}MB")
                return io.BytesIO(compressed_data)
            
            return io.BytesIO(original_data)
    
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


def setup(bot):
    """Cogのセットアップ"""
    bot.add_cog(RecordingCog(bot, bot.config))