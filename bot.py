#!/usr/bin/env python3
"""
yomiageBotEx - Discord読み上げボット (Phase 1: 基本機能)
"""

import os
import sys
import asyncio
import random
import logging
from pathlib import Path
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
import yaml
from dotenv import load_dotenv

# 環境変数の読み込み
load_dotenv()

# 設定ファイルの読み込み
def load_config():
    """設定ファイルを読み込む"""
    config_path = Path("config.yaml")
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
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

# ロギングの設定
def setup_logging():
    """ロギングの初期設定"""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    log_level = getattr(logging, config["logging"]["level"], logging.INFO)
    log_file = config["logging"]["file"]
    
    # フォーマッターの設定
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # ファイルハンドラー
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    
    # コンソールハンドラー
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    
    # ロガーの設定
    logger = logging.getLogger()
    logger.setLevel(log_level)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

# ロギングの初期化
logger = setup_logging()

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
        
        # スラッシュコマンドの同期
        try:
            synced = await self.tree.sync()
            logger.info(f"Synced {len(synced)} command(s)")
        except Exception as e:
            logger.error(f"Failed to sync commands: {e}")
    
    async def on_ready(self):
        """Bot準備完了時のイベント"""
        logger.info(f"Bot is ready! Logged in as {self.user} (ID: {self.user.id})")
        logger.info(f"Connected to {len(self.guilds)} guild(s)")
        
        # ステータスの設定
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.listening,
                name="/join でVCに参加"
            )
        )
    
    async def on_error(self, event_method: str, *args, **kwargs):
        """エラーハンドリング"""
        logger.error(f"Error in {event_method}", exc_info=True)
    
    async def rate_limit_delay(self):
        """レート制限対策の遅延"""
        delay = random.uniform(*self.config["bot"]["rate_limit_delay"])
        await asyncio.sleep(delay)

# Botインスタンスの作成
bot = YomiageBot()

@bot.tree.command(name="join", description="ボイスチャンネルに参加します")
async def join_command(interaction: discord.Interaction):
    """VCに参加するコマンド"""
    await bot.rate_limit_delay()
    
    # ユーザーがVCに接続しているか確認
    if not interaction.user.voice:
        await interaction.response.send_message(
            "❌ ボイスチャンネルに接続してから実行してください。",
            ephemeral=True
        )
        logger.warning(f"Join failed: {interaction.user} is not in a voice channel")
        return
    
    channel = interaction.user.voice.channel
    
    # 既に接続している場合
    if interaction.guild.voice_client:
        if interaction.guild.voice_client.channel == channel:
            await interaction.response.send_message(
                f"✅ 既に {channel.name} に接続しています。",
                ephemeral=True
            )
            return
        else:
            # 別のチャンネルに移動
            try:
                await interaction.guild.voice_client.move_to(channel)
                await interaction.response.send_message(
                    f"🔄 {channel.name} に移動しました。",
                    ephemeral=True
                )
                logger.info(f"Moved to voice channel: {channel.name} in {interaction.guild.name}")
                return
            except Exception as e:
                logger.error(f"Failed to move to voice channel: {e}")
                await interaction.response.send_message(
                    "❌ チャンネルの移動に失敗しました。",
                    ephemeral=True
                )
                return
    
    # 新規接続
    try:
        await channel.connect(timeout=10.0, reconnect=True)
        await interaction.response.send_message(
            f"✅ {channel.name} に接続しました！",
            ephemeral=True
        )
        logger.info(f"Connected to voice channel: {channel.name} in {interaction.guild.name}")
    except asyncio.TimeoutError:
        await interaction.response.send_message(
            "❌ 接続がタイムアウトしました。",
            ephemeral=True
        )
        logger.error("Voice connection timeout")
    except Exception as e:
        await interaction.response.send_message(
            "❌ 接続に失敗しました。",
            ephemeral=True
        )
        logger.error(f"Failed to connect to voice channel: {e}")

@bot.tree.command(name="leave", description="ボイスチャンネルから退出します")
async def leave_command(interaction: discord.Interaction):
    """VCから退出するコマンド"""
    await bot.rate_limit_delay()
    
    # ボットが接続しているか確認
    if not interaction.guild.voice_client:
        await interaction.response.send_message(
            "❌ ボイスチャンネルに接続していません。",
            ephemeral=True
        )
        return
    
    try:
        channel_name = interaction.guild.voice_client.channel.name
        await interaction.guild.voice_client.disconnect()
        await interaction.response.send_message(
            f"👋 {channel_name} から退出しました。",
            ephemeral=True
        )
        logger.info(f"Disconnected from voice channel: {channel_name} in {interaction.guild.name}")
    except Exception as e:
        await interaction.response.send_message(
            "❌ 退出に失敗しました。",
            ephemeral=True
        )
        logger.error(f"Failed to disconnect from voice channel: {e}")

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