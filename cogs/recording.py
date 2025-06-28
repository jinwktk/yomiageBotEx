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
from discord import app_commands
from discord.ext import commands

from utils.recording import RecordingManager, SimpleRecordingSink
from utils.audio_sink import RealTimeAudioRecorder


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
        
        # クリーンアップタスクを開始
        if self.recording_enabled:
            asyncio.create_task(self.recording_manager.start_cleanup_task())
    
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
            voice_client = guild.voice_client
            if voice_client and voice_client.is_connected():
                self.logger.info(f"Recording: Bot joined, starting recording for user {member.display_name}")
                
                # リアルタイム録音を開始
                try:
                    self.real_time_recorder.start_recording(guild.id, voice_client)
                    self.logger.info(f"Recording: Started real-time recording for {voice_client.channel.name}")
                except Exception as e:
                    self.logger.error(f"Recording: Failed to start real-time recording: {e}")
                    # フォールバック: シミュレーション録音
                    sink = self.get_recording_sink(guild.id)
                    if not sink.is_recording:
                        sink.start_recording()
                        self.logger.info(f"Recording: Started fallback simulation recording for {voice_client.channel.name}")
            else:
                self.logger.warning(f"Recording: No voice client when trying to start recording for {member.display_name}")
        except Exception as e:
            self.logger.error(f"Recording: Failed to handle bot joined with user: {e}")
    
    @app_commands.command(name="replay", description="最近の音声を録音してチャットに投稿します")
    @app_commands.describe(
        duration="録音する時間（秒）。最大300秒まで",
        user="対象ユーザー（省略時は全員の音声をマージ）"
    )
    async def replay_command(
        self, 
        interaction: discord.Interaction, 
        duration: int = 30,
        user: Optional[discord.Member] = None
    ):
        """最近の音声を録音・再生するコマンド"""
        await self.rate_limit_delay()
        
        # 機能が無効の場合
        if not self.recording_enabled:
            await interaction.response.send_message(
                "❌ 録音機能は現在無効になっています。",
                ephemeral=True
            )
            return
        
        # ボットがVCに接続しているか確認
        if not interaction.guild.voice_client:
            await interaction.response.send_message(
                "❌ ボットがボイスチャンネルに接続していません。",
                ephemeral=True
            )
            return
        
        # パラメータ検証
        max_duration = self.config.get("recording", {}).get("max_duration", 300)
        if duration > max_duration or duration < 1:
            await interaction.response.send_message(
                f"❌ 録音時間は1〜{max_duration}秒で指定してください。",
                ephemeral=True
            )
            return
        
        # 応答を遅延（処理時間確保）
        await interaction.response.defer(ephemeral=True)
        
        try:
            # 録音を保存
            recording_id = await self.recording_manager.save_recent_audio(
                guild_id=interaction.guild.id,
                duration_seconds=float(duration),
                requester_id=interaction.user.id,
                target_user_id=user.id if user else None
            )
            
            if not recording_id:
                if user:
                    await interaction.followup.send(
                        f"❌ {user.mention} の録音データが見つかりません。",
                        ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        "❌ 録音データが見つかりません。しばらく音声がない可能性があります。",
                        ephemeral=True
                    )
                return
            
            # 録音ファイルのパスを取得
            recording_path = await self.recording_manager.get_recording_path(recording_id)
            if not recording_path:
                await interaction.followup.send(
                    "❌ 録音ファイルの読み込みに失敗しました。",
                    ephemeral=True
                )
                return
            
            # 録音ファイルをチャットに投稿
            with open(recording_path, "rb") as audio_file:
                file = discord.File(
                    audio_file,
                    filename=f"recording_{recording_id[:8]}.wav"
                )
                
                if user:
                    await interaction.followup.send(
                        f"🎵 {user.mention} の過去{duration}秒間の録音です",
                        file=file
                    )
                else:
                    await interaction.followup.send(
                        f"🎵 全員の過去{duration}秒間の録音です",
                        file=file
                    )
            
            self.logger.info(f"Replaying {duration}s audio (user: {user}) for {interaction.user} in {interaction.guild.name}")
            
        except Exception as e:
            self.logger.error(f"Failed to replay audio: {e}")
            await interaction.followup.send(
                "❌ 音声の再生に失敗しました。",
                ephemeral=True
            )
    
    @app_commands.command(name="recordings", description="最近の録音リストを表示します")
    async def recordings_command(self, interaction: discord.Interaction):
        """録音リストを表示するコマンド"""
        await self.rate_limit_delay()
        
        if not self.recording_enabled:
            await interaction.response.send_message(
                "❌ 録音機能は現在無効になっています。",
                ephemeral=True
            )
            return
        
        try:
            recordings = await self.recording_manager.list_recent_recordings(
                guild_id=interaction.guild.id,
                limit=5
            )
            
            if not recordings:
                await interaction.response.send_message(
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
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            self.logger.error(f"Failed to list recordings: {e}")
            await interaction.response.send_message(
                "❌ 録音リストの取得に失敗しました。",
                ephemeral=True
            )
    
    @app_commands.command(name="clear_buffer", description="音声バッファをクリアします")
    async def clear_buffer_command(self, interaction: discord.Interaction):
        """音声バッファをクリアするコマンド"""
        await self.rate_limit_delay()
        
        if not self.recording_enabled:
            await interaction.response.send_message(
                "❌ 録音機能は現在無効になっています。",
                ephemeral=True
            )
            return
        
        # 権限チェック（管理者のみ）
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ この操作は管理者のみ実行できます。",
                ephemeral=True
            )
            return
        
        try:
            self.recording_manager.clear_buffer(interaction.guild.id)
            await interaction.response.send_message(
                "🗑️ 音声バッファをクリアしました。",
                ephemeral=True
            )
            
        except Exception as e:
            self.logger.error(f"Failed to clear buffer: {e}")
            await interaction.response.send_message(
                "❌ バッファのクリアに失敗しました。",
                ephemeral=True
            )


async def setup(bot: commands.Bot, config: Dict[str, Any]):
    """Cogのセットアップ"""
    await bot.add_cog(RecordingCog(bot, config))