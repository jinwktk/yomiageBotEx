"""
ボイスチャンネル管理Cog
"""

import asyncio
import random
import logging
from typing import Dict, Any
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
        
        # 起動時自動参加チェックのタスクを開始
        if not self.startup_auto_join_check.is_running():
            self.startup_auto_join_check.start()
    
    def cog_unload(self):
        """Cogアンロード時のクリーンアップ"""
        self.empty_channel_check.cancel()
        self.startup_auto_join_check.cancel()
    
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
                
                # セッション復元後に他のCogに通知（起動時フラグを設定）
                await self.notify_bot_joined_channel(guild, channel, is_startup=True)
                
            except Exception as e:
                self.logger.error(f"Failed to restore session for guild {guild_id}: {e}")
        
        # セッション復元後は一度保存
        self.save_sessions()
    
    
    @tasks.loop(count=1)  # 1回だけ実行
    async def startup_auto_join_check(self):
        """起動時自動参加チェック（1回限り実行）"""
        # Bot起動直後に実行されるので、少し待つ
        await asyncio.sleep(15)
        
        self.logger.info("Starting startup auto-join check...")
        await self.check_startup_auto_join()
    
    @startup_auto_join_check.before_loop
    async def before_startup_auto_join_check(self):
        """startup_auto_join_check開始前の処理"""
        await self.bot.wait_until_ready()
        self.logger.info("Bot is ready, preparing startup auto-join check")
        
        # Guild情報が完全に同期されるまで短縮待機
        await asyncio.sleep(2)
        self.logger.info("Guild sync wait completed")
    
    async def check_startup_auto_join(self):
        """起動時の自動VC参加処理"""
        self.logger.info("VoiceCog.check_startup_auto_join() called")
        
        auto_join_enabled = self.config.get("bot", {}).get("auto_join", True)
        self.logger.info(f"Auto-join setting: {auto_join_enabled}")
        
        if not auto_join_enabled:
            self.logger.info("Auto-join disabled in config, skipping startup check")
            return
        
        self.logger.info("Starting voice channel check on startup...")
        
        guild_count = len(self.bot.guilds)
        self.logger.info(f"Found {guild_count} guilds to check")
        
        # 並列処理でギルドを同時チェック
        tasks = []
        for guild in self.bot.guilds:
            task = asyncio.create_task(self._check_guild_for_auto_join(guild))
            tasks.append(task)
        
        # 全ギルドを並列で処理
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
            self.logger.info("Startup voice channel check completed")
    
    async def _check_guild_for_auto_join(self, guild):
        """個別ギルドの自動参加チェック"""
        self.logger.info(f"Checking guild: {guild.name} (ID: {guild.id})")
        
        try:
            # 既に接続している場合でも録音機能の確認と開始を行う
            if guild.voice_client:
                self.logger.info(f"Already connected to voice in {guild.name}")
                # 接続中のチャンネルでメンバーがいる場合は録音機能を確保する
                current_channel = guild.voice_client.channel
                if current_channel:
                    # 既存メンバーがいるかチェック
                    non_bot_members = [m for m in current_channel.members if not m.bot]
                    if non_bot_members:
                        self.logger.info(f"Found {len(non_bot_members)} members in connected channel {current_channel.name}, ensuring recording is active")
                        # 録音機能が開始されていることを確認
                        await self.notify_bot_joined_channel(guild, current_channel, is_startup=True, ensure_recording=True)
                        self.save_sessions()
                return
            
            # ボイスチャンネル数をログ
            vc_count = len(guild.voice_channels)
            self.logger.info(f"Guild {guild.name} has {vc_count} voice channels")
            
            # 各ボイスチャンネルをチェック
            for channel in guild.voice_channels:
                # 複数の方法でメンバー情報を取得
                all_members = []
                non_bot_members = []
                    
                # 方法1: 標準のchannel.members
                standard_members = channel.members
                self.logger.debug(f"Standard method - Channel {channel.name}: {len(standard_members)} members")
                
                # 方法2: ギルドのvoice_statesから取得
                voice_state_members = []
                for member in guild.members:
                    if member.voice and member.voice.channel and member.voice.channel.id == channel.id:
                        voice_state_members.append(member)
                self.logger.debug(f"Voice states method - Channel {channel.name}: {len(voice_state_members)} members")
                
                # より多くのメンバーが検出された方を使用
                if len(voice_state_members) > len(standard_members):
                    all_members = voice_state_members
                    self.logger.info(f"Using voice_states method for {channel.name}")
                else:
                    all_members = standard_members
                    self.logger.info(f"Using standard method for {channel.name}")
                
                # ボット以外のメンバーをフィルタ
                non_bot_members = [m for m in all_members if not m.bot]
                    
                self.logger.info(f"Channel {channel.name}: {len(all_members)} total members, {len(non_bot_members)} non-bot members")
                
                # メンバーの詳細情報をログ出力
                if len(all_members) > 0:
                    member_info = []
                    for member in all_members:
                        member_info.append(f"{member.display_name}({'bot' if member.bot else 'user'})")
                    self.logger.info(f"Channel {channel.name} members: {', '.join(member_info)}")
                
                if len(non_bot_members) > 0:
                    # 既に接続中かチェック
                    if guild.voice_client:
                        self.logger.info(f"Already connected to {guild.voice_client.channel.name} in {guild.name}, skipping join")
                        # 既存接続を優先し、自動移動は行わない
                        if guild.voice_client.channel != channel:
                            self.logger.info(
                                "Keeping current channel %s in %s; skip auto-move to %s",
                                guild.voice_client.channel.name,
                                guild.name,
                                channel.name,
                            )
                        continue
                    
                    try:
                        self.logger.info(f"Attempting to join {channel.name}...")
                        
                        # 既存の接続をチェック
                        if guild.voice_client and guild.voice_client.is_connected():
                            self.logger.info(f"Already connected to {guild.voice_client.channel.name}, disconnecting first")
                            try:
                                await guild.voice_client.disconnect()
                                await asyncio.sleep(2.0)  # 切断完了を待機
                            except Exception as disconnect_error:
                                self.logger.warning(f"Failed to disconnect existing connection: {disconnect_error}")
                        
                        # カスタムVoiceClientで接続
                        await self.bot.connect_to_voice(channel)
                        connected_client = guild.voice_client
                        if (
                            not connected_client
                            or not connected_client.is_connected()
                            or connected_client.channel != channel
                        ):
                            self.logger.warning(
                                "Auto-join verification failed for %s in %s (connected=%s, channel=%s)",
                                channel.name,
                                guild.name,
                                bool(connected_client and connected_client.is_connected()),
                                getattr(getattr(connected_client, "channel", None), "name", None),
                            )
                            continue
                        self.logger.info(f"Successfully auto-joined on startup: {channel.name} in {guild.name}")
                        
                        # 他のCogに参加を通知（起動時フラグを設定）
                        self.logger.info(f"Notifying other Cogs about startup join to {channel.name}")
                        await self.notify_bot_joined_channel(guild, channel, is_startup=True)
                        
                        # セッションを保存
                        self.save_sessions()
                        
                        # 1つのギルドで1つのチャンネルのみ
                        return  # break → returnに変更
                        
                    except Exception as e:
                        self.logger.error(f"Failed to auto-join {channel.name} on startup: {e}", exc_info=True)
                        continue
                else:
                    self.logger.debug(f"Channel {channel.name} is empty, skipping")
                        
        except Exception as e:
            self.logger.error(f"Failed to check guild {guild.name} on startup: {e}", exc_info=True)
    
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
        
        voice_client = guild.voice_client
        is_connected = bool(voice_client and voice_client.is_connected())

        # 既に接続している場合
        if is_connected:
            # 同じチャンネルの場合、録音が開始されているか確認
            if voice_client.channel == channel:
                # 新しいユーザーが参加した時の録音開始処理
                self.logger.info(f"User joined same channel as bot: {channel.name}")
                
                # RecordingCogに録音開始を通知（ユーザー参加時）
                recording_cog = self.bot.get_cog("RecordingCog")
                if recording_cog:
                    try:
                        # 録音が既に開始されているかチェック
                        if not getattr(voice_client, 'recording', False):
                            self.logger.info(f"Starting recording for user join: {channel.name}")
                            await recording_cog.real_time_recorder.start_recording(guild.id, voice_client)
                            recording_cog.real_time_recorder.debug_recording_status(guild.id)
                        else:
                            self.logger.info(f"Recording already active in {channel.name}")
                    except Exception as e:
                        self.logger.error(f"Failed to start recording on user join: {e}")
                return
            
            # 既存接続を維持（ユーザー参加トリガーでの自動移動はしない）
            self.logger.info(
                "Already connected to %s in %s; skip auto-move to %s",
                voice_client.channel.name,
                guild.name,
                channel.name,
            )
            return
        else:
            if voice_client:
                self.logger.warning(f"Detected stale voice client in {guild.name}, attempting reconnect")
                try:
                    await voice_client.disconnect()
                except Exception as disconnect_error:
                    self.logger.debug(f"Failed to cleanup stale voice client: {disconnect_error}")
            
            # 新規接続
            current_client = guild.voice_client
            if current_client and current_client.is_connected():
                self.logger.info(f"Already connected to a voice channel in {guild.name}, notifying only")
                await self.notify_bot_joined_channel(guild, channel, ensure_recording=True)
                return
            
            try:
                await self.bot.connect_to_voice(channel)
                connected_client = guild.voice_client
                if (
                    not connected_client
                    or not connected_client.is_connected()
                    or connected_client.channel != channel
                ):
                    self.logger.warning(
                        "Auto-join verification failed for %s in %s (connected=%s, channel=%s)",
                        channel.name,
                        guild.name,
                        bool(connected_client and connected_client.is_connected()),
                        getattr(getattr(connected_client, "channel", None), "name", None),
                    )
                    return
                self.logger.info(f"Auto-joined voice channel: {channel.name} in {guild.name}")
                self.save_sessions()
                # 接続後に他のCogに通知
                await self.notify_bot_joined_channel(guild, channel)
            except Exception as e:
                self.logger.error(f"Failed to auto-join voice channel: {e}")
    
    async def notify_bot_joined_channel(self, guild: discord.Guild, channel: discord.VoiceChannel, is_startup: bool = False, ensure_recording: bool = False):
        """ボットがチャンネルに接続した際の他Cogへの通知"""
        try:
            # 既に接続済みで録音確保のみの場合は安定化チェックをスキップ
            if ensure_recording and guild.voice_client and guild.voice_client.is_connected():
                self.logger.info(f"Ensuring recording is active for existing connection in {channel.name}")
            else:
                # 音声接続が完全に確立されるまで待機
                self.logger.info("Waiting for voice connection to stabilize...")
                
                stable_connection = False
                for attempt in range(10):  # 最大10回試行（3秒間）に短縮
                    await asyncio.sleep(0.3)
                    
                    voice_client = guild.voice_client
                    if voice_client and voice_client.is_connected():
                        # 追加の安定性チェック：WebSocketの状態も確認
                        try:
                            # ボイスクライアントの内部状態をチェック
                            if hasattr(voice_client, '_connected') and voice_client._connected:
                                self.logger.info(f"Voice connection confirmed after {(attempt + 1) * 0.3}s")
                                stable_connection = True
                                break
                            elif hasattr(voice_client, 'is_connected') and voice_client.is_connected():
                                self.logger.info(f"Voice connection stable after {(attempt + 1) * 0.3}s")
                                stable_connection = True
                                break
                        except Exception as e:
                            self.logger.debug(f"Connection stability check failed: {e}")
                            continue
                    
                    if attempt >= 9:
                        self.logger.warning("Voice connection not stable after 3s, aborting")
                        return
                
                if not stable_connection:
                    self.logger.warning("Voice connection stability could not be verified")
                    return
                
                # 追加の安定化待機
                await asyncio.sleep(1.5)
            
            # 最終確認：接続がまだ有効か
            voice_client = guild.voice_client
            if not voice_client or not voice_client.is_connected():
                self.logger.warning("Voice client disconnected during stabilization wait")
                return
            
            # チャンネルにいる全メンバーを取得（ボット以外）
            members = [m for m in channel.members if not m.bot]
            self.logger.info(f"Bot joined channel with {len(members)} members: {[m.display_name for m in members]}")
            
            # 録音確保モードの場合は録音処理のみ実行
            if ensure_recording:
                if members:
                    self.logger.info("Ensuring recording is active for connected members")
                    first_member = members[0]
                    await self._process_member_recording(guild, first_member)
                return
            
            # TTS処理は並列実行、録音処理は最初の1回のみ実行
            if members:
                # TTS挨拶処理は並列実行
                tts_tasks = []
                for member in members:
                    task = asyncio.create_task(self._process_member_tts(guild, member, is_startup))
                    tts_tasks.append(task)
                
                # TTS処理を並列実行
                await asyncio.gather(*tts_tasks, return_exceptions=True)
                
                # 録音処理は最初のメンバーでのみ実行（重複を防ぐ）
                first_member = members[0]
                await self._process_member_recording(guild, first_member)
            
            # 音声接続完了
                    
        except Exception as e:
            self.logger.error(f"Failed to notify other cogs: {e}")
    
    async def _process_member_tts(self, guild: discord.Guild, member: discord.Member, is_startup: bool = False):
        """個別メンバーのTTS処理"""
        try:
            # 接続確認
            current_voice_client = guild.voice_client
            if not current_voice_client or not current_voice_client.is_connected():
                self.logger.warning(f"Voice client disconnected before TTS processing for {member.display_name}")
                return
            
            # TTSCogに挨拶を依頼（起動時情報を渡す）
            tts_cog = self.bot.get_cog("TTSCog")
            if tts_cog:
                await tts_cog.handle_bot_joined_with_user(guild, member, is_startup=is_startup)
            
                
        except Exception as e:
            self.logger.error(f"Failed to process member TTS for {member.display_name}: {e}")
    
    async def _process_member_recording(self, guild: discord.Guild, member: discord.Member):
        """個別メンバーの録音処理（最初の1名のみ）"""
        try:
            # 接続確認
            current_voice_client = guild.voice_client
            if not current_voice_client or not current_voice_client.is_connected():
                self.logger.warning(f"Voice client disconnected before recording processing for {member.display_name}")
                return
            
            # 短い間隔を置いてから録音処理
            await asyncio.sleep(0.5)
            
            # RecordingCogに録音開始を依頼（代表のメンバーで1回のみ）
            recording_cog = self.bot.get_cog("RecordingCog")
            if recording_cog:
                await recording_cog.handle_bot_joined_with_user(guild, member)
                
        except Exception as e:
            self.logger.error(f"Failed to process member recording for {member.display_name}: {e}")
    
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
        
        # 重複応答を防ぐためのチェック
        if ctx.response.is_done():
            self.logger.warning(f"Interaction already acknowledged for /join by {ctx.author}")
            return
        
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
            if ctx.guild.voice_client.is_connected() and ctx.guild.voice_client.channel == channel:
                await ctx.respond(
                    f"✅ 既に {channel.name} に接続しています。",
                    ephemeral=True
                )
                return
            else:
                # 別のチャンネルに移動または再接続
                try:
                    if ctx.guild.voice_client.is_connected():
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
                    else:
                        # 接続状態が不整合の場合はクリーンアップ
                        self.logger.warning("Voice client exists but not connected, cleaning up")
                        await ctx.guild.voice_client.disconnect()
                        await asyncio.sleep(1.0)
                except Exception as e:
                    self.logger.error(f"Failed to move to voice channel: {e}")
                    try:
                        if not ctx.response.is_done():
                            await ctx.respond(
                                "❌ チャンネルの移動に失敗しました。再接続を試行します。",
                                ephemeral=True
                            )
                        # 移動に失敗した場合は切断して再接続を試行
                        await ctx.guild.voice_client.disconnect()
                        await asyncio.sleep(1.0)
                    except Exception as cleanup_error:
                        self.logger.error(f"Failed to cleanup after move error: {cleanup_error}")
        
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


def setup(bot):
    """Cogのセットアップ"""
    bot.add_cog(VoiceCog(bot, bot.config))
