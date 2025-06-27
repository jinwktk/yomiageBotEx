#!/usr/bin/env python3
"""
yomiageBotEx - Discord読み上げボット (Phase 2: Cog構造 + 自動参加/退出)
"""

import os
import sys
import asyncio
import logging
from pathlib import Path
from typing import Optional

import discord
from discord.ext import commands
import yaml
from dotenv import load_dotenv

from utils.logger import setup_logging, start_log_cleanup_task

# 音声受信クライアントのインポート（py-cord優先、フォールバック付き）
try:
    from utils.real_audio_recorder import RealEnhancedVoiceClient as EnhancedVoiceClient
    print("✅ Using py-cord real audio recording")
    VOICE_CLIENT_TYPE = "py-cord"
except Exception as e:
    print(f"⚠️ Could not import RealEnhancedVoiceClient: {e}, trying fallback")
    try:
        from utils.voice_receiver import EnhancedVoiceClient
        print("✅ Using discord.py fallback audio simulation")
        VOICE_CLIENT_TYPE = "discord.py"
    except Exception as e2:
        print(f"⚠️ Could not import EnhancedVoiceClient: {e2}, using simple recorder")
        from utils.simple_recorder import SimpleEnhancedVoiceClient as EnhancedVoiceClient
        VOICE_CLIENT_TYPE = "simple"

# 環境変数の読み込み
load_dotenv()

# 設定ファイルの読み込み
def load_config():
    """設定ファイルを読み込む"""
    config_path = Path("config.yaml")
    print(f"DEBUG: Loading config from: {config_path.absolute()}")
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
            print(f"DEBUG: TTS API URL: {config.get('tts', {}).get('api_url', 'NOT_FOUND')}")
            return config
    else:
        # デフォルト設定
        return {
            "bot": {
                "command_prefix": "/",
                "auto_join": True,
                "auto_leave": True,
                "rate_limit_delay": [0.5, 1.0]
            },
            "logging": {
                "level": "INFO",
                "file": "logs/yomiage.log"
            }
        }

# 設定の読み込み
config = load_config()

# ロギングの初期化
logger = setup_logging(config)

class YomiageBot(commands.Bot):
    """読み上げボットのメインクラス"""
    
    def __init__(self):
        # Intentsの設定
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True
        intents.guilds = True
        
        super().__init__(
            command_prefix=config["bot"]["command_prefix"],
            intents=intents,
            help_command=None  # デフォルトのヘルプコマンドを無効化
        )
        
        self.config = config
        
    async def setup_hook(self):
        """起動時の初期設定"""
        logger.info("Bot setup started...")
        
        # Cogの読み込み
        await self.load_cogs()
        
        # ログクリーンアップタスクの開始
        asyncio.create_task(start_log_cleanup_task(self.config))
        
        # py-cordではスラッシュコマンドは自動同期されるため、手動同期は不要
        logger.info("Bot setup completed (py-cord auto-syncs slash commands)")
    
    async def load_cogs(self):
        """Cogを読み込む"""
        cogs = [
            "cogs.voice",
            "cogs.tts",
            "cogs.recording",
            "cogs.message_reader",
        ]
        
        for cog in cogs:
            try:
                # Cogモジュールを動的にインポート
                module = __import__(cog, fromlist=["setup"])
                await module.setup(self, self.config)
                logger.info(f"Loaded cog: {cog}")
            except Exception as e:
                logger.error(f"Failed to load cog {cog}: {e}")
    
    async def on_ready(self):
        """Bot準備完了時のイベント"""
        logger.info(f"Bot is ready! Logged in as {self.user} (ID: {self.user.id})")
        logger.info(f"Connected to {len(self.guilds)} guild(s)")
        logger.info(f"Voice client type: {VOICE_CLIENT_TYPE}")
        
        # ステータスの設定
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.listening,
                name="自動参加・退出対応 | /join"
            )
        )
    
    async def on_error(self, event_method: str, *args, **kwargs):
        """エラーハンドリング"""
        logger.error(f"Error in {event_method}", exc_info=True)
    
    async def connect_to_voice(self, channel: discord.VoiceChannel) -> discord.VoiceClient:
        """カスタムVoiceClientで接続"""
        # 既存の接続をチェック
        if channel.guild.voice_client:
            await channel.guild.voice_client.disconnect()
        
        # EnhancedVoiceClientを使用して接続
        return await channel.connect(cls=EnhancedVoiceClient)
    
# Botインスタンスの作成
bot = YomiageBot()

def main():
    """メイン実行関数"""
    # トークンの確認
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        logger.error("DISCORD_TOKEN not found in environment variables")
        print("エラー: .envファイルにDISCORD_TOKENを設定してください。")
        sys.exit(1)
    
    # Botの起動
    try:
        logger.info("Starting bot...")
        bot.run(token)
    except discord.LoginFailure:
        logger.error("Invalid token")
        print("エラー: 無効なトークンです。")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()