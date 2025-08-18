"""
録音・リプレイ機能Cog
- /replayコマンド
- 音声バッファ管理
- 録音ファイル自動クリーンアップ
"""

import asyncio
import io
import logging
import random
from typing import Dict, Any, Optional

import discord
from discord.ext import commands

from utils.recording import RecordingManager, SimpleRecordingSink
from utils.real_audio_recorder import RealTimeAudioRecorder
from utils.audio_processor import AudioProcessor


class RecordingCog(commands.Cog):
    """録音・リプレイ機能を提供するCog"""
    
    def __init__(self, bot: commands.Bot, config: Dict[str, Any]):
        self.bot = bot
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.recording_manager = RecordingManager(config)
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
    
    def get_recording_sink(self, guild_id: int) -> SimpleRecordingSink:
        """ギルド用の録音シンクを取得"""
        if guild_id not in self.recording_sinks:
            self.recording_sinks[guild_id] = SimpleRecordingSink(
                self.recording_manager, guild_id
            )
        return self.recording_sinks[guild_id]
    
    @commands.Cog.listener()
    async def on_ready(self):
        """Bot準備完了時のクリーンアップタスク開始"""
        if self.recording_enabled and not self.cleanup_task_started:
            asyncio.create_task(self.recording_manager.start_cleanup_task())
            self.cleanup_task_started = True
            self.logger.info("Recording: Cleanup task started")
    
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
        await ctx.defer(ephemeral=True)
        
        if not self.recording_enabled:
            await ctx.respond("⚠️ 録音機能が無効です。", ephemeral=True)
            return
        
        if not ctx.guild.voice_client:
            await ctx.respond("⚠️ 現在録音中ではありません。", ephemeral=True)
            return
        
        # 重い処理を別タスクで実行してボットのブロックを回避
        asyncio.create_task(self._process_replay_async(ctx, duration, user))
        
        # すぐにユーザーに応答
        await ctx.respond("🎵 録音を処理中です...", ephemeral=True)
    
    async def _process_replay_async(self, ctx, duration: float, user):
        """replayコマンドの重い処理を非同期で実行"""
        try:
            import time
            from datetime import datetime, timedelta
            
            # リアルタイム録音データから直接バッファを取得（Guild別）
            guild_id = ctx.guild.id
            
            # TTSManagerは不要になったため削除
            
            # 現在時刻を記録（録音期間計算用）
            current_time = datetime.now()
            start_time = current_time - timedelta(seconds=duration)
            
            # 時刻文字列を生成（日本時間表示用）
            time_range_str = f"{start_time.strftime('%H:%M:%S')}-{current_time.strftime('%H:%M:%S')}"
            date_str = current_time.strftime('%m/%d')
            date_str_for_filename = current_time.strftime('%m%d')  # ファイル名用（スラッシュなし）
            
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
            
            # 時間範囲ベースの音声データ取得（優先処理）
            time_range_audio = None
            if hasattr(self.real_time_recorder, 'get_audio_for_time_range'):
                # 連続バッファから指定時間分の音声を取得
                time_range_audio = self.real_time_recorder.get_audio_for_time_range(guild_id, duration, user.id if user else None)
                self.logger.info(f"Time range audio result: {len(time_range_audio) if time_range_audio else 0} users")
            
            # 時間範囲ベースで音声データが取得できた場合
            if time_range_audio:
                if user:
                    # 特定ユーザーの音声
                    if user.id not in time_range_audio or not time_range_audio[user.id]:
                        # フォールバック前にエラーメッセージ
                        self.logger.warning(f"No time-range audio for user {user.id}, checking if fallback should be used")
                    else:
                        audio_data = time_range_audio[user.id]
                        audio_buffer = io.BytesIO(audio_data)
                        
                        # 一時ファイルに保存してノーマライズ処理
                        filename = f"recording_user{user.id}_{date_str_for_filename}_{time_range_str.replace(':', '')}_{duration}s.wav"
                        
                        processed_buffer = await self._process_audio_buffer(audio_buffer)
                        
                        # 時間精度を向上：指定した時間分のみ切り出し
                        trimmed_buffer = await self._trim_audio_to_duration(processed_buffer, duration)
                        
                        # 音声ファイルを投稿
                        await ctx.followup.send(
                            f"🎵 {user.mention} の録音です（{date_str} {time_range_str}、{duration}秒分、ノーマライズ済み）",
                            file=discord.File(trimmed_buffer, filename=filename),
                            ephemeral=True
                        )
                        return
                
                else:
                    # 全員の音声をマージ
                    # 全ユーザーの音声データを1つのWAVファイルに結合
                    combined_audio = io.BytesIO()
                    user_count = len(time_range_audio)
                    first_user = True
                    
                    for user_id, audio_data in time_range_audio.items():
                        # 0bytes問題を防ぐための厳密な検証
                        if not audio_data:
                            self.logger.warning(f"User {user_id}: No audio data (None)")
                            continue
                        
                        if len(audio_data) <= 44:  # WAVヘッダー以下
                            self.logger.warning(f"User {user_id}: Audio data too small ({len(audio_data)} bytes)")
                            continue
                            
                        if len(audio_data) < 1000:  # 1KB未満は実質無音
                            self.logger.warning(f"User {user_id}: Audio data very small ({len(audio_data)} bytes)")
                        
                        self.logger.info(f"User {user_id}: Adding {len(audio_data)} bytes of audio data")
                        
                        if first_user:
                            # 最初のユーザーはヘッダー込みで追加
                            combined_audio.write(audio_data)
                            first_user = False
                            self.logger.info(f"User {user_id}: Added as first user with header")
                        else:
                            # 2番目以降はヘッダーを除いて音声データのみ追加
                            if len(audio_data) > 44:
                                data_only = audio_data[44:]
                                combined_audio.write(data_only)
                                self.logger.info(f"User {user_id}: Added {len(data_only)} bytes without header")
                    
                    if combined_audio.tell() > 0:
                        combined_audio.seek(0)
                        
                        # 一時ファイルに保存してノーマライズ処理
                        filename = f"recording_all_{user_count}users_{date_str_for_filename}_{time_range_str.replace(':', '')}_{duration}s.wav"
                        
                        processed_buffer = await self._process_audio_buffer(combined_audio)
                        
                        # 時間精度を向上：指定した時間分のみ切り出し
                        trimmed_buffer = await self._trim_audio_to_duration(processed_buffer, duration)
                        
                        # 音声ファイルを投稿
                        await ctx.followup.send(
                            f"🎵 全員の録音です（{date_str} {time_range_str}、{user_count}人、{duration}秒分、ノーマライズ済み）",
                            file=discord.File(trimmed_buffer, filename=filename),
                            ephemeral=True
                        )
                        return
            
            # 時間範囲ベース処理が失敗した場合のみフォールバック
            self.logger.warning(f"Time-range based audio extraction failed or returned empty, falling back to buffer-based method")
            
            # フォールバック：従来の方式（バッファベース）
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
                
                # 時間制限を考慮したバッファを結合
                audio_buffer = io.BytesIO()
                current_time = time.time()
                cutoff_time = current_time - duration  # duration秒前のカットオフ時刻
                
                # カットオフ時刻より新しいバッファのみ使用
                filtered_buffers = [
                    (buffer, timestamp) for buffer, timestamp in sorted_buffers
                    if timestamp >= cutoff_time
                ]
                
                if not filtered_buffers:
                    # カットオフ時刻内にバッファがない場合は最新1個のみ使用
                    filtered_buffers = sorted_buffers[-1:]
                    self.logger.warning(f"No buffers within {duration}s timeframe for user {user.id}, using latest buffer only")
                else:
                    self.logger.info(f"Using {len(filtered_buffers)} buffers within {duration}s timeframe for user {user.id}")
                
                for buffer, timestamp in filtered_buffers:
                    buffer.seek(0)
                    audio_buffer.write(buffer.read())
                
                audio_buffer.seek(0)
                
                # 一時ファイルに保存してノーマライズ処理
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = f"recording_user{user.id}_{date_str_for_filename}_{time_range_str.replace(':', '')}_{duration}s.wav"
                
                processed_buffer = await self._process_audio_buffer(audio_buffer)
                
                # 時間精度を向上：指定した時間分のみ切り出し（フォールバック）
                trimmed_buffer = await self._trim_audio_to_duration(processed_buffer, duration)
                
                # 音声ファイルを投稿
                await ctx.followup.send(
                    f"🎵 {user.mention} の録音です（{date_str} {time_range_str}、{duration}秒分、ノーマライズ済み・フォールバック）",
                    file=discord.File(trimmed_buffer, filename=filename),
                    ephemeral=True
                )
                
            else:
                # 全員の音声をマージ
                if not user_audio_buffers:
                    await ctx.followup.send("⚠️ 録音データがありません。", ephemeral=True)
                    return
                
                # 全ユーザーの音声データを収集・マージ（時間制限付き）
                all_audio_data = []
                user_count = 0
                current_time = time.time()
                cutoff_time = current_time - duration  # duration秒前のカットオフ時刻
                
                for user_id, buffers in user_audio_buffers.items():
                    if not buffers:
                        continue
                    
                    # 時間制限を考慮したバッファを取得
                    sorted_buffers = sorted(buffers, key=lambda x: x[1])
                    
                    # カットオフ時刻より新しいバッファのみ使用
                    filtered_buffers = [
                        (buffer, timestamp) for buffer, timestamp in sorted_buffers
                        if timestamp >= cutoff_time
                    ]
                    
                    if not filtered_buffers:
                        # カットオフ時刻内にバッファがない場合は最新1個のみ使用
                        filtered_buffers = sorted_buffers[-1:]
                        self.logger.warning(f"No buffers within {duration}s timeframe for user {user_id}, using latest buffer only")
                    else:
                        self.logger.info(f"Using {len(filtered_buffers)} buffers within {duration}s timeframe for user {user_id}")
                    
                    user_count += 1
                    
                    # ユーザーごとの音声データを結合
                    user_audio = io.BytesIO()
                    for buffer, timestamp in filtered_buffers:
                        buffer.seek(0)
                        user_audio.write(buffer.read())
                    
                    if user_audio.tell() > 0:  # データがある場合のみ追加
                        user_audio.seek(0)
                        all_audio_data.append(user_audio)
                
                if not all_audio_data:
                    await ctx.followup.send("⚠️ 有効な録音データがありません。", ephemeral=True)
                    return
                
                # 全員の音声を1つのファイルに結合
                merged_audio = io.BytesIO()
                for audio in all_audio_data:
                    audio.seek(0)
                    merged_audio.write(audio.read())
                
                merged_audio.seek(0)
                
                # マージした音声をノーマライズ処理
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = f"recording_all_{user_count}users_{date_str_for_filename}_{time_range_str.replace(':', '')}_{duration}s.wav"
                
                processed_buffer = await self._process_audio_buffer(merged_audio)
                
                # 時間精度を向上：指定した時間分のみ切り出し（フォールバック）
                trimmed_buffer = await self._trim_audio_to_duration(processed_buffer, duration)
                
                # 音声ファイルを投稿
                await ctx.followup.send(
                    f"🎵 全員の録音です（{date_str} {time_range_str}、{user_count}人分、{duration}秒分、ノーマライズ済み・フォールバック）",
                    file=discord.File(trimmed_buffer, filename=filename),
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
    
    async def _trim_audio_to_duration(self, audio_buffer, duration_seconds: float):
        """音声を指定した時間長に正確に切り出し"""
        try:
            import tempfile
            import os
            
            # 一時ファイルに保存
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_input:
                audio_buffer.seek(0)
                temp_input.write(audio_buffer.read())
                temp_input_path = temp_input.name
            
            # AudioProcessorの時間切り出し機能を使用
            if hasattr(self.audio_processor, 'extract_time_range'):
                trimmed_path = await self.audio_processor.extract_time_range(temp_input_path, 0, duration_seconds)
                
                if trimmed_path and trimmed_path != temp_input_path:
                    # 切り出された音声を読み込み
                    with open(trimmed_path, 'rb') as f:
                        trimmed_data = f.read()
                    
                    # 一時ファイルをクリーンアップ
                    self.audio_processor.cleanup_temp_files(temp_input_path)
                    self.audio_processor.cleanup_temp_files(trimmed_path)
                    
                    self.logger.info(f"Successfully trimmed audio to {duration_seconds} seconds")
                    return io.BytesIO(trimmed_data)
                else:
                    self.logger.warning("Audio trimming failed, returning original audio")
                    # 元の音声データを使用
                    with open(temp_input_path, 'rb') as f:
                        original_data = f.read()
                    self.audio_processor.cleanup_temp_files(temp_input_path)
                    return io.BytesIO(original_data)
            else:
                self.logger.warning("extract_time_range method not available, returning original audio")
                # AudioProcessorに時間切り出し機能がない場合は元の音声を返す
                with open(temp_input_path, 'rb') as f:
                    original_data = f.read()
                self.audio_processor.cleanup_temp_files(temp_input_path)
                return io.BytesIO(original_data)
                
        except Exception as e:
            self.logger.error(f"Audio trimming failed: {e}")
            # エラー時は元の音声を返す
            return audio_buffer


def setup(bot):
    """Cogのセットアップ"""
    bot.add_cog(RecordingCog(bot, bot.config))