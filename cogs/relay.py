"""
音声横流し（リレー）機能Cog - シンプル実装版
"""

import asyncio
import logging
from typing import Dict, Any

import discord
from discord.ext import commands

from utils.smooth_audio_relay import SmoothAudioRelay, RelayStatus


class RelayCog(commands.Cog):
    """修正版音声横流し（リレー）機能"""
    
    def __init__(self, bot: commands.Bot, config: Dict[str, Any]):
        self.bot = bot
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # 修正版AudioRelayマネージャーの初期化
        from utils.smooth_audio_relay import SmoothAudioRelay
        self.audio_relay = SmoothAudioRelay(bot, config, self.logger)
        
        # 管理者ユーザーID
        self.admin_user_id = config.get("bot", {}).get("admin_user_id")
        
        # 自動開始設定
        self.auto_start_enabled = config.get("audio_relay", {}).get("auto_start", False)
        self.auto_relay_pairs = config.get("audio_relay", {}).get("auto_relay_pairs", [])
        
        # 自動開始フラグ
        self.auto_start_completed = False
        
        self.logger.info("RelayCog (Fixed) initialized")
        self.logger.info(f"Audio relay enabled: {self.audio_relay.enabled}")
        self.logger.info(f"Auto start enabled: {self.auto_start_enabled}")
    
    def _is_admin(self, user_id: int) -> bool:
        """管理者権限チェック"""
        return self.admin_user_id and user_id == self.admin_user_id
    
    @commands.Cog.listener()
    async def on_ready(self):
        """ボット準備完了時の処理"""
        self.logger.info("RelayCog on_ready triggered")
        
        # 自動開始が有効で、まだ実行されていない場合
        if self.auto_start_enabled and not self.auto_start_completed:
            self.logger.info("Scheduling auto-start relay sessions...")
            # ボット接続安定化のため5秒後に自動開始
            asyncio.create_task(self._delayed_auto_start())
    
    async def _delayed_auto_start(self):
        """遅延自動開始"""
        try:
            await asyncio.sleep(5.0)  # 接続安定化待機
            await self._auto_start_relay_sessions()
            self.auto_start_completed = True
        except Exception as e:
            self.logger.error(f"Error in delayed auto-start: {e}")
    
    async def _auto_start_relay_sessions(self):
        """自動リレーセッションの開始"""
        if not self.audio_relay.enabled:
            self.logger.info("Audio relay is disabled, skipping auto start")
            return
        
        self.logger.info("Starting auto relay sessions...")
        
        started_count = 0
        
        for pair in self.auto_relay_pairs:
            if not pair.get("enabled", False):
                continue
            
            try:
                source_guild_id = pair.get("source_guild_id")
                source_channel_id = pair.get("source_channel_id")
                target_guild_id = pair.get("target_guild_id")
                target_channel_id = pair.get("target_channel_id")
                
                if not all([source_guild_id, source_channel_id, target_guild_id, target_channel_id]):
                    self.logger.warning(f"Invalid relay pair configuration: {pair}")
                    continue
                
                # リレーセッション開始
                session_id = await self.audio_relay.start_relay_session(
                    source_guild_id=source_guild_id,
                    source_channel_id=source_channel_id,
                    target_guild_id=target_guild_id,
                    target_channel_id=target_channel_id
                )
                
                self.logger.info(f"🎤 AUTO-STARTED RELAY: Session {session_id}")
                started_count += 1
                
                # 連続開始の間隔
                await asyncio.sleep(2.0)
                
            except Exception as e:
                self.logger.error(f"Failed to auto-start relay session for pair {pair}: {e}")
        
        self.logger.info(f"Auto relay sessions started: {started_count} sessions")
    
    @discord.slash_command(name="relay_start", description="音声リレーセッションを開始")
    async def relay_start(
        self,
        ctx,
        source_guild: discord.Option(str, "転送元サーバーID", required=True),
        source_channel: discord.Option(str, "転送元チャンネルID", required=True),
        target_guild: discord.Option(str, "転送先サーバーID", required=True),
        target_channel: discord.Option(str, "転送先チャンネルID", required=True)
    ):
        """音声リレーセッションを手動開始"""
        if not self._is_admin(ctx.author.id):
            await ctx.respond("❌ このコマンドは管理者のみ使用できます。", ephemeral=True)
            return
        
        try:
            session_id = await self.audio_relay.start_relay_session(
                source_guild_id=int(source_guild),
                source_channel_id=int(source_channel),
                target_guild_id=int(target_guild),
                target_channel_id=int(target_channel)
            )
            
            await ctx.respond(f"🎤 音声リレーセッションを開始しました\nセッションID: `{session_id}`", ephemeral=True)
            
        except ValueError as e:
            await ctx.respond(f"❌ 設定エラー: {e}", ephemeral=True)
        except Exception as e:
            self.logger.error(f"Error starting relay session: {e}")
            await ctx.respond(f"❌ リレーセッションの開始に失敗しました: {e}", ephemeral=True)
    
    @discord.slash_command(name="relay_stop", description="音声リレーセッションを停止")
    async def relay_stop(
        self,
        ctx,
        session_id: discord.Option(str, "停止するセッションID", required=True)
    ):
        """音声リレーセッションを停止"""
        if not self._is_admin(ctx.author.id):
            await ctx.respond("❌ このコマンドは管理者のみ使用できます。", ephemeral=True)
            return
        
        try:
            success = await self.audio_relay.stop_relay_session(session_id)
            
            if success:
                await ctx.respond(f"🛑 音声リレーセッションを停止しました\nセッションID: `{session_id}`", ephemeral=True)
            else:
                await ctx.respond(f"❌ セッションが見つかりません: `{session_id}`", ephemeral=True)
                
        except Exception as e:
            self.logger.error(f"Error stopping relay session: {e}")
            await ctx.respond(f"❌ リレーセッションの停止に失敗しました: {e}", ephemeral=True)
    
    @discord.slash_command(name="relay_status", description="アクティブな音声リレーセッション一覧")
    async def relay_status(self, ctx):
        """アクティブなリレーセッション状態を表示"""
        if not self._is_admin(ctx.author.id):
            await ctx.respond("❌ このコマンドは管理者のみ使用できます。", ephemeral=True)
            return
        
        try:
            sessions = self.audio_relay.get_active_sessions()
            
            if not sessions:
                await ctx.respond("📋 現在アクティブなリレーセッションはありません。", ephemeral=True)
                return
            
            status_lines = []
            status_lines.append("📋 **アクティブなリレーセッション**")
            status_lines.append("")
            
            for session_id, info in sessions.items():
                duration_minutes = int(info["duration"] // 60)
                source_guild = self.bot.get_guild(info["source_guild_id"])
                target_guild = self.bot.get_guild(info["target_guild_id"])
                
                source_name = source_guild.name if source_guild else f"Unknown({info['source_guild_id']})"
                target_name = target_guild.name if target_guild else f"Unknown({info['target_guild_id']})"
                
                status_lines.append(f"🎤 **{session_id[:16]}...**")
                status_lines.append(f"   転送元: {source_name}")
                status_lines.append(f"   転送先: {target_name}")
                status_lines.append(f"   状態: {info['status']}")
                status_lines.append(f"   継続時間: {duration_minutes}分")
                status_lines.append("")
            
            status_text = "\n".join(status_lines)
            
            # Discordの2000文字制限対策
            if len(status_text) > 2000:
                status_text = status_text[:1997] + "..."
            
            await ctx.respond(status_text, ephemeral=True)
            
        except Exception as e:
            self.logger.error(f"Error getting relay status: {e}")
            await ctx.respond(f"❌ ステータス取得に失敗しました: {e}", ephemeral=True)
    
    async def cog_unload(self):
        """Cogアンロード時のクリーンアップ"""
        self.logger.info("Unloading RelayCog...")
        await self.audio_relay.stop_all_sessions()


def setup(bot):
    """Cog設定関数"""
    import yaml
    with open('config.yaml', 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    bot.add_cog(RelayCog(bot, config))