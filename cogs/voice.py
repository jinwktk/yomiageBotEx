"""
VoiceCog v2 - シンプルなVC操作機能
- 自動参加・退出
- 手動参加・退出コマンド
"""

import logging
import asyncio
from typing import Optional

import discord
from discord.ext import commands

logger = logging.getLogger(__name__)

class VoiceCogV2(commands.Cog):
    """ボイスチャンネル操作Cog"""
    
    def __init__(self, bot):
        self.bot = bot
        self.config = bot.config.get('bot', {})
        
        # 接続状態管理
        self.connected_channels = {}  # guild_id: voice_client
        
        logger.info("VoiceCog v2 initialized")
    
    @discord.slash_command(name="join", description="ボイスチャンネルに参加")
    async def join_command(self, ctx: discord.ApplicationContext):
        """手動VC参加コマンド"""
        await ctx.defer(ephemeral=True)
        
        try:
            # ユーザーがVCにいるかチェック
            if not ctx.author.voice:
                await ctx.followup.send("ボイスチャンネルに参加してからコマンドを実行してください", ephemeral=True)
                return
            
            channel = ctx.author.voice.channel
            result = await self.join_voice_channel(channel)
            
            if result:
                await ctx.followup.send(f"✅ {channel.name} に参加しました", ephemeral=True)
            else:
                await ctx.followup.send("❌ ボイスチャンネルへの参加に失敗しました", ephemeral=True)
                
        except Exception as e:
            logger.error(f"Join command error: {e}", exc_info=True)
            await ctx.followup.send("❌ エラーが発生しました", ephemeral=True)
    
    @discord.slash_command(name="leave", description="ボイスチャンネルから退出")
    async def leave_command(self, ctx: discord.ApplicationContext):
        """手動VC退出コマンド"""
        await ctx.defer(ephemeral=True)
        
        try:
            result = await self.leave_voice_channel(ctx.guild.id)
            
            if result:
                await ctx.followup.send("✅ ボイスチャンネルから退出しました", ephemeral=True)
            else:
                await ctx.followup.send("❌ ボイスチャンネルに接続していません", ephemeral=True)
                
        except Exception as e:
            logger.error(f"Leave command error: {e}", exc_info=True)
            await ctx.followup.send("❌ エラーが発生しました", ephemeral=True)
    
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """VC状態変更時の自動処理"""
        if not self.config.get('auto_join', True):
            return
        
        # Botの状態変更は無視
        if member.bot:
            return
        
        guild = member.guild
        
        try:
            # ユーザーがVCに参加した場合
            if after.channel and not before.channel:
                await self.handle_user_joined(member, after.channel)
            
            # ユーザーがVCから退出した場合
            elif before.channel and not after.channel:
                await self.handle_user_left(member, before.channel)
                
        except Exception as e:
            logger.error(f"Voice state update error: {e}", exc_info=True)
    
    async def handle_user_joined(self, member: discord.Member, channel: discord.VoiceChannel):
        """ユーザーのVC参加処理"""
        guild_id = member.guild.id
        
        # Botが接続していない場合は自動参加
        if guild_id not in self.connected_channels:
            logger.info(f"User {member.display_name} joined {channel.name}, auto-joining...")
            await self.join_voice_channel(channel)
    
    async def handle_user_left(self, member: discord.Member, channel: discord.VoiceChannel):
        """ユーザーのVC退出処理"""
        if not self.config.get('auto_leave', True):
            return
        
        guild_id = member.guild.id
        
        # Botが接続している場合のみチェック
        if guild_id in self.connected_channels:
            # 5秒後にチャンネルユーザー数をチェック
            await asyncio.sleep(5)
            await self.check_empty_channel(guild_id)
    
    async def check_empty_channel(self, guild_id: int):
        """空チャンネルチェックと自動退出"""
        if guild_id not in self.connected_channels:
            return
        
        voice_client = self.connected_channels[guild_id]
        if not voice_client or not voice_client.channel:
            return
        
        # Bot以外のユーザーがいるかチェック
        human_members = [m for m in voice_client.channel.members if not m.bot]
        
        if not human_members:
            logger.info(f"No users in {voice_client.channel.name}, auto-leaving...")
            await self.leave_voice_channel(guild_id)
    
    async def join_voice_channel(self, channel: discord.VoiceChannel) -> bool:
        """ボイスチャンネルに参加"""
        try:
            guild_id = channel.guild.id
            
            # 既に接続している場合
            if guild_id in self.connected_channels:
                current_channel = self.connected_channels[guild_id].channel
                if current_channel.id == channel.id:
                    logger.debug(f"Already connected to {channel.name}")
                    return True
                else:
                    # 別のチャンネルに移動
                    await self.connected_channels[guild_id].move_to(channel)
                    logger.info(f"Moved to {channel.name}")
                    return True
            
            # 新規接続
            voice_client = await channel.connect(timeout=30.0, reconnect=True)
            self.connected_channels[guild_id] = voice_client
            
            logger.info(f"Connected to {channel.name} in {channel.guild.name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to join voice channel: {e}", exc_info=True)
            return False
    
    async def leave_voice_channel(self, guild_id: int) -> bool:
        """ボイスチャンネルから退出"""
        try:
            if guild_id not in self.connected_channels:
                return False
            
            voice_client = self.connected_channels[guild_id]
            channel_name = voice_client.channel.name if voice_client.channel else "Unknown"
            
            await voice_client.disconnect()
            del self.connected_channels[guild_id]
            
            logger.info(f"Disconnected from {channel_name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to leave voice channel: {e}", exc_info=True)
            return False
    
    def get_voice_client(self, guild_id: int) -> Optional[discord.VoiceClient]:
        """指定ギルドのVoiceClientを取得"""
        return self.connected_channels.get(guild_id)
    
    def cog_unload(self):
        """Cog終了時の処理"""
        logger.info("VoiceCog v2 unloading...")

def setup(bot):
    bot.add_cog(VoiceCogV2(bot))