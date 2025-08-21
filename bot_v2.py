#!/usr/bin/env python3
"""
yomiageBotEx v2 - シンプルな録音機能付き読み上げBot
- StyleBertVITS2による読み上げ
- リプレイ録音機能
- 辞書機能（オプション）
"""

import os
import asyncio
import logging
from pathlib import Path
from typing import Optional

import discord
from discord.ext import commands
import yaml
from dotenv import load_dotenv

# 環境変数読み込み
load_dotenv()

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot_v2.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def load_config():
    """設定ファイル読み込み"""
    config_path = Path("config_v2.yaml")
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {}

class SimpleBotV2(commands.Bot):
    """シンプルなBotクラス"""
    
    def __init__(self):
        # 設定読み込み
        self.config = load_config()
        
        # Discord Intents設定
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True
        intents.guild_messages = True
        
        super().__init__(
            command_prefix='/',
            intents=intents,
            help_command=None
        )
        
        # 初期化フラグ
        self.is_ready = False
        
    async def setup_hook(self):
        """起動時の初期化処理"""
        logger.info("Bot setup starting...")
        
        # Cogの読み込み
        cogs = [
            'cogs_v2.voice',
            'cogs_v2.tts', 
            'cogs_v2.recording',
            'cogs_v2.dictionary'
        ]
        
        for cog in cogs:
            try:
                await self.load_extension(cog)
                logger.info(f"Loaded cog: {cog}")
            except Exception as e:
                logger.error(f"Failed to load cog {cog}: {e}")
        
        logger.info("Bot setup completed")
    
    async def on_ready(self):
        """Bot準備完了時"""
        if not self.is_ready:
            logger.info(f"Bot logged in as {self.user}")
            logger.info(f"Bot ID: {self.user.id}")
            logger.info(f"Connected to {len(self.guilds)} guilds")
            
            # スラッシュコマンド同期
            try:
                synced = await self.tree.sync()
                logger.info(f"Synced {len(synced)} slash commands")
            except Exception as e:
                logger.error(f"Failed to sync commands: {e}")
            
            self.is_ready = True
    
    async def on_error(self, event, *args, **kwargs):
        """エラーハンドリング"""
        logger.error(f"Error in event {event}", exc_info=True)
    
    async def close(self):
        """Bot終了処理"""
        logger.info("Bot shutting down...")
        await super().close()

async def main():
    """メイン実行関数"""
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        logger.error("DISCORD_TOKEN not found in environment variables")
        return
    
    bot = SimpleBotV2()
    
    try:
        await bot.start(token)
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot error: {e}", exc_info=True)
    finally:
        await bot.close()

if __name__ == "__main__":
    asyncio.run(main())