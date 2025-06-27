"""
ボイスチャンネル管理Cog
- スラッシュコマンド（/join, /leave）
- 自動参加・退出機能
"""

import asyncio
import random
import logging
from typing import Dict, Any, Optional
import json
from pathlib import Path

import discord
from discord.ext import commands, tasks


class VoiceCog(commands.Cog):
    """ボイスチャンネル管理機能"""
    
    def __init__(self, bot: commands.Bot, config: Dict[str, Any]):
        self.bot = bot
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.sessions_file = Path("sessions.json")
        self.saved_sessions = self.load_sessions()
        
        # 定期チェックタスクを開始
        if not self.empty_channel_check.is_running():
            self.empty_channel_check.start()
    
    def cog_unload(self):
        """Cogアンロード時のクリーンアップ"""
        self.empty_channel_check.cancel()
    
    def load_sessions(self) -> Dict[int, int]:
        """保存されたセッション情報を読み込み"""
        try:
            if self.sessions_file.exists():
                with open(self.sessions_file, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            self.logger.error(f"Failed to load sessions: {e}")
        return {}
    
    def save_sessions(self):
        """現在のセッション情報を保存"""
        try:
            sessions = {}
            for guild in self.bot.guilds:
                if guild.voice_client and guild.voice_client.channel:
                    sessions[guild.id] = guild.voice_client.channel.id
            
            with open(self.sessions_file, "w", encoding="utf-8") as f:
                json.dump(sessions, f, indent=2)
                
        except Exception as e:
            self.logger.error(f"Failed to save sessions: {e}")
    
    async def rate_limit_delay(self):
        """レート制限対策の遅延"""
        delay = random.uniform(*self.config["bot"]["rate_limit_delay"])
        await asyncio.sleep(delay)
    
    @commands.Cog.listener()
    async def on_ready(self):
        """Bot起動時の処理"""
        # 保存されたセッションの復元
        await self.restore_saved_sessions()
    
    async def restore_saved_sessions(self):
        """保存されたセッションを復元"""
        if not self.saved_sessions:
            return
        
        for guild_id, channel_id in self.saved_sessions.items():
            try:
                guild = self.bot.get_guild(guild_id)
                if not guild:
                    continue
                
                channel = guild.get_channel(channel_id)
                if not channel or not isinstance(channel, discord.VoiceChannel):
                    continue
                
                # チャンネルにユーザーがいるかチェック
                if len(channel.members) == 0:
                    self.logger.info(f"Skipping empty channel: {channel.name} in {guild.name}")
                    continue
                
                # 既に接続している場合はスキップ
                if guild.voice_client:
                    continue
                
                # カスタムVoiceClientで接続
                await self.bot.connect_to_voice(channel)
                self.logger.info(f"Restored session: {channel.name} in {guild.name}")
                
                # セッション復元後に他のCogに通知
                await self.notify_bot_joined_channel(guild, channel)
                
            except Exception as e:
                self.logger.error(f"Failed to restore session for guild {guild_id}: {e}")
        
        # セッション復元後は一度保存
        self.save_sessions()
    
    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """ボイスステート変更時の自動参加・退出処理"""
        if member.bot:  # ボット自身の変更は無視
            return
        
        guild = member.guild
        
        # ユーザーがチャンネルに参加した場合
        if before.channel is None and after.channel is not None:
            await self.handle_user_join(guild, after.channel)
        
        # ユーザーがチャンネルから退出した場合
        if before.channel is not None and after.channel is None:
            await self.handle_user_leave(guild, before.channel)
        
        # ユーザーがチャンネル間を移動した場合
        if before.channel is not None and after.channel is not None and before.channel != after.channel:
            await self.handle_user_move(guild, before.channel, after.channel)
    
    async def handle_user_join(self, guild: discord.Guild, channel: discord.VoiceChannel):
        """ユーザー参加時の処理"""
        if not self.config["bot"]["auto_join"]:
            return
        
        # 既に接続している場合
        if guild.voice_client:
            # 同じチャンネルの場合は何もしない
            if guild.voice_client.channel == channel:
                return
            # 別のチャンネルに移動
            try:
                await guild.voice_client.move_to(channel)
                self.logger.info(f"Moved to voice channel: {channel.name} in {guild.name}")
                self.save_sessions()
                # 移動後に他のCogに通知
                await self.notify_bot_joined_channel(guild, channel)
            except Exception as e:
                self.logger.error(f"Failed to move to voice channel: {e}")
        else:
            # 新規接続
            try:
                await self.bot.connect_to_voice(channel)
                self.logger.info(f"Auto-joined voice channel: {channel.name} in {guild.name}")
                self.save_sessions()
                # 接続後に他のCogに通知
                await self.notify_bot_joined_channel(guild, channel)
            except Exception as e:
                self.logger.error(f"Failed to auto-join voice channel: {e}")
    
    async def notify_bot_joined_channel(self, guild: discord.Guild, channel: discord.VoiceChannel):
        """ボットがチャンネルに接続した際の他Cogへの通知"""
        try:
            # 少し待ってから処理（接続の安定化）
            await asyncio.sleep(1)
            
            # チャンネルにいる全メンバーを取得（ボット以外）
            members = [m for m in channel.members if not m.bot]
            self.logger.info(f"Bot joined channel with {len(members)} members: {[m.display_name for m in members]}")
            
            # 各メンバーに対してTTSと録音の処理を開始
            for member in members:
                # TTSCogに挨拶を依頼
                tts_cog = self.bot.get_cog("TTSCog")
                if tts_cog:
                    await tts_cog.handle_bot_joined_with_user(guild, member)
                
                # RecordingCogに録音開始を依頼
                recording_cog = self.bot.get_cog("RecordingCog")
                if recording_cog:
                    await recording_cog.handle_bot_joined_with_user(guild, member)
                    
        except Exception as e:
            self.logger.error(f"Failed to notify other cogs: {e}")
    
    async def handle_user_leave(self, guild: discord.Guild, channel: discord.VoiceChannel):
        """ユーザー退出時の処理"""
        if not self.config["bot"]["auto_leave"]:
            return
        
        # ボットが接続していない場合は何もしない
        if not guild.voice_client or guild.voice_client.channel != channel:
            return
        
        # チャンネルが空かチェック
        if len(channel.members) <= 1:  # ボット自身のみ
            try:
                await guild.voice_client.disconnect()
                self.logger.info(f"Auto-left empty voice channel: {channel.name} in {guild.name}")
                self.save_sessions()
            except Exception as e:
                self.logger.error(f"Failed to auto-leave voice channel: {e}")
    
    async def handle_user_move(self, guild: discord.Guild, old_channel: discord.VoiceChannel, new_channel: discord.VoiceChannel):
        """ユーザー移動時の処理"""
        # 退出処理
        await self.handle_user_leave(guild, old_channel)
        # 参加処理
        await self.handle_user_join(guild, new_channel)
    
    @tasks.loop(minutes=5)
    async def empty_channel_check(self):
        """5分ごとの空チャンネルチェック"""
        try:
            for guild in self.bot.guilds:
                if not guild.voice_client:
                    continue
                
                channel = guild.voice_client.channel
                if len(channel.members) <= 1:  # ボット自身のみ
                    await guild.voice_client.disconnect()
                    self.logger.info(f"Left empty channel during periodic check: {channel.name} in {guild.name}")
                    self.save_sessions()
                    
        except Exception as e:
            self.logger.error(f"Error in empty channel check: {e}")
    
    @empty_channel_check.before_loop
    async def before_empty_channel_check(self):
        """定期チェック開始前の待機"""
        await self.bot.wait_until_ready()
    
    @discord.slash_command(name="join", description="ボイスチャンネルに参加します")
    async def join_command(self, ctx: discord.ApplicationContext):
        """VCに参加するコマンド"""
        self.logger.info(f"/join command called by {ctx.author} in {ctx.guild.name}")
        await self.rate_limit_delay()
        
        # ユーザーがVCに接続しているか確認
        if not ctx.author.voice:
            await ctx.respond(
                "❌ ボイスチャンネルに接続してから実行してください。",
                ephemeral=True
            )
            self.logger.warning(f"Join failed: {ctx.author} is not in a voice channel")
            return
        
        channel = ctx.author.voice.channel
        self.logger.info(f"User {ctx.author} is in channel: {channel.name}")
        
        # 既に接続している場合
        if ctx.guild.voice_client:
            if ctx.guild.voice_client.channel == channel:
                await ctx.respond(
                    f"✅ 既に {channel.name} に接続しています。",
                    ephemeral=True
                )
                return
            else:
                # 別のチャンネルに移動
                try:
                    await ctx.guild.voice_client.move_to(channel)
                    await ctx.respond(
                        f"🔄 {channel.name} に移動しました。",
                        ephemeral=True
                    )
                    self.logger.info(f"Moved to voice channel: {channel.name} in {ctx.guild.name}")
                    self.save_sessions()
                    
                    # 移動後に他のCogに通知
                    await self.notify_bot_joined_channel(ctx.guild, channel)
                    return
                except Exception as e:
                    self.logger.error(f"Failed to move to voice channel: {e}")
                    await ctx.respond(
                        "❌ チャンネルの移動に失敗しました。",
                        ephemeral=True
                    )
                    return
        
        # 新規接続
        try:
            self.logger.info(f"Attempting to connect to voice channel: {channel.name}")
            await self.bot.connect_to_voice(channel)
            self.logger.info(f"Successfully connected to voice channel: {channel.name}")
            
            await ctx.respond(
                f"✅ {channel.name} に接続しました！",
                ephemeral=True
            )
            self.logger.info(f"Connected to voice channel: {channel.name} in {ctx.guild.name}")
            self.save_sessions()
            
            # 接続後に他のCogに通知
            await self.notify_bot_joined_channel(ctx.guild, channel)
        except asyncio.TimeoutError:
            await ctx.respond(
                "❌ 接続がタイムアウトしました。",
                ephemeral=True
            )
            self.logger.error("Voice connection timeout")
        except Exception as e:
            await ctx.respond(
                "❌ 接続に失敗しました。",
                ephemeral=True
            )
            self.logger.error(f"Failed to connect to voice channel: {e}", exc_info=True)
    
    @discord.slash_command(name="leave", description="ボイスチャンネルから退出します")
    async def leave_command(self, ctx: discord.ApplicationContext):
        """VCから退出するコマンド"""
        await self.rate_limit_delay()
        
        # ボットが接続しているか確認
        if not ctx.guild.voice_client:
            await ctx.respond(
                "❌ ボイスチャンネルに接続していません。",
                ephemeral=True
            )
            return
        
        try:
            channel_name = ctx.guild.voice_client.channel.name
            await ctx.guild.voice_client.disconnect()
            await ctx.respond(
                f"👋 {channel_name} から退出しました。",
                ephemeral=True
            )
            self.logger.info(f"Disconnected from voice channel: {channel_name} in {ctx.guild.name}")
            self.save_sessions()
        except Exception as e:
            await ctx.respond(
                "❌ 退出に失敗しました。",
                ephemeral=True
            )
            self.logger.error(f"Failed to disconnect from voice channel: {e}")


async def setup(bot: commands.Bot, config: Dict[str, Any]):
    """Cogのセットアップ"""
    await bot.add_cog(VoiceCog(bot, config))