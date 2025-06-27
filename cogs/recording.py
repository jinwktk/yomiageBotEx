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
from discord import FFmpegPCMAudio, PCMVolumeTransformer

from utils.recording import RecordingManager, RecordingSink


class RecordingCog(commands.Cog):
    """録音・リプレイ機能を提供するCog"""
    
    def __init__(self, bot: commands.Bot, config: Dict[str, Any]):
        self.bot = bot
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.recording_manager = RecordingManager(config)
        self.recording_enabled = config.get("recording", {}).get("enabled", False)
        
        # ギルドごとの録音シンク
        self.recording_sinks: Dict[int, RecordingSink] = {}
        
        # クリーンアップタスクを開始
        if self.recording_enabled:
            asyncio.create_task(self.recording_manager.start_cleanup_task())
    
    def cog_unload(self):
        """Cogアンロード時のクリーンアップ"""
        for sink in self.recording_sinks.values():
            sink.cleanup()
        self.recording_sinks.clear()
    
    async def rate_limit_delay(self):
        """レート制限対策の遅延"""
        delay = random.uniform(*self.config["bot"]["rate_limit_delay"])
        await asyncio.sleep(delay)
    
    def get_recording_sink(self, guild_id: int) -> RecordingSink:
        """ギルド用の録音シンクを取得"""
        if guild_id not in self.recording_sinks:
            self.recording_sinks[guild_id] = RecordingSink(
                self.recording_manager, guild_id
            )
        return self.recording_sinks[guild_id]
    
    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """ボイス状態変更時の録音管理"""
        if not self.recording_enabled:
            return
        
        if member.bot:  # ボット自身の変更は無視
            return
        
        guild = member.guild
        voice_client = guild.voice_client
        
        if not voice_client or not voice_client.is_connected():
            return
        
        # ボットと同じチャンネルでの変更のみ処理
        bot_channel = voice_client.channel
        
        # ユーザーがボットのいるチャンネルに参加した場合は録音開始
        if before.channel != bot_channel and after.channel == bot_channel:
            sink = self.get_recording_sink(guild.id)
            if not sink.is_recording:
                sink.start_recording()
        
        # チャンネルが空になった場合は録音停止
        elif before.channel == bot_channel and after.channel != bot_channel:
            # ボット以外のメンバー数をチェック
            members_count = len([m for m in bot_channel.members if not m.bot])
            if members_count == 0:
                sink = self.get_recording_sink(guild.id)
                if sink.is_recording:
                    sink.stop_recording()
    
    @app_commands.command(name="replay", description="最近の音声を録音して再生します")
    @app_commands.describe(
        duration="録音する時間（秒）。最大300秒まで",
        volume="再生音量（0.1-2.0）"
    )
    async def replay_command(
        self, 
        interaction: discord.Interaction, 
        duration: int = 30,
        volume: float = 1.0
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
        
        if volume < 0.1 or volume > 2.0:
            await interaction.response.send_message(
                "❌ 音量は0.1〜2.0で指定してください。",
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
                requester_id=interaction.user.id
            )
            
            if not recording_id:
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
            
            # 音声を再生
            voice_client = interaction.guild.voice_client
            if voice_client.is_playing():
                voice_client.stop()
            
            # FFmpegで音声ファイルを読み込み
            audio_source = FFmpegPCMAudio(str(recording_path))
            
            # 音量調整
            if volume != 1.0:
                audio_source = PCMVolumeTransformer(audio_source, volume=volume)
            
            voice_client.play(audio_source)
            
            await interaction.followup.send(
                f"🎵 録音を再生中... ({duration}秒, 音量: {volume:.1f})",
                ephemeral=True
            )
            
            self.logger.info(f"Replaying {duration}s audio for {interaction.user} in {interaction.guild.name}")
            
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