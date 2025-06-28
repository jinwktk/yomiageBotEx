"""
録音・リプレイ機能Cog
- /replayコマンド
- 音声バッファ管理
- 録音ファイル自動クリーンアップ
"""

import asyncio
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
                self.real_time_recorder.start_recording(guild.id, voice_client)
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
                    
                    # 録音状況デバッグ
                    await asyncio.sleep(1)  # 録音開始を待つ
                    self.real_time_recorder.debug_recording_status(guild.id)
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
        await ctx.defer()
        
        if not self.recording_enabled:
            await ctx.respond("⚠️ 録音機能が無効です。", ephemeral=True)
            return
        
        if not ctx.guild.voice_client:
            await ctx.respond("⚠️ 現在録音中ではありません。", ephemeral=True)
            return
        
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
            
            user_audio_buffers = self.real_time_recorder.get_user_audio_buffers(guild_id, user.id if user else None)
            
            # バッファクリーンアップ（Guild別）
            await self.real_time_recorder.clean_old_buffers(guild_id)
            
            if user:
                # 特定ユーザーの音声
                if user.id not in user_audio_buffers or not user_audio_buffers[user.id]:
                    await ctx.respond(f"⚠️ {user.mention} の音声データが見つかりません。", ephemeral=True)
                    return
                
                # 最新のバッファを取得
                sorted_buffers = sorted(user_audio_buffers[user.id], key=lambda x: x[1])
                if not sorted_buffers:
                    await ctx.respond(f"⚠️ {user.mention} の音声データがありません。", ephemeral=True)
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
                
                await ctx.respond(
                    f"🎵 {user.mention} の録音です（{duration}秒分、ノーマライズ済み）",
                    file=discord.File(processed_buffer, filename=filename)
                )
                
            else:
                # 全員の音声をマージ
                if not user_audio_buffers:
                    await ctx.respond("⚠️ 録音データがありません。", ephemeral=True)
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
                    await ctx.respond("⚠️ 有効な録音データがありません。", ephemeral=True)
                    return
                
                # 全員の音声を1つのファイルに結合
                merged_audio = io.BytesIO()
                for audio in all_audio_data:
                    audio.seek(0)
                    merged_audio.write(audio.read())
                
                merged_audio.seek(0)
                
                # マージした音声をノーマライズ処理
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = f"recording_all_{user_count}users_{timestamp}.wav"
                
                processed_buffer = await self._process_audio_buffer(merged_audio)
                
                await ctx.respond(
                    f"🎵 全員の録音です（{user_count}人分、{duration}秒分、ノーマライズ済み）",
                    file=discord.File(processed_buffer, filename=filename)
                )
            
            self.logger.info(f"Replaying {duration}s audio (user: {user}) for {ctx.user} in {ctx.guild.name}")
            
        except Exception as e:
            self.logger.error(f"Failed to replay audio: {e}")
            await ctx.respond(f"⚠️ リプレイに失敗しました: {str(e)}", ephemeral=True)
    
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
    
    @discord.slash_command(name="clear_buffer", description="音声バッファをクリアします")
    async def clear_buffer_command(self, ctx: discord.ApplicationContext):
        """音声バッファをクリアするコマンド"""
        await self.rate_limit_delay()
        
        if not self.recording_enabled:
            await ctx.respond(
                "❌ 録音機能は現在無効になっています。",
                ephemeral=True
            )
            return
        
        # 権限チェック（管理者のみ）
        if not ctx.user.guild_permissions.administrator:
            await ctx.respond(
                "❌ この操作は管理者のみ実行できます。",
                ephemeral=True
            )
            return
        
        try:
            self.recording_manager.clear_buffer(ctx.guild.id)
            await ctx.respond(
                "🗑️ 音声バッファをクリアしました。",
                ephemeral=True
            )
            
        except Exception as e:
            self.logger.error(f"Failed to clear buffer: {e}")
            await ctx.respond(
                "❌ バッファのクリアに失敗しました。",
                ephemeral=True
            )
    
    @discord.slash_command(name="debug_recording", description="録音状況をデバッグします（管理者限定）")
    async def debug_recording_command(self, ctx: discord.ApplicationContext):
        """録音デバッグコマンド"""
        await self.rate_limit_delay()
        
        # 管理者権限チェック
        if not ctx.author.guild_permissions.administrator:
            await ctx.respond(
                "❌ このコマンドは管理者のみ実行できます。",
                ephemeral=True
            )
            return
        
        try:
            # 録音状況のデバッグ
            self.real_time_recorder.debug_recording_status(ctx.guild.id)
            
            # バッファ状況の確認（Guild別）
            buffers = self.real_time_recorder.get_user_audio_buffers(ctx.guild.id)
            
            debug_text = f"📊 **録音デバッグ情報**\n"
            debug_text += f"録音機能有効: {self.recording_enabled}\n"
            debug_text += f"ボット接続状況: {ctx.guild.voice_client is not None}\n"
            
            if ctx.guild.voice_client:
                debug_text += f"接続チャンネル: {ctx.guild.voice_client.channel.name}\n"
                debug_text += f"録音中: {getattr(ctx.guild.voice_client, 'recording', False)}\n"
            
            debug_text += f"バッファユーザー数: {len(buffers)}\n"
            
            for user_id, user_buffers in buffers.items():
                debug_text += f"  - ユーザー {user_id}: {len(user_buffers)} バッファ\n"
            
            await ctx.respond(debug_text, ephemeral=True)
            
        except Exception as e:
            self.logger.error(f"Failed to debug recording: {e}")
            await ctx.respond(
                "❌ デバッグ中にエラーが発生しました。",
                ephemeral=True
            )
    
    @discord.slash_command(name="test_recording", description="録音をテストします（管理者限定）")
    async def test_recording_command(self, ctx: discord.ApplicationContext):
        """録音テストコマンド（録音停止→再開でコールバック確認）"""
        await self.rate_limit_delay()
        
        # 管理者権限チェック
        if not ctx.author.guild_permissions.administrator:
            await ctx.respond(
                "❌ このコマンドは管理者のみ実行できます。",
                ephemeral=True
            )
            return
        
        if not ctx.guild.voice_client:
            await ctx.respond(
                "❌ ボットがボイスチャンネルに接続していません。",
                ephemeral=True
            )
            return
        
        try:
            await ctx.respond("🎙️ 録音テスト中... 5秒後に結果を表示します", ephemeral=True)
            
            guild_id = ctx.guild.id
            voice_client = ctx.guild.voice_client
            
            # 録音を一度停止（コールバックをトリガー）
            self.logger.info(f"Test: Stopping recording for callback trigger")
            await self.real_time_recorder.stop_recording(guild_id)
            
            await asyncio.sleep(2)  # コールバック処理を待つ
            
            # バッファ確認（Guild別）
            buffers = self.real_time_recorder.get_user_audio_buffers(guild_id)
            
            # 録音再開
            self.logger.info(f"Test: Restarting recording")
            await self.real_time_recorder.start_recording(guild_id, voice_client)
            
            await asyncio.sleep(3)  # 結果確認の時間
            
            # 結果表示
            result_text = f"📊 **録音テスト結果**\n"
            result_text += f"取得された音声バッファ数: {len(buffers)}\n"
            
            if buffers:
                for user_id, user_buffers in buffers.items():
                    result_text += f"  - ユーザー {user_id}: {len(user_buffers)} バッファ\n"
                    for i, (buffer, timestamp) in enumerate(user_buffers):
                        buffer_size = len(buffer.getvalue()) if buffer else 0
                        result_text += f"    - バッファ {i+1}: {buffer_size} bytes\n"
            else:
                result_text += "⚠️ 音声データが取得されませんでした\n"
            
            await ctx.followup.send(result_text, ephemeral=True)
            
        except Exception as e:
            self.logger.error(f"Failed to test recording: {e}")
            await ctx.followup.send(
                f"❌ 録音テスト中にエラーが発生しました: {str(e)}",
                ephemeral=True
            )
    
    async def _process_audio_buffer(self, audio_buffer):
        """音声バッファをノーマライズ処理"""
        try:
            import tempfile
            import os
            
            # 一時ファイルに保存
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_input:
                audio_buffer.seek(0)
                temp_input.write(audio_buffer.read())
                temp_input_path = temp_input.name
            
            # ノーマライズ処理
            normalized_path = await self.audio_processor.normalize_audio(temp_input_path)
            
            if normalized_path and normalized_path != temp_input_path:
                # ノーマライズされたファイルを読み込み
                with open(normalized_path, 'rb') as f:
                    processed_data = f.read()
                
                # 処理済みファイルをクリーンアップ
                self.audio_processor.cleanup_temp_files(normalized_path)
            else:
                # ノーマライズに失敗した場合は元のデータを使用
                with open(temp_input_path, 'rb') as f:
                    processed_data = f.read()
            
            # 入力ファイルをクリーンアップ
            self.audio_processor.cleanup_temp_files(temp_input_path)
            
            # 処理済みデータをBytesIOで返す
            import io
            return io.BytesIO(processed_data)
            
        except Exception as e:
            self.logger.error(f"Audio processing failed: {e}")
            # エラー時は元のバッファを返す
            audio_buffer.seek(0)
            return audio_buffer


def setup(bot):
    """Cogのセットアップ"""
    bot.add_cog(RecordingCog(bot, bot.config))