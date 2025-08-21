"""
RecordingCog v2 - シンプルな録音・リプレイ機能
- リアルタイム音声録音
- /replayコマンド
"""

import logging
import tempfile
from pathlib import Path

import discord
from discord.ext import commands

from utils.audio_recorder import AudioRecorderV2

logger = logging.getLogger(__name__)

class RecordingCogV2(commands.Cog):
    """録音機能Cog"""
    
    def __init__(self, bot):
        self.bot = bot
        self.config = bot.config.get('recording', {})
        
        # 録音機能が有効かチェック
        self.enabled = self.config.get('enabled', True)
        
        # 録音マネージャー
        self.recorder = None
        if self.enabled:
            self.recorder = AudioRecorderV2(self.config)
        
        logger.info(f"RecordingCog v2 initialized - Enabled: {self.enabled}")
    
    @discord.slash_command(name="replay", description="録音した音声を再生")
    async def replay_command(self, ctx: discord.ApplicationContext,
                           duration: discord.Option(int, "再生する秒数（デフォルト: 30秒）", required=False, default=30)):
        """録音リプレイコマンド"""
        await ctx.defer(ephemeral=True)
        
        try:
            if not self.enabled:
                await ctx.followup.send("❌ 録音機能が無効になっています", ephemeral=True)
                return
            
            # VoiceClientチェック
            voice_cog = self.bot.get_cog('VoiceCogV2')
            if not voice_cog:
                await ctx.followup.send("❌ ボイス機能が利用できません", ephemeral=True)
                return
            
            voice_client = voice_cog.get_voice_client(ctx.guild.id)
            if not voice_client:
                await ctx.followup.send("❌ ボイスチャンネルに接続していません", ephemeral=True)
                return
            
            # 音声データ取得
            audio_data = await self.recorder.get_recent_audio(ctx.guild.id, duration)
            if not audio_data:
                await ctx.followup.send("❌ 録音データが見つかりません", ephemeral=True)
                return
            
            # 一時ファイルに保存
            with tempfile.NamedTemporaryFile(delete=False, suffix='.wav') as temp_file:
                temp_file.write(audio_data.getvalue())
                temp_file.flush()
                
                # Discordに送信
                file = discord.File(temp_file.name, filename=f"replay_{duration}s.wav")
                await ctx.followup.send(
                    f"🎵 録音データ（{duration}秒）", 
                    file=file, 
                    ephemeral=True
                )
                
                logger.info(f"Replay sent - Guild: {ctx.guild.name}, Duration: {duration}s")
                
                # 一時ファイル削除
                Path(temp_file.name).unlink(missing_ok=True)
                
        except Exception as e:
            logger.error(f"Replay command error: {e}", exc_info=True)
            await ctx.followup.send("❌ リプレイ中にエラーが発生しました", ephemeral=True)
    
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """VC状態変更時の録音処理"""
        if not self.enabled or member.bot:
            return
        
        try:
            # ユーザーがVCに参加した場合 - 録音開始
            if after.channel and not before.channel:
                await self.handle_user_joined(member, after.channel)
            
            # ユーザーがVCから退出した場合 - 録音停止チェック
            elif before.channel and not after.channel:
                await self.handle_user_left(member, before.channel)
                
        except Exception as e:
            logger.error(f"Recording voice state error: {e}", exc_info=True)
    
    async def handle_user_joined(self, member: discord.Member, channel: discord.VoiceChannel):
        """ユーザーVC参加時の録音開始"""
        try:
            voice_cog = self.bot.get_cog('VoiceCogV2')
            if not voice_cog:
                return
            
            voice_client = voice_cog.get_voice_client(member.guild.id)
            if not voice_client:
                return
            
            # 録音開始（既に録音中の場合はスキップ）
            if not self.recorder.is_recording(member.guild.id):
                await self.recorder.start_recording(voice_client)
                logger.info(f"Started recording for {member.display_name} in {channel.name}")
                
        except Exception as e:
            logger.error(f"Handle user joined error: {e}", exc_info=True)
    
    async def handle_user_left(self, member: discord.Member, channel: discord.VoiceChannel):
        """ユーザーVC退出時の録音停止チェック"""
        try:
            voice_cog = self.bot.get_cog('VoiceCogV2')
            if not voice_cog:
                return
            
            voice_client = voice_cog.get_voice_client(member.guild.id)
            if not voice_client:
                return
            
            # チャンネルにBot以外のユーザーがいなくなった場合は録音停止
            human_members = [m for m in channel.members if not m.bot]
            if not human_members:
                await self.recorder.stop_recording(voice_client)
                logger.info(f"Stopped recording in {channel.name} (no users)")
                
        except Exception as e:
            logger.error(f"Handle user left error: {e}", exc_info=True)
    
    def is_recording(self, guild_id: int) -> bool:
        """録音中かチェック"""
        if not self.enabled or not self.recorder:
            return False
        return self.recorder.is_recording(guild_id)

def setup(bot):
    bot.add_cog(RecordingCogV2(bot))