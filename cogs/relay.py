"""
音声横流し（リレー）機能Cog
"""

import asyncio
import logging
from typing import Dict, Any

import discord
from discord.ext import commands

from utils.audio_relay import AudioRelay, RelayStatus


class RelayCog(commands.Cog):
    """音声横流し（リレー）機能"""
    
    def __init__(self, bot: commands.Bot, config: Dict[str, Any]):
        self.bot = bot
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # AudioRelayマネージャーの初期化
        self.audio_relay = AudioRelay(bot, config)
        
        # 管理者ユーザーID
        self.admin_user_id = config.get("bot", {}).get("admin_user_id")
        
        # 自動開始設定
        self.auto_start_config = config.get("audio_relay", {}).get("auto_start", False)
        self.auto_relay_pairs = config.get("audio_relay", {}).get("auto_relay_pairs", [])
        
        self.logger.info("RelayCog initialized")
        
        # 自動開始タスク
        if self.auto_start_config and self.audio_relay.enabled:
            self._start_auto_relay_task()
    
    def _start_auto_relay_task(self):
        """自動リレー開始タスクの開始（on_readyで実行）"""
        # on_readyで実行するためここでは何もしない
        pass
    
    async def _auto_start_relay_sessions(self):
        """自動リレーセッションの開始"""
        # Botの準備完了まで待機
        await self.bot.wait_until_ready()
        
        # ギルド情報の同期待機
        await asyncio.sleep(5)
        
        self.logger.info("Starting auto relay sessions...")
        
        if not self.auto_relay_pairs:
            self.logger.info("No auto relay pairs configured")
            return
        
        started_count = 0
        for pair in self.auto_relay_pairs:
            try:
                # ペアが有効かチェック
                if not pair.get("enabled", False):
                    self.logger.debug(f"Skipping disabled relay pair: {pair}")
                    continue
                
                source_guild_id = pair.get("source_guild_id", 0)
                configured_source_channel_id = pair.get("source_channel_id", 0)
                target_guild_id = pair.get("target_guild_id", 0)
                target_channel_id = pair.get("target_channel_id", 0)
                
                # ソースギルドでボットが現在接続しているチャンネルを動的取得
                source_guild = self.bot.get_guild(source_guild_id)
                if source_guild and source_guild.voice_client:
                    source_channel_id = source_guild.voice_client.channel.id
                    self.logger.info(f"Using bot's current voice channel as source: {source_channel_id}")
                else:
                    # ボットが接続していない場合は設定値を使用
                    source_channel_id = configured_source_channel_id
                    self.logger.warning(f"Bot not connected in source guild {source_guild_id}, using configured channel: {source_channel_id}")
                
                # IDの妥当性チェック
                if not all([source_guild_id, source_channel_id, target_guild_id, target_channel_id]):
                    self.logger.warning(f"Invalid relay pair configuration: {pair}")
                    continue
                
                # ギルドとチャンネルの存在確認
                source_guild = self.bot.get_guild(source_guild_id)
                target_guild = self.bot.get_guild(target_guild_id)
                
                if not source_guild:
                    self.logger.warning(f"Source guild {source_guild_id} not found")
                    continue
                    
                if not target_guild:
                    self.logger.warning(f"Target guild {target_guild_id} not found")
                    continue
                
                source_channel = source_guild.get_channel(source_channel_id)
                target_channel = target_guild.get_channel(target_channel_id)
                
                if not source_channel or not isinstance(source_channel, discord.VoiceChannel):
                    self.logger.warning(f"Source channel {source_channel_id} not found or not a voice channel")
                    continue
                    
                if not target_channel or not isinstance(target_channel, discord.VoiceChannel):
                    self.logger.warning(f"Target channel {target_channel_id} not found or not a voice channel")
                    continue
                
                # 既存の音声接続チェック（人がいる場合のみ移動を避ける）
                source_existing_connection = source_guild.voice_client
                target_existing_connection = target_guild.voice_client
                
                if source_existing_connection and source_existing_connection.channel != source_channel:
                    current_channel = source_existing_connection.channel
                    non_bot_members = [m for m in current_channel.members if not m.bot]
                    
                    if len(non_bot_members) == 0:
                        self.logger.info(
                            f"Bot in empty channel {current_channel.name} in source guild, "
                            f"will move to {source_channel.name} for relay"
                        )
                    else:
                        self.logger.info(
                            f"Bot staying in {current_channel.name} with {len(non_bot_members)} users in source guild, "
                            f"will relay from current location instead of {source_channel.name}"
                        )
                
                if target_existing_connection and target_existing_connection.channel != target_channel:
                    current_channel = target_existing_connection.channel
                    non_bot_members = [m for m in current_channel.members if not m.bot]
                    
                    if len(non_bot_members) == 0:
                        self.logger.info(
                            f"Bot in empty channel {current_channel.name} in target guild, "
                            f"will move to {target_channel.name} for relay"
                        )
                    else:
                        self.logger.info(
                            f"Bot staying in {current_channel.name} with {len(non_bot_members)} users in target guild, "
                            f"will relay to current location instead of {target_channel.name}"
                        )
                
                # リレーセッション開始
                session_id = await self.audio_relay.start_relay_session(
                    source_guild_id=source_guild_id,
                    source_channel_id=source_channel_id,
                    target_guild_id=target_guild_id,
                    target_channel_id=target_channel_id
                )
                
                self.logger.info(
                    f"Auto-started relay session: {session_id} "
                    f"({source_channel.name} -> {target_channel.name})"
                )
                started_count += 1
                
                # セッション間の待機（負荷軽減）
                await asyncio.sleep(2)
                
            except Exception as e:
                self.logger.error(f"Failed to auto-start relay session for pair {pair}: {e}")
        
        self.logger.info(f"Auto relay sessions started: {started_count} sessions")
    
    def cog_unload(self):
        """Cogアンロード時のクリーンアップ"""
        # すべてのリレーセッションを停止
        asyncio.create_task(self.audio_relay.stop_all_sessions())
    
    def _is_admin(self, user_id: int) -> bool:
        """管理者権限チェック"""
        return self.admin_user_id and user_id == self.admin_user_id
    
    @commands.Cog.listener()
    async def on_ready(self):
        """ボット準備完了時にクリーンアップタスクと自動リレーを開始"""
        self.audio_relay._start_cleanup_task()
        if self.config.get("audio_relay", {}).get("auto_start", False):
            asyncio.create_task(self._auto_start_relay_sessions())
    
    # @discord.slash_command(name="relay_start", description="音声横流し（リレー）を開始します")
    async def relay_start_command(
        self,
        ctx: discord.ApplicationContext,
        source_channel: discord.Option(
            discord.VoiceChannel,
            name="source_channel",
            description="音声の取得元チャンネル",
            required=True
        ),
        target_guild_id: discord.Option(
            str,
            name="target_guild_id", 
            description="転送先サーバーのID",
            required=True
        ),
        target_channel_id: discord.Option(
            str,
            name="target_channel_id",
            description="転送先チャンネルのID", 
            required=True
        )
    ):
        """音声リレー開始コマンド"""
        # 管理者権限チェック
        if not self._is_admin(ctx.author.id):
            await ctx.respond("❌ このコマンドは管理者限定です。", ephemeral=True)
            return
        
        # 音声リレー機能が有効かチェック
        if not self.audio_relay.enabled:
            await ctx.respond("❌ 音声リレー機能が無効になっています。", ephemeral=True)
            return
        
        self.logger.info(f"Relay start command called by {ctx.author} in {ctx.guild.name}")
        
        try:
            # パラメータの変換
            target_guild_id = int(target_guild_id)
            target_channel_id = int(target_channel_id)
            
            # 即座に応答
            await ctx.respond("🔄 音声リレーを開始しています...", ephemeral=True)
            
            # バックグラウンドでリレーセッション開始
            asyncio.create_task(
                self._start_relay_background(ctx, source_channel, target_guild_id, target_channel_id)
            )
            
        except ValueError:
            await ctx.respond("❌ ギルドIDまたはチャンネルIDが無効です。", ephemeral=True)
        except Exception as e:
            self.logger.error(f"Error in relay start command: {e}")
            await ctx.respond("❌ リレー開始に失敗しました。", ephemeral=True)
    
    async def _start_relay_background(
        self,
        ctx: discord.ApplicationContext,
        source_channel: discord.VoiceChannel,
        target_guild_id: int,
        target_channel_id: int
    ):
        """バックグラウンドでのリレーセッション開始処理"""
        try:
            # ターゲットギルドとチャンネルの存在確認
            target_guild = self.bot.get_guild(target_guild_id)
            if not target_guild:
                await ctx.followup.send("❌ 転送先サーバーが見つかりません。", ephemeral=True)
                return
            
            target_channel = target_guild.get_channel(target_channel_id)
            if not target_channel or not isinstance(target_channel, discord.VoiceChannel):
                await ctx.followup.send("❌ 転送先チャンネルが見つからないか、音声チャンネルではありません。", ephemeral=True)
                return
            
            # リレーセッション開始
            session_id = await self.audio_relay.start_relay_session(
                source_guild_id=source_channel.guild.id,
                source_channel_id=source_channel.id,
                target_guild_id=target_guild_id,
                target_channel_id=target_channel_id
            )
            
            # 成功通知
            await ctx.followup.send(
                f"✅ 音声リレーを開始しました！\n"
                f"**転送元**: {source_channel.name} ({source_channel.guild.name})\n"
                f"**転送先**: {target_channel.name} ({target_guild.name})\n"
                f"**セッションID**: `{session_id}`",
                ephemeral=True
            )
            
            self.logger.info(f"Relay session started: {session_id}")
            
        except Exception as e:
            self.logger.error(f"Failed to start relay session: {e}")
            await ctx.followup.send(f"❌ リレー開始に失敗しました: {str(e)}", ephemeral=True)
    
    # @discord.slash_command(name="relay_stop", description="音声横流し（リレー）を停止します")
    async def relay_stop_command(
        self,
        ctx: discord.ApplicationContext,
        session_id: discord.Option(
            str,
            name="session_id",
            description="停止するセッションのID（省略時は全停止）",
            required=False
        )
    ):
        """音声リレー停止コマンド"""
        # 管理者権限チェック
        if not self._is_admin(ctx.author.id):
            await ctx.respond("❌ このコマンドは管理者限定です。", ephemeral=True)
            return
        
        self.logger.info(f"Relay stop command called by {ctx.author}")
        
        try:
            if session_id:
                # 特定セッションを停止
                success = await self.audio_relay.stop_relay_session(session_id)
                if success:
                    await ctx.respond(f"✅ セッション `{session_id}` を停止しました。", ephemeral=True)
                else:
                    await ctx.respond(f"❌ セッション `{session_id}` の停止に失敗しました。", ephemeral=True)
            else:
                # 全セッションを停止
                await ctx.respond("🔄 すべてのリレーセッションを停止しています...", ephemeral=True)
                await self.audio_relay.stop_all_sessions()
                await ctx.followup.send("✅ すべてのリレーセッションを停止しました。", ephemeral=True)
                
        except Exception as e:
            self.logger.error(f"Error in relay stop command: {e}")
            await ctx.respond("❌ リレー停止に失敗しました。", ephemeral=True)
    
    # @discord.slash_command(name="relay_status", description="音声横流し（リレー）の状態を表示します")
    async def relay_status_command(self, ctx: discord.ApplicationContext):
        """音声リレー状態表示コマンド"""
        # 管理者権限チェック
        if not self._is_admin(ctx.author.id):
            await ctx.respond("❌ このコマンドは管理者限定です。", ephemeral=True)
            return
        
        try:
            # アクティブセッション取得
            active_sessions = self.audio_relay.get_active_sessions()
            
            if not active_sessions:
                await ctx.respond("📊 現在アクティブなリレーセッションはありません。", ephemeral=True)
                return
            
            # ステータス表示の構築
            embed = discord.Embed(
                title="🔄 音声リレー状態",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )
            
            for session_id, session_info in active_sessions.items():
                # ギルドとチャンネル名を取得
                source_guild = self.bot.get_guild(session_info["source_guild_id"])
                target_guild = self.bot.get_guild(session_info["target_guild_id"])
                
                source_channel = None
                target_channel = None
                
                if source_guild:
                    source_channel = source_guild.get_channel(session_info["source_channel_id"])
                if target_guild:
                    target_channel = target_guild.get_channel(session_info["target_channel_id"])
                
                # セッション情報の表示
                source_name = f"{source_channel.name} ({source_guild.name})" if source_channel and source_guild else "不明"
                target_name = f"{target_channel.name} ({target_guild.name})" if target_channel and target_guild else "不明"
                
                duration_minutes = int(session_info["duration"] // 60)
                duration_seconds = int(session_info["duration"] % 60)
                
                field_value = (
                    f"**転送元**: {source_name}\n"
                    f"**転送先**: {target_name}\n"
                    f"**状態**: {session_info['status']}\n"
                    f"**継続時間**: {duration_minutes:02d}:{duration_seconds:02d}\n"
                    f"**アクティブユーザー**: {len(session_info['active_users'])}人"
                )
                
                embed.add_field(
                    name=f"セッション: {session_id[:16]}...",
                    value=field_value,
                    inline=False
                )
            
            embed.set_footer(text="音声リレーシステム")
            await ctx.respond(embed=embed, ephemeral=True)
            
        except Exception as e:
            self.logger.error(f"Error in relay status command: {e}")
            await ctx.respond("❌ ステータス取得に失敗しました。", ephemeral=True)
    
    # @discord.slash_command(name="relay_test", description="音声リレー機能をテストします")
    async def relay_test_command(self, ctx: discord.ApplicationContext):
        """音声リレーテストコマンド"""
        # 管理者権限チェック
        if not self._is_admin(ctx.author.id):
            await ctx.respond("❌ このコマンドは管理者限定です。", ephemeral=True)
            return
        
        try:
            # 音声リレー機能の状態確認
            embed = discord.Embed(
                title="🔧 音声リレー機能テスト",
                color=discord.Color.green() if self.audio_relay.enabled else discord.Color.red(),
                timestamp=discord.utils.utcnow()
            )
            
            # 基本情報
            embed.add_field(
                name="機能状態",
                value="✅ 有効" if self.audio_relay.enabled else "❌ 無効",
                inline=True
            )
            
            embed.add_field(
                name="アクティブセッション数",
                value=str(len(self.audio_relay.active_sessions)),
                inline=True
            )
            
            embed.add_field(
                name="最大セッション時間",
                value=f"{self.audio_relay.max_session_duration / 3600:.1f}時間",
                inline=True
            )
            
            # 設定情報
            config_info = []
            config_info.append(f"ボリューム: {self.audio_relay.relay_config.get('volume', 0.5)}")
            config_info.append(f"クールダウン: {self.audio_relay.stream_switch_cooldown}秒")
            config_info.append(f"バッファ間隔: {self.audio_relay.buffer_flush_interval}秒")
            
            embed.add_field(
                name="設定情報",
                value="\n".join(config_info),
                inline=False
            )
            
            # ボットの音声接続状況
            voice_connections = []
            for guild in self.bot.guilds:
                if guild.voice_client:
                    channel = guild.voice_client.channel
                    voice_connections.append(f"• {channel.name} ({guild.name})")
            
            if voice_connections:
                embed.add_field(
                    name="現在の音声接続",
                    value="\n".join(voice_connections[:5]),  # 最大5つ表示
                    inline=False
                )
            else:
                embed.add_field(
                    name="現在の音声接続",
                    value="なし",
                    inline=False
                )
            
            embed.set_footer(text="音声リレーシステムテスト")
            await ctx.respond(embed=embed, ephemeral=True)
            
        except Exception as e:
            self.logger.error(f"Error in relay test command: {e}")
            await ctx.respond("❌ テスト実行に失敗しました。", ephemeral=True)


def setup(bot):
    """Cogのセットアップ"""
    bot.add_cog(RelayCog(bot, bot.config))