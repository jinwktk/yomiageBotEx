"""
音声横流し（リレー）機能Cog - シンプル実装版
"""

import asyncio
import logging
from typing import Dict, Any

import discord
from discord.ext import commands

from utils.simple_audio_relay import SimpleAudioRelay, RelayStatus


class RelayCog(commands.Cog):
    """音声横流し（リレー）機能 - シンプル版"""
    
    def __init__(self, bot: commands.Bot, config: Dict[str, Any]):
        print("DEBUG: RelayCog.__init__ called")  # デバッグ用
        self.bot = bot
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        print("DEBUG: Creating SimpleAudioRelay...")  # デバッグ用
        # SimpleAudioRelayマネージャーの初期化
        self.audio_relay = SimpleAudioRelay(bot, config, self.logger)
        print("DEBUG: SimpleAudioRelay created")  # デバッグ用
        
        # 管理者ユーザーID
        self.admin_user_id = config.get("bot", {}).get("admin_user_id")
        
        # 自動開始設定
        self.auto_start_config = config.get("audio_relay", {}).get("auto_start", False)
        
        # ログ初期化
        self.logger.info("RelayCog initialized")
        self.logger.info(f"Audio relay enabled: {self.audio_relay.enabled}")
        
        if self.auto_start_config:
            self.logger.info("Auto start config: True")
            auto_relay_pairs = config.get("audio_relay", {}).get("auto_relay_pairs", [])
            self.logger.info(f"Auto relay pairs: {len(auto_relay_pairs)} pairs")
            self.logger.info("Auto start conditions met, will start relay on bot ready")
        else:
            self.logger.info("Auto start config: False")
    
    async def _auto_start_relay_sessions(self):
        """シンプル自動リレーセッションの開始"""
        if not self.config.get("audio_relay", {}).get("enabled", False):
            self.logger.info("Audio relay is disabled, skipping auto start")
            return
            
        self.logger.info("Starting simple auto relay sessions...")
        
        auto_relay_pairs = self.config.get("audio_relay", {}).get("auto_relay_pairs", [])
        if not auto_relay_pairs:
            self.logger.info("No auto relay pairs configured")
            return
        
        started_count = 0
        
        for pair in auto_relay_pairs:
            if not pair.get("enabled", False):
                continue
                
            try:
                source_guild_id = pair.get("source_guild_id")
                source_channel_id = pair.get("source_channel_id")  # 固定チャンネルIDを使用
                target_guild_id = pair.get("target_guild_id")
                target_channel_id = pair.get("target_channel_id")
                
                if not all([source_guild_id, source_channel_id, target_guild_id, target_channel_id]):
                    self.logger.warning(f"Invalid relay pair configuration: {pair}")
                    continue
                
                # シンプルリレーセッション開始
                session_id = await self.audio_relay.start_relay_session(
                    source_guild_id=source_guild_id,
                    source_channel_id=source_channel_id,
                    target_guild_id=target_guild_id,
                    target_channel_id=target_channel_id
                )
                
                self.logger.info(f"🎤 AUTO-STARTED RELAY: Session {session_id}")
                started_count += 1
                
            except Exception as e:
                self.logger.error(f"Failed to auto-start relay session for pair {pair}: {e}")
        
        self.logger.info(f"Simple auto relay sessions started: {started_count} sessions")
    
    def _is_admin(self, user_id: int) -> bool:
        """管理者権限チェック"""
        return self.admin_user_id and user_id == self.admin_user_id
    
    @commands.Cog.listener()
    async def on_ready(self):
        """ボット準備完了時にクリーンアップタスクを開始（自動リレーはVoiceCogからの通知で開始）"""
        self.logger.info("RelayCog on_ready triggered")
        auto_start_enabled = self.config.get("audio_relay", {}).get("auto_start", False)
        self.logger.info(f"Auto start enabled: {auto_start_enabled} (will be triggered by VoiceCog after voice connection)")
    
    async def handle_voice_connected(self, guild_id: int, channel_id: int):
        """VoiceCogからの音声接続完了通知を受信してリレーを開始"""
        auto_start_enabled = self.config.get("audio_relay", {}).get("auto_start", False)
        if not auto_start_enabled:
            return
            
        # 対象チャンネルかチェック
        auto_relay_pairs = self.config.get("audio_relay", {}).get("auto_relay_pairs", [])
        for pair in auto_relay_pairs:
            if pair.get("enabled", False) and pair.get("source_guild_id") == guild_id and pair.get("source_channel_id") == channel_id:
                self.logger.info(f"Voice connection confirmed for relay source channel {channel_id}, starting auto relay...")
                await asyncio.sleep(3)  # 接続安定化待機
                await self._auto_start_relay_sessions()
                break
    
    def cog_unload(self):
        """Cogアンロード時のクリーンアップ"""
        # すべてのリレーセッションを停止
        asyncio.create_task(self.audio_relay.stop_all_sessions())


def setup(bot):
    """Cog設定関数"""
    import yaml
    with open('config.yaml', 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    bot.add_cog(RelayCog(bot, config))