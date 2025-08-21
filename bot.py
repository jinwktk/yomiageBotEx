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
    print("WARNING: cogwatch not installed - hot reload feature disabled")

from utils.logger import setup_logging, start_log_cleanup_task

# 音声受信クライアントのインポート（py-cord統合版のみ使用）
try:
    from utils.real_audio_recorder import RealEnhancedVoiceClient as EnhancedVoiceClient
    print("SUCCESS: Using py-cord real audio recording")
    VOICE_CLIENT_TYPE = "py-cord"
except Exception as e:
    print(f"ERROR: Could not import RealEnhancedVoiceClient: {e}")
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

class YomiageBot(commands.Bot):
    """読み上げボットのメインクラス"""
    
    def __init__(self):
        # Intentsの設定
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True
        intents.guilds = True
        intents.members = True  # メンバー情報の取得を有効化
        
        # デバッグ用ギルド設定（即座にコマンド同期）
        debug_guilds = [813783748566581249, 995627275074666568]  # にめろうサーバー、Valworld
        
        super().__init__(
            command_prefix='/',
            intents=intents,
            heartbeat_timeout=60.0,  # HeartBeatタイムアウトを60秒に延長
            debug_guilds=debug_guilds  # デバッグギルドで即座同期
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
                    timeout=15.0,  # タイムアウト短縮（WebSocket 4006エラー対策）
                    reconnect=False  # 自動再接続無効化（手動制御）
                )
                
                # 接続成功後の安定化待機を短縮
                await asyncio.sleep(0.5)
                
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
        
        # 最終クリーンアップ - グローバル強制リセット
        logger.info("Starting comprehensive global cleanup for ultimate fallback")
        try:
            # 全ギルドの接続状態を強制リセット
            for g in self.guilds:
                if g.voice_client:
                    logger.info(f"Global cleanup: force disconnecting from {g.name}")
                    try:
                        await g.voice_client.disconnect()
                    except:
                        pass
                    g._voice_client = None
            
            # Discord.pyの内部状態強制リセット（あまり推奨されないが必要）
            if hasattr(self, '_voice_clients'):
                logger.info("Force clearing Discord.py internal voice clients")
                self._voice_clients.clear()
            
            await asyncio.sleep(2.0)  # 長めの待機時間
            logger.info("Global cleanup completed")
        except Exception as cleanup_e:
            logger.warning(f"Global cleanup partial failure: {cleanup_e}")
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
        except discord.ClientException as client_e:
            if "Already connected to a voice channel" in str(client_e):
                logger.critical("Ultimate fallback still reports 'Already connected' - this is a Discord.py internal issue")
                logger.info("Attempting to find and return any existing valid connection")
                
                # 最後の手段: 既存の接続を探して返す
                for g in self.guilds:
                    if g.voice_client and g.voice_client.is_connected():
                        logger.info(f"Found existing valid connection in {g.name}: {g.voice_client.channel.name}")
                        if g.voice_client.channel == channel:
                            logger.info("Existing connection is already the target channel - returning it")
                            return g.voice_client
                        else:
                            logger.info(f"Moving existing connection from {g.voice_client.channel.name} to {channel.name}")
                            try:
                                await g.voice_client.move_to(channel)
                                return g.voice_client
                            except Exception as move_e:
                                logger.error(f"Failed to move existing connection: {move_e}")
                
                logger.critical("No valid existing connection found despite 'Already connected' error")
                raise client_e
            else:
                logger.error(f"Ultimate fallback failed with ClientException: {client_e}")
                raise client_e
        except Exception as final_e:
            logger.error(f"Ultimate fallback failed: {final_e}")
            raise final_e
        
    def setup_cogs(self):
        """起動時のCog読み込み（同期処理）- 非同期版に委任"""
        # 非同期版に委任（on_readyで実行される）
        self._cogs_loaded = False
                
    async def load_cogs(self):
        """Cogを読み込む（非同期版）"""
        cogs = [
            "cogs.voice",
            "cogs.tts", 
            "cogs.recording",
            "cogs.message_reader",
            "cogs.dictionary",
            # "cogs.user_settings",  # 一時的に無効化（.disabled ファイルのため）
        ]
        
        for cog in cogs:
            try:
                # 既に読み込まれているかチェック
                if cog in self.extensions:
                    logger.debug(f"Cog {cog} already loaded, skipping")
                    continue
                
                # py-cordでは load_extension は同期メソッド
                self.load_extension(cog)
                logger.info(f"Loaded cog: {cog}")
            except Exception as e:
                logger.error(f"Failed to load cog {cog}: {e}", exc_info=True)
    
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
        total_slash_commands = 0
        for cog_name, cog in self.cogs.items():
            cog_commands = cog.get_commands()
            slash_commands = [cmd for cmd in cog_commands if hasattr(cmd, 'type') and getattr(cmd, 'type', None) == discord.SlashCommandGroup or hasattr(cmd, '_callback')]
            total_slash_commands += len(slash_commands)
            logger.info(f"Cog {cog_name}: {len(cog_commands)} total commands, {len(slash_commands)} slash commands")
            for cmd in cog_commands:
                cmd_type = "slash" if (hasattr(cmd, 'type') and getattr(cmd, 'type', None) == discord.SlashCommandGroup) or hasattr(cmd, '_callback') else "regular"
                logger.info(f"  - {cmd.name} ({cmd_type})")
        
        # py-cordのスラッシュコマンド同期確認
        logger.info(f"py-cord detected - {total_slash_commands} slash commands found")
        logger.info(f"Debug guilds configured: {self.debug_guilds}")
        
        # py-cordでは明示的にスラッシュコマンドを同期する必要がある
        if total_slash_commands > 0 and self.debug_guilds:
            try:
                logger.info("Syncing slash commands to debug guilds...")
                for guild_id in self.debug_guilds:
                    guild = self.get_guild(guild_id)
                    if guild:
                        # py-cordでは引数なしでsync_commands()を呼び、debug_guildsで自動的に各ギルドに同期される
                        await self.sync_commands()
                        logger.info(f"Synced {total_slash_commands} slash commands to debug guilds")
                        break  # 一度だけ実行すればすべてのdebug_guildsに同期される
                    else:
                        logger.warning(f"Guild {guild_id} not found for command sync")
            except Exception as e:
                logger.error(f"Failed to sync slash commands: {e}")
        else:
            logger.info("Slash commands will sync automatically to debug guilds")
        
        # ログクリーンアップタスクの開始
        asyncio.create_task(start_log_cleanup_task(self.config))
        
        # ステータスの設定
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.listening,
                name="自動参加・退出対応 | /join"
            )
        )
        
        # 自動接続機能を強制実行
        await self.force_auto_connect()
    
    async def force_auto_connect(self):
        """自動接続機能を強制実行"""
        try:
            logger.info("Starting forced auto-connect...")
            
            # 自動参加が有効かチェック
            auto_join_enabled = self.config.get("bot", {}).get("auto_join", True)
            if not auto_join_enabled:
                logger.info("Auto-join disabled in config, skipping")
                return
            
            # 少し待機してからギルド情報を取得
            await asyncio.sleep(3)
            
            # 全ギルドの候補チャンネルを調査
            candidates = []
            for guild in self.guilds:
                try:
                    candidate = await self._find_best_channel_in_guild(guild)
                    if candidate:
                        candidates.append(candidate)
                except Exception as e:
                    logger.error(f"Error scanning guild {guild.name}: {e}")
            
            if candidates:
                # ユーザー数で降順ソート
                candidates.sort(key=lambda x: x.get('user_count', 0), reverse=True)
                
                logger.info(f"Found {len(candidates)} candidate channels:")
                for candidate in candidates:
                    logger.info(f"  - {candidate['guild_name']}.{candidate['channel_name']}: {candidate['user_count']}人")
                
                # 最適なチャンネルに接続
                best_candidate = candidates[0]
                try:
                    await self._connect_to_candidate_channel(best_candidate)
                    logger.info(f"Auto-connected to {best_candidate['guild_name']}.{best_candidate['channel_name']}")
                except Exception as e:
                    logger.error(f"Failed to auto-connect: {e}")
            else:
                logger.info("No suitable voice channels found for auto-connect")
                
        except Exception as e:
            logger.error(f"Error in force_auto_connect: {e}")
    
    async def _find_best_channel_in_guild(self, guild):
        """ギルド内で最適なチャンネルを見つける（簡易版）"""
        try:
            # 権限チェック
            bot_member = guild.get_member(self.user.id)
            if not bot_member or not bot_member.guild_permissions.connect:
                return None
            
            # 既に接続している場合をチェック
            for g in self.guilds:
                if g.voice_client and g.voice_client.is_connected():
                    current_channel = g.voice_client.channel
                    members = [m for m in current_channel.members if not m.bot]
                    return {
                        'guild': g,
                        'channel': current_channel,
                        'guild_name': g.name,
                        'channel_name': current_channel.name,
                        'user_count': len(members) + 1000,  # 既存接続は最高優先度
                        'members': members,
                        'already_connected': True
                    }
            
            # 最適なチャンネルを探す
            best_channel = None
            max_users = 0
            
            for channel in guild.voice_channels:
                # チャンネル権限チェック
                channel_perms = channel.permissions_for(bot_member)
                if not channel_perms.connect:
                    continue
                
                # ユーザー数をチェック
                non_bot_members = [m for m in channel.members if not m.bot]
                user_count = len(non_bot_members)
                
                if user_count > 0 and user_count > max_users:
                    max_users = user_count
                    best_channel = {
                        'guild': guild,
                        'channel': channel,
                        'guild_name': guild.name,
                        'channel_name': channel.name,
                        'user_count': user_count,
                        'members': non_bot_members,
                        'already_connected': False
                    }
            
            return best_channel
            
        except Exception as e:
            logger.error(f"Error scanning guild {guild.name}: {e}")
            return None
    
    async def _connect_to_candidate_channel(self, candidate):
        """候補チャンネルに接続（簡易版）"""
        if candidate['already_connected']:
            logger.info(f"Already connected to {candidate['channel_name']}")
            return True
        
        # 新規接続
        await self.connect_to_voice(candidate['channel'])
        logger.info(f"Connected to {candidate['guild_name']}.{candidate['channel_name']}")
        return True

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