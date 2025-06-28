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
from cogwatch import watch

from utils.logger import setup_logging, start_log_cleanup_task

# 音声受信クライアントのインポート（py-cord統合版のみ使用）
try:
    from utils.real_audio_recorder import RealEnhancedVoiceClient as EnhancedVoiceClient
    print("✅ Using py-cord real audio recording")
    VOICE_CLIENT_TYPE = "py-cord"
except Exception as e:
    print(f"❌ Could not import RealEnhancedVoiceClient: {e}")
    print("   Please ensure py-cord[voice] and required dependencies are installed")
    sys.exit(1)

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

class YomiageBot(discord.Bot):
    """読み上げボットのメインクラス"""
    
    def __init__(self):
        # Intentsの設定
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True
        intents.guilds = True
        intents.members = True  # メンバー情報の取得を有効化
        
        # グローバルコマンド同期（すべてのギルドで利用可能）
        # debug_guildsを指定しないことで、すべてのギルドでコマンドが同期される
        super().__init__(
            intents=intents
            # debug_guildsを削除してグローバル同期に変更
        )
        
        self.config = config
    
    async def connect_voice_safely(self, channel):
        """安全な音声接続（WebSocketエラー対応強化版）"""
        max_retries = 3
        retry_delay = 2.0
        
        for attempt in range(max_retries):
            try:
                logger.info(f"Voice connection attempt {attempt + 1}/{max_retries} to {channel.name}")
                
                # タイムアウトとreconnectで接続の安定性を向上
                vc = await channel.connect(
                    timeout=45.0,  # タイムアウトを延長
                    reconnect=True
                )
                
                # 接続成功後の安定化待機
                await asyncio.sleep(1.0)
                
                # 接続状態の確認
                if vc and vc.is_connected():
                    logger.info(f"Voice connection successful to {channel.name}")
                    
                    try:
                        # 接続後にdeafenを設定
                        await channel.guild.change_voice_state(
                            channel=channel,
                            self_deaf=True,
                            self_mute=False
                        )
                        logger.info("Voice state (self_deaf=True) set successfully")
                    except Exception as state_error:
                        logger.warning(f"Failed to set voice state, but connection is OK: {state_error}")
                    
                    return vc
                else:
                    logger.warning(f"Connection established but not stable, attempt {attempt + 1}")
                    if vc:
                        await vc.disconnect()
                    raise Exception("Connection not stable")
                    
            except Exception as e:
                logger.error(f"Voice connection attempt {attempt + 1} failed: {e}")
                
                # WebSocket 4000 エラーの特別な処理
                if "4000" in str(e) or "WebSocket" in str(e):
                    logger.warning(f"WebSocket error detected: {e}")
                    if attempt < max_retries - 1:
                        logger.info(f"Retrying after {retry_delay}s due to WebSocket error...")
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 1.5  # 指数バックオフ
                        continue
                
                # 最後の試行でない場合はリトライ
                if attempt < max_retries - 1:
                    logger.info(f"Retrying connection after {retry_delay}s...")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 1.2
                else:
                    # 最後の試行：フォールバック
                    logger.error("All connection attempts failed, trying basic connect")
                    try:
                        return await channel.connect()
                    except Exception as e2:
                        logger.error(f"Fallback connection also failed: {e2}")
                        raise
        
    def setup_cogs(self):
        """起動時のCog読み込み（同期処理）"""
        logger.info("Loading cogs...")
        
        try:
            self.load_cogs_sync()
            logger.info(f"Cogs loaded. Total cogs: {len(self.cogs)}")
        except Exception as e:
            logger.error(f"Failed to load cogs: {e}", exc_info=True)
    
    def load_cogs_sync(self):
        """Cogを読み込む（同期版）"""
        cogs = [
            "cogs.voice",
            "cogs.tts", 
            "cogs.recording",
            "cogs.message_reader",
            "cogs.dictionary",
            "cogs.user_settings",
        ]
        
        for cog in cogs:
            try:
                # py-cordの推奨方法でCogを読み込み
                self.load_extension(cog)
                logger.info(f"Loaded cog: {cog}")
            except Exception as e:
                logger.error(f"Failed to load cog {cog}: {e}", exc_info=True)
                
    async def load_cogs(self):
        """Cogを読み込む（非同期版）"""
        self.load_cogs_sync()
    
    @watch(path="cogs", preload=True)
    async def on_ready(self):
        """Bot準備完了時のイベント"""
        logger.info(f"Bot is ready! Logged in as {self.user} (ID: {self.user.id})")
        logger.info(f"Connected to {len(self.guilds)} guild(s)")
        logger.info(f"Voice client type: {VOICE_CLIENT_TYPE}")
        logger.info("🔄 Cogwatch enabled - Cogs will auto-reload on file changes")
        
        # デバッグ用にギルドIDをログ出力
        if self.guilds:
            logger.info("Guild IDs:")
            for guild in self.guilds:
                logger.info(f"  - {guild.name}: {guild.id}")
                
        # py-cordのスラッシュコマンド確認（bot_simple.pyから移植）
        logger.info(f"Bot commands: {len(self.commands)}")
        logger.info(f"Bot cogs: {list(self.cogs.keys())}")
        for cmd in self.commands:
            logger.info(f"  Command: {cmd.name} (type: {type(cmd).__name__})")
        
        # Cogのコマンド詳細確認
        for cog_name, cog in self.cogs.items():
            cog_commands = cog.get_commands()
            logger.info(f"Cog {cog_name}: {len(cog_commands)} commands")
            for cmd in cog_commands:
                logger.info(f"  - {cmd.name}")
        
        # ログクリーンアップタスクの開始
        asyncio.create_task(start_log_cleanup_task(self.config))
        
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
    
    async def on_application_command_error(self, ctx, error):
        """スラッシュコマンドのエラーハンドリング"""
        logger.error(f"Application command error in {ctx.command.name}: {error}", exc_info=True)
        
        # ユーザーへのエラー通知
        try:
            if ctx.response.is_done():
                await ctx.followup.send(f"❌ コマンドの実行中にエラーが発生しました: {str(error)}", ephemeral=True)
            else:
                await ctx.respond(f"❌ コマンドの実行中にエラーが発生しました: {str(error)}", ephemeral=True)
        except Exception as e:
            logger.error(f"Failed to send error message to user: {e}")
    
    async def on_command_error(self, ctx, error):
        """通常コマンドのエラーハンドリング"""
        logger.error(f"Command error in {ctx.command}: {error}", exc_info=True)
    
    async def close(self):
        """Bot終了時のクリーンアップ"""
        logger.info("Bot is shutting down, cleaning up resources...")
        
        # TTSセッションのクリーンアップ
        tts_cog = self.get_cog("TTSCog")
        if tts_cog and hasattr(tts_cog, 'tts_manager'):
            try:
                await tts_cog.tts_manager.cleanup()
                logger.info("TTS session cleanup completed")
            except Exception as e:
                logger.error(f"Failed to cleanup TTS session: {e}")
        
        # 親クラスのクリーンアップを呼び出し
        await super().close()
    
    async def connect_to_voice(self, channel: discord.VoiceChannel) -> discord.VoiceClient:
        """カスタムVoiceClientで接続"""
        # 既存の接続をチェック
        if channel.guild.voice_client:
            await channel.guild.voice_client.disconnect()
        
        # 安全な接続を試行
        try:
            return await self.connect_voice_safely(channel)
        except Exception as e:
            logger.error(f"Safe connection failed, trying EnhancedVoiceClient: {e}")
            # フォールバック：EnhancedVoiceClientを使用
            return await channel.connect(cls=EnhancedVoiceClient)
    
# Botインスタンスの作成
bot = YomiageBot()

# Cogの初期読み込み
bot.setup_cogs()

async def shutdown_handler():
    """シャットダウン時のクリーンアップハンドラ"""
    logger.info("Shutdown signal received, cleaning up...")
    await bot.close()

def main():
    """メイン実行関数"""
    # トークンの確認
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        logger.error("DISCORD_TOKEN not found in environment variables")
        print("エラー: .envファイルにDISCORD_TOKENを設定してください。")
        sys.exit(1)
    
    # シグナルハンドラーの設定
    import signal
    
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, initiating shutdown...")
        asyncio.create_task(shutdown_handler())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Botの起動
    try:
        logger.info("Starting bot...")
        bot.run(token)
    except discord.LoginFailure:
        logger.error("Invalid token")
        print("エラー: 無効なトークンです。")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
        # シャットダウン処理を実行
        asyncio.run(shutdown_handler())
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        # 例外発生時もクリーンアップを実行
        try:
            asyncio.run(shutdown_handler())
        except:
            pass
        sys.exit(1)

if __name__ == "__main__":
    main()