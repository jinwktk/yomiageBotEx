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
import signal
import time

import discord
from discord.ext import commands
import yaml
from dotenv import load_dotenv
import fnmatch

# cogwatchはオプショナル - 開発用ホットリロード機能
try:
    from cogwatch import watch
    COGWATCH_AVAILABLE = True
except ImportError:
    COGWATCH_AVAILABLE = False
    print("⚠️ cogwatch not installed - hot reload feature disabled")

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
            
            # TTS設定は data/tts_config.json から取得
            try:
                tts_config_path = Path("data/tts_config.json")
                if tts_config_path.exists():
                    import json
                    with open(tts_config_path, "r", encoding="utf-8") as tts_f:
                        tts_config = json.load(tts_f)
                        print(f"DEBUG: TTS API URL: {tts_config.get('api_url', 'NOT_FOUND')}")
                else:
                    print("DEBUG: TTS API URL: data/tts_config.json NOT_FOUND")
            except Exception as e:
                print(f"DEBUG: TTS API URL: ERROR - {e}")
            
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
            intents=intents,
            heartbeat_timeout=60.0  # HeartBeatタイムアウトを60秒に延長
            # debug_guildsを削除してグローバル同期に変更
        )
        
        self.config = config
        self._cogs_loaded = False
        
        # 起動時にCogを読み込み
        self.setup_cogs()
    
    async def connect_voice_safely(self, channel):
        """安全な音声接続（重複接続対応強化版）"""
        max_retries = 3
        retry_delay = 2.0
        
        # 事前チェック：既に接続している場合
        guild = channel.guild
        if guild.voice_client and guild.voice_client.is_connected():
            current_channel = guild.voice_client.channel
            if current_channel == channel:
                logger.info(f"Already connected to target channel {channel.name}, returning existing connection")
                return guild.voice_client
            else:
                logger.info(f"Already connected to {current_channel.name}, moving to {channel.name}")
                await guild.voice_client.move_to(channel)
                return guild.voice_client
        elif guild.voice_client and not guild.voice_client.is_connected():
            logger.info(f"Cleaning up disconnected voice client for {guild.name}")
            try:
                await guild.voice_client.disconnect()
            except:
                pass  # エラーは無視してクリーンアップを続行
        
        for attempt in range(max_retries):
            try:
                logger.info(f"Voice connection attempt {attempt + 1}/{max_retries} to {channel.name}")
                
                # タイムアウトとreconnectで接続の安定性を向上
                vc = await channel.connect(
                    timeout=60.0,  # タイムアウトを延長（45秒→60秒）
                    reconnect=True
                )
                
                # 接続成功後の安定化待機を延長
                await asyncio.sleep(2.0)
                
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
                    
            except discord.ClientException as e:
                if "Already connected to a voice channel" in str(e):
                    logger.warning(f"Already connected error: {e}")
                    # 既存接続を確認して適切に処理
                    current_vc = guild.voice_client
                    if current_vc and current_vc.is_connected():
                        if current_vc.channel == channel:
                            logger.info(f"Already connected to target channel {channel.name}")
                            return current_vc
                        else:
                            logger.info(f"Moving from {current_vc.channel.name} to {channel.name}")
                            await current_vc.move_to(channel)
                            return current_vc
                    else:
                        logger.error("ClientException occurred but no valid connection found")
                        # 無効な接続状態をクリーンアップ
                        try:
                            if guild.voice_client:
                                logger.info("Force cleaning up invalid voice client state")
                                await guild.voice_client.disconnect()
                                guild._voice_client = None
                        except:
                            pass
                        
                        # クリーンアップ後に再試行
                        if attempt < max_retries - 1:
                            logger.info(f"Retrying after cleanup, attempt {attempt + 2}")
                            await asyncio.sleep(retry_delay)
                            continue
                        else:
                            logger.warning("Final attempt with ClientException, will try fallback method")
                            # 最終試行では例外を投げずに続行してフォールバック処理に進む
                            break
                else:
                    logger.error(f"Voice connection attempt {attempt + 1} failed: {e}")
                    
            except Exception as e:
                logger.error(f"Voice connection attempt {attempt + 1} failed: {e}")
                
                # list index out of range エラーの特別な処理
                if "list index out of range" in str(e):
                    logger.warning(f"Encryption mode selection error detected: {e}")
                    # 不完全な接続状態をクリーンアップ
                    try:
                        if guild.voice_client:
                            logger.info("Cleaning up partial connection after list index error")
                            await guild.voice_client.disconnect()
                            # 強制的にNoneに設定
                            guild._voice_client = None
                    except:
                        pass
                    
                    if attempt < max_retries - 1:
                        logger.info(f"Retrying after {retry_delay}s due to encryption error...")
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 1.5
                        continue
                
                # WebSocket 4000 エラーの特別な処理
                elif "4000" in str(e) or "WebSocket" in str(e) or "ClientConnectionResetError" in str(e):
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
                    logger.warning("All connection attempts failed, trying basic connect")
                    logger.info(f"Attempting fallback connection to {channel.name} in {guild.name}")
                    
                    # 最終的なクリーンアップ
                    try:
                        if guild.voice_client:
                            logger.info("Final cleanup before fallback connection")
                            await guild.voice_client.disconnect()
                            guild._voice_client = None
                            await asyncio.sleep(1.0)  # クリーンアップ待機
                    except:
                        pass
                    
                    try:
                        logger.info("Executing basic channel.connect() fallback")
                        vc = await channel.connect()
                        if vc and vc.is_connected():
                            logger.info(f"Fallback connection successful to {channel.name}")
                            return vc
                        else:
                            logger.error("Fallback connection returned invalid voice client")
                            return vc
                    except discord.ClientException as fallback_e:
                        if "Already connected to a voice channel" in str(fallback_e):
                            logger.warning("Fallback also failed with already connected error")
                            # グローバルクリーンアップを試行
                            for g in self.guilds:
                                try:
                                    if g.voice_client:
                                        logger.info(f"Global cleanup: disconnecting from {g.name}")
                                        await g.voice_client.disconnect()
                                        g._voice_client = None
                                except:
                                    pass
                            
                            # 最終的に再試行
                            await asyncio.sleep(2.0)
                            try:
                                return await channel.connect()
                            except:
                                logger.error("Final fallback connection also failed")
                                raise fallback_e
                        raise
                    except Exception as e2:
                        logger.error(f"Fallback connection also failed: {e2}")
                        raise
        
        # forループを抜けた場合（breakまたは全試行完了）のフォールバック処理
        logger.warning("Loop completed without successful connection, executing final fallback")
        logger.info(f"Final fallback attempt to {channel.name} in {guild.name}")
        
        # 最終クリーンアップ
        try:
            if guild.voice_client:
                logger.info("Final cleanup before ultimate fallback")
                await guild.voice_client.disconnect()
                guild._voice_client = None
                await asyncio.sleep(1.0)
        except:
            pass
        
        # 最終フォールバック
        try:
            logger.info("Executing ultimate fallback: basic channel.connect()")
            vc = await channel.connect()
            if vc and vc.is_connected():
                logger.info(f"Ultimate fallback successful to {channel.name}")
                return vc
            else:
                logger.error("Ultimate fallback returned invalid voice client")
                raise Exception("Ultimate fallback failed: invalid connection")
        except Exception as final_e:
            logger.error(f"Ultimate fallback failed: {final_e}")
            raise final_e
        
    def setup_cogs(self):
        """起動時のCog読み込み（同期処理）"""
        logger.info("Loading cogs...")
        
        try:
            self.load_cogs_sync()
            self._cogs_loaded = True
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
                # 既に読み込まれているかチェック
                if cog in self.extensions:
                    logger.debug(f"Cog {cog} already loaded, skipping")
                    continue
                
                # py-cordの推奨方法でCogを読み込み
                self.load_extension(cog)
                logger.info(f"Loaded cog: {cog}")
            except Exception as e:
                logger.error(f"Failed to load cog {cog}: {e}", exc_info=True)
                
    async def load_cogs(self):
        """Cogを読み込む（非同期版）"""
        self.load_cogs_sync()
    
    async def on_ready(self, client=None):
        """Bot準備完了時のイベント"""
        logger.info(f"Bot is ready! Logged in as {self.user} (ID: {self.user.id})")
        logger.info(f"Connected to {len(self.guilds)} guild(s)")
        logger.info(f"Voice client type: {VOICE_CLIENT_TYPE}")
        
        if COGWATCH_AVAILABLE:
            logger.info("🔄 Cogwatch enabled - Cogs will auto-reload on file changes")
        else:
            logger.info("ℹ️ Cogwatch not available - manual Cog management only")
        
        # Cogが読み込まれていない場合は手動で読み込み
        if len(self.cogs) == 0:
            logger.warning("No cogs loaded, attempting manual load...")
            await self.load_cogs()
        elif not self._cogs_loaded:
            logger.info("Cogs already loaded by cogwatch preload")
        
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
        
        # TTSセッションのクリーンアップ（全Cog）
        tts_cog = self.get_cog("TTSCog")
        if tts_cog and hasattr(tts_cog, 'tts_manager'):
            try:
                await tts_cog.tts_manager.cleanup()
                logger.info("TTSCog session cleanup completed")
            except Exception as e:
                logger.error(f"Failed to cleanup TTSCog session: {e}")
        
        # MessageReaderCogのTTSManagerもクリーンアップ
        message_reader_cog = self.get_cog("MessageReaderCog")
        if message_reader_cog and hasattr(message_reader_cog, 'tts_manager'):
            try:
                await message_reader_cog.tts_manager.cleanup()
                logger.info("MessageReaderCog session cleanup completed")
            except Exception as e:
                logger.error(f"Failed to cleanup MessageReaderCog session: {e}")
        
        logger.info("TTS session cleanup completed")
        
        # 親クラスのクリーンアップを呼び出し
        await super().close()
    
    async def connect_to_voice(self, channel: discord.VoiceChannel) -> discord.VoiceClient:
        """カスタムVoiceClientで接続（重複接続対応）"""
        guild = channel.guild
        
        # 詳細な既存接続チェック
        if guild.voice_client and guild.voice_client.is_connected():
            current_channel = guild.voice_client.channel
            if current_channel == channel:
                logger.info(f"connect_to_voice: Already connected to target channel {channel.name}")
                return guild.voice_client
            else:
                logger.info(f"connect_to_voice: Moving from {current_channel.name} to {channel.name}")
                await guild.voice_client.move_to(channel)
                return guild.voice_client
        elif guild.voice_client and not guild.voice_client.is_connected():
            logger.info(f"connect_to_voice: Cleaning up disconnected voice client for {guild.name}")
            try:
                await guild.voice_client.disconnect()
            except:
                pass  # エラーは無視してクリーンアップを続行
        
        # 安全な接続を試行
        try:
            return await self.connect_voice_safely(channel)
        except discord.ClientException as e:
            if "Already connected to a voice channel" in str(e):
                logger.warning(f"connect_to_voice: ClientException - {e}")
                # 既存接続を再確認して返す
                if guild.voice_client and guild.voice_client.is_connected():
                    logger.info("connect_to_voice: Returning existing connection after ClientException")
                    return guild.voice_client
                else:
                    logger.error("connect_to_voice: ClientException but no valid connection found")
                    raise
            else:
                logger.error(f"connect_to_voice: Safe connection failed with ClientException: {e}")
                raise
        except Exception as e:
            logger.error(f"connect_to_voice: Safe connection failed, trying EnhancedVoiceClient: {e}")
            # フォールバック：EnhancedVoiceClientを使用
            try:
                return await channel.connect(cls=EnhancedVoiceClient)
            except discord.ClientException as fallback_e:
                if "Already connected to a voice channel" in str(fallback_e):
                    logger.warning(f"connect_to_voice: EnhancedVoiceClient fallback also failed - {fallback_e}")
                    # 最終的に既存接続を返す
                    if guild.voice_client and guild.voice_client.is_connected():
                        return guild.voice_client
                raise
    
# Botインスタンスの作成
bot = YomiageBot()

# cogwatchが利用可能な場合、on_readyメソッドにwatchデコレータを適用
if COGWATCH_AVAILABLE:
    bot.on_ready = watch(path="cogs", preload=True, debug=False)(bot.on_ready)

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
    
    # シグナルハンドラーの設定（PST.exe保護機能を改善）
    sigint_count = 0
    last_sigint_time = 0
    
    def signal_handler(signum, frame):
        nonlocal sigint_count, last_sigint_time
        logger.info(f"Received signal {signum}, initiating shutdown...")
        
        if signum == signal.SIGINT:
            current_time = time.time()
            
            # 短時間での連続SIGINT（PST.exeの可能性）をチェック
            if current_time - last_sigint_time < 2.0:  # 2秒以内の連続SIGINT
                sigint_count += 1
                logger.warning(f"SIGINT #{sigint_count} received within 2s - possibly from PST.exe")
                
                if sigint_count >= 3:  # 3回以上の連続SIGINT
                    logger.info("Multiple rapid SIGINTs detected - likely PST.exe interference. Ignoring...")
                    return  # PST.exeからの信号を無視
            else:
                # 単発のSIGINTまたは時間が空いている場合（ユーザーのCtrl+C）
                sigint_count = 1
                logger.info("Single SIGINT received - likely user Ctrl+C. Initiating shutdown...")
            
            last_sigint_time = current_time
            
            # 単発のSIGINTは正常な終了要求として処理
            if sigint_count <= 2:
                asyncio.create_task(shutdown_handler())
            return
        
        # SIGTERM等は即座に処理
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