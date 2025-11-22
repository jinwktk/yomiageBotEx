#!/usr/bin/env python3
"""
yomiageBotEx - Discord読み上げボット
"""

import os
import sys
import asyncio
import logging
from pathlib import Path
import signal
import time
import threading
import atexit
import gc
import io
import wave
from contextlib import suppress
from typing import Optional

import discord
from discord import opus as discord_opus
try:
    from nacl.exceptions import CryptoError
except Exception:  # pragma: no cover
    CryptoError = None
import yaml
from dotenv import load_dotenv

from utils.logger import setup_logging, start_log_cleanup_task
from utils.hot_reload import HotReloadManager
from utils.dictionary import DictionaryManager
    
# プロセス重複防止機能（CLAUDE.mdルール遵守）
LOCK_FILE = "bot.lock"

def cleanup_lock_file():
    """ロックファイルのクリーンアップ"""
    try:
        if os.path.exists(LOCK_FILE):
            os.unlink(LOCK_FILE)
            print(f"Lock file {LOCK_FILE} removed")
    except Exception as e:
        print(f"Warning: Could not remove lock file: {e}")

def is_process_running(pid):
    """指定されたPIDのプロセスが実行中かチェック"""
    try:
        # Windows
        if sys.platform == "win32":
            import subprocess
            result = subprocess.run(['tasklist', '/FI', f'PID eq {pid}'], 
                                  capture_output=True, text=True)
            return str(pid) in result.stdout
        # Unix/Linux
        else:
            os.kill(int(pid), 0)
            return True
    except (OSError, ValueError, subprocess.SubprocessError):
        return False

def check_single_process():
    """単一プロセス実行を確認"""
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, 'r') as f:
                existing_pid = f.read().strip()
            
            # PIDが実際に生きているかチェック
            if is_process_running(existing_pid):
                print(f"Bot is already running (PID: {existing_pid})!")
                print("Multiple process execution is prohibited by CLAUDE.md rules.")
                sys.exit(1)
            else:
                print(f"Stale lock file found (PID {existing_pid} not running), removing...")
                cleanup_lock_file()
                
        except Exception as e:
            print(f"Lock file exists but unreadable: {e}")
            # 壊れたロックファイルを削除
            cleanup_lock_file()
    
    # ロックファイル作成
    try:
        with open(LOCK_FILE, 'w') as f:
            f.write(str(os.getpid()))
        print(f"Process lock created: {LOCK_FILE} (PID: {os.getpid()})")
        
        # 終了時のクリーンアップを登録
        atexit.register(cleanup_lock_file)
        
    except Exception as e:
        print(f"Failed to create lock file: {e}")
        sys.exit(1)

# 単一プロセス実行チェック実行
check_single_process()

try:
    from utils.real_audio_recorder import RealEnhancedVoiceClient as EnhancedVoiceClient
    print("[OK] Using py-cord real audio recording")
    VOICE_CLIENT_TYPE = "py-cord"
except Exception as e:
    print(f"[ERROR] Could not import RealEnhancedVoiceClient: {e}")
    print("   Please ensure py-cord[voice] and required dependencies are installed")
    sys.exit(1)

def patch_opus_decode_manager():
    """Opusデコーダーのエラーハンドリングを強化."""
    if getattr(discord_opus.DecodeManager, "_yomiage_patch_applied", False):
        return

    def _describe_ssrc_context(voice_client, ssrc):
        if ssrc is None:
            return "unknown source"
        if voice_client is None:
            return f"SSRC={ssrc}"
        parts = [f"SSRC={ssrc}"]
        try:
            ws = getattr(voice_client, "ws", None)
            ssrc_map = getattr(ws, "ssrc_map", {}) if ws else {}
            info = ssrc_map.get(ssrc)
            if info is None:
                try:
                    info = ssrc_map.get(int(ssrc))
                except Exception:
                    info = None
            user_id = info.get("user_id") if isinstance(info, dict) else None
            if user_id:
                guild = getattr(voice_client, "guild", None)
                member = guild.get_member(user_id) if guild else None
                if member:
                    parts.append(f"user={member.display_name}({user_id})")
                else:
                    parts.append(f"user_id={user_id}")
            channel = getattr(getattr(voice_client, "channel", None), "name", None)
            if channel:
                parts.append(f"channel={channel}")
            guild = getattr(voice_client, "guild", None)
            if guild:
                parts.append(f"guild={guild.name}({guild.id})")
        except Exception:
            parts.append("context=unavailable")
        return " ".join(parts)

    def patched_run(self):
        opus_logger = logging.getLogger("discord.opus")
        if not hasattr(self, "_last_opus_error"):
            self._last_opus_error = {}
        if not hasattr(self, "_error_state"):
            self._error_state = {}
        while not self._end_thread.is_set():
            try:
                data = self.decode_queue.pop(0)
            except IndexError:
                time.sleep(0.001)
                continue

            if not data.decrypted_data:
                continue

            try:
                decoder = self.get_decoder(getattr(data, "ssrc", None))
                data.decoded_data = decoder.decode(data.decrypted_data)
            except discord_opus.OpusError as err:
                ssrc = getattr(data, "ssrc", "unknown")
                ssrc_context = _describe_ssrc_context(getattr(self, "client", None), ssrc)
                state = self._error_state.setdefault(ssrc, {"count": 0, "blocked_until": 0.0})
                now = time.monotonic()
                if now >= state["blocked_until"]:
                    state["count"] = 0
                self.decoder.pop(ssrc, None)
                now = time.monotonic()
                last_logged = self._last_opus_error.get(ssrc, 0)
                state["count"] += 1
                if state["count"] > 5:
                    state["blocked_until"] = now + 30.0
                    state["count"] = 0
                    opus_logger.warning(
                        "Opus decode repeatedly failed (%s). Muting errors for 30s.",
                        ssrc_context,
                    )
                elif now - last_logged >= 5.0:
                    opus_logger.warning(
                        "Opus decode error (%s): %s. Decoder reset.",
                        ssrc_context,
                        err,
                    )
                    self._last_opus_error[ssrc] = now
                continue
            else:
                ssrc = getattr(data, "ssrc", None)
                if ssrc in getattr(self, "_error_state", {}):
                    self._error_state[ssrc]["count"] = 0

            self.client.recv_decoded_audio(data)

    discord_opus.DecodeManager.run = patched_run
    discord_opus.DecodeManager._yomiage_patch_applied = True
    logging.getLogger(__name__).info("Applied YomiageBot Opus decoder patch for improved stability.")
    opus_logger = logging.getLogger("discord.opus")
    opus_logger.setLevel(logging.WARNING)
    opus_logger.propagate = False


patch_opus_decode_manager()


def patch_voice_decrypt_errors():
    """Voice受信の復号エラーを抑制してフレームをスキップ"""
    if not CryptoError:
        logging.getLogger(__name__).warning("PyNaCl CryptoError unavailable; decrypt patch skipped")
        return

    VoiceClient = discord.voice_client.VoiceClient
    if getattr(VoiceClient, "_yomiage_decrypt_patch", False):
        return

    original_unpack_audio = VoiceClient.unpack_audio
    vc_logger = logging.getLogger("discord.voice_client")

    def patched_unpack_audio(self, data):
        try:
            return original_unpack_audio(self, data)
        except CryptoError as err:
            guild = getattr(getattr(self, "guild", None), "name", "unknown")
            channel = getattr(getattr(self, "channel", None), "name", "unknown")
            vc_logger.warning(
                "Voice decrypt error skipped (guild=%s channel=%s): %s",
                guild,
                channel,
                err,
            )
            return None

    VoiceClient.unpack_audio = patched_unpack_audio
    VoiceClient._yomiage_decrypt_patch = True
    vc_logger.info("Applied decrypt error patch to skip corrupted frames")


patch_voice_decrypt_errors()


def patch_wave_sink():
    """WaveSinkがPCMデータを失う問題を回避"""
    try:
        from discord.sinks.wave import WaveSink
    except Exception as exc:
        print(f"[WARN] Failed to import WaveSink for patching: {exc}")
        return

    if getattr(WaveSink, "_yomiage_patch_applied", False):
        return

    original_format_audio = WaveSink.format_audio

    def patched_format_audio(self, audio):
        try:
            audio.file.seek(0)
            pcm_data = audio.file.read()
            if not pcm_data:
                return original_format_audio(self, audio)

            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, "wb") as wav_file:
                wav_file.setnchannels(self.vc.decoder.CHANNELS)
                wav_file.setsampwidth(self.vc.decoder.SAMPLE_SIZE // self.vc.decoder.CHANNELS)
                wav_file.setframerate(self.vc.decoder.SAMPLING_RATE)
                wav_file.writeframes(pcm_data)

            audio.file = io.BytesIO(wav_buffer.getvalue())
            audio.file.seek(0)
            audio.on_format(self.encoding)
        except Exception as exc:
            print(f"[WARN] WaveSink patch failed, falling back to original: {exc}")
            original_format_audio(self, audio)

    WaveSink.format_audio = patched_format_audio
    WaveSink._yomiage_patch_applied = True
    print("[INFO] Applied WaveSink patch to preserve PCM data.")


patch_wave_sink()

load_dotenv()
def load_config():
    """設定ファイルを読み込む"""
    config_path = Path("config.yaml")
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    else:
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

config = load_config()
logger = setup_logging(config)

class YomiageBot(discord.Bot):
    """読み上げボットのメインクラス"""
    
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True
        intents.guilds = True
        intents.members = True
        
        super().__init__(intents=intents)
        
        self.config = config
        self.dictionary_manager = DictionaryManager(self.config)
        self._cogs_loaded = False
        self._refresh_task: Optional[asyncio.Task] = None

        dev_config = self.config.get("development", {})
        hot_reload_config = dev_config.get("hot_reload", {}) if isinstance(dev_config, dict) else {}
        self._hot_reload_enabled = bool(hot_reload_config.get("enabled", False))
        self._hot_reload_interval = float(hot_reload_config.get("poll_interval", 1.0))
        self.hot_reload_manager: Optional[HotReloadManager] = HotReloadManager() if self._hot_reload_enabled else None
        self._hot_reload_task: Optional[asyncio.Task] = None

        self.setup_cogs()

    async def _refresh_resources(self):
        """長時間稼働によるリソース劣化をリフレッシュ"""
        logger.info("Scheduled refresh: starting resource refresh cycle")

        # TTS マネージャーのセッションを更新
        async def refresh_tts_manager(cog_name: str):
            cog = self.get_cog(cog_name)
            if cog and hasattr(cog, "tts_manager"):
                tts_manager = cog.tts_manager
                try:
                    await tts_manager.cleanup()
                    await tts_manager.cache.cleanup_if_needed()
                    await tts_manager.init_session()
                    logger.info("Scheduled refresh: %s TTS session refreshed", cog_name)
                except Exception as exc:
                    logger.warning("Scheduled refresh: failed to refresh %s TTS manager: %s", cog_name, exc)

        await refresh_tts_manager("TTSCog")
        await refresh_tts_manager("MessageReaderCog")

        # メモリクリーニング
        collected = gc.collect()
        logger.debug("Scheduled refresh: garbage collector reclaimed %s objects", collected)

    async def _periodic_refresh(self):
        """1時間ごとの自動リフレッシュタスク"""
        await self.wait_until_ready()
        logger.info("Scheduled refresh task started")
        try:
            while not self.is_closed():
                await asyncio.sleep(3600)  # 1時間
                try:
                    await self._refresh_resources()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.error("Scheduled refresh: refresh step failed: %s", exc, exc_info=True)
        except asyncio.CancelledError:
            logger.info("Scheduled refresh task cancelled")
            raise
        finally:
            logger.info("Scheduled refresh task terminated")

    async def _hot_reload_loop(self):
        await self.wait_until_ready()
        logger.info("Hot reload watcher started")
        try:
            while not self.is_closed():
                await asyncio.sleep(self._hot_reload_interval)
                if not self.hot_reload_manager:
                    continue
                for extension in self.hot_reload_manager.collect_changed_extensions():
                    try:
                        logger.info("Hot reloading extension: %s", extension)
                        self.reload_extension(extension)
                    except Exception as exc:
                        logger.error("Hot reload failed for %s: %s", extension, exc, exc_info=True)
        except asyncio.CancelledError:
            logger.info("Hot reload watcher cancelled")
            raise

    async def close(self):
        if self._hot_reload_task:
            self._hot_reload_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._hot_reload_task
            self._hot_reload_task = None
        await super().close()
    
    async def connect_voice_safely(self, channel):
        """安全な音声接続（WebSocketエラー対応強化版）"""
        max_retries = 3
        
        if await self._cleanup_existing_connection(channel):
            await asyncio.sleep(2.0)
        for attempt in range(max_retries):
            try:
                logger.info(f"Voice connection attempt {attempt + 1}/{max_retries} to {channel.name}")
                vc = await self._attempt_voice_connection(channel)
                
                if await self._verify_connection_stability(vc, channel):
                    await self._configure_voice_state(channel)
                    logger.info(f"Voice connection successful to {channel.name}")
                    return vc
                else:
                    if vc:
                        await self._disconnect_safely(vc)
                    raise Exception("Connection not stable")
                    
            except Exception as e:
                logger.error(f"Voice connection attempt {attempt + 1} failed: {e}")
                
                if attempt < max_retries - 1:
                    retry_delay = 3.0 * (attempt + 1)
                    logger.info(f"Retrying connection after {retry_delay}s...")
                    await asyncio.sleep(retry_delay)
                else:
                    logger.error("All connection attempts failed, trying basic connect")
                    try:
                        return await channel.connect()
                    except Exception as e2:
                        logger.error(f"Fallback connection also failed: {e2}")
                        raise

    async def _cleanup_existing_connection(self, channel):
        """既存の音声接続をクリーンアップ"""
        if not channel.guild.voice_client:
            return False
            
        try:
            logger.info(f"Disconnecting existing voice client from {channel.guild.voice_client.channel.name if channel.guild.voice_client.channel else 'unknown'}")
            await channel.guild.voice_client.disconnect()
            logger.info("Existing voice client disconnected successfully")
        except Exception as e:
            logger.warning(f"Failed to disconnect existing voice client: {e}")
        finally:
            # 強制的にリセット
            try:
                channel.guild._voice_client = None
            except Exception:
                pass
        return True

    async def _attempt_voice_connection(self, channel):
        """音声接続を試行"""
        vc = await channel.connect(timeout=30.0, reconnect=True)
        await asyncio.sleep(2.0)
        return vc

    async def _verify_connection_stability(self, vc, channel):
        """接続の安定性を確認"""
        if not vc or not hasattr(vc, 'is_connected') or not vc.is_connected():
            return False
            
        if hasattr(vc, 'ws') and vc.ws and hasattr(vc.ws, 'open'):
            if not vc.ws.open:
                logger.warning("WebSocket not open")
                await asyncio.sleep(1.0)
                if not (hasattr(vc.ws, 'open') and vc.ws.open):
                    return False
        return vc.is_connected()

    def _should_listen_to_channel_audio(self) -> bool:
        """録音やリレー機能のためにチャンネル音声を受信する必要があるか"""
        recording_enabled = self.config.get("recording", {}).get("enabled", False)
        relay_enabled = self.config.get("audio_relay", {}).get("enabled", False)
        return recording_enabled or relay_enabled

    async def _configure_voice_state(self, channel):
        """音声状態を設定"""
        try:
            listen_required = self._should_listen_to_channel_audio()
            await channel.guild.change_voice_state(
                channel=channel,
                self_deaf=not listen_required,
                self_mute=False
            )
            logger.info("Voice state (self_deaf=%s) set successfully", not listen_required)
        except Exception as e:
            logger.warning(f"Failed to set voice state: {e}")

    async def _disconnect_safely(self, vc):
        """安全に切断"""
        try:
            await vc.disconnect()
        except Exception:
            pass
        
    def load_extension(self, name: str, *, package: Optional[str] = None):
        super().load_extension(name, package=package)
        self._register_hot_reload_path(name)

    def reload_extension(self, name: str, *, package: Optional[str] = None):
        super().reload_extension(name, package=package)
        self._register_hot_reload_path(name)

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
            "cogs.relay",
            "cogs.admin",
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

    def _register_hot_reload_path(self, extension: str) -> None:
        if not self.hot_reload_manager:
            return
        module = sys.modules.get(extension)
        module_file = getattr(module, "__file__", None) if module else None
        if not module_file:
            return
        self.hot_reload_manager.register_extension(extension, Path(module_file))

    async def setup_hook(self) -> None:
        if self._hot_reload_enabled and not self._hot_reload_task:
            self._hot_reload_task = asyncio.create_task(self._hot_reload_loop())

    async def on_ready(self):
        """Bot準備完了時のイベント"""
        logger.info(f"Bot is ready! Logged in as {self.user} (ID: {self.user.id})")
        logger.info(f"Connected to {len(self.guilds)} guild(s)")
        logger.info(f"Voice client type: {VOICE_CLIENT_TYPE}")

        
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
        
        # RecordingCallbackManagerの初期化
        try:
            from utils.recording_callback_manager import recording_callback_manager
            await recording_callback_manager.initialize()
            logger.info("RecordingCallbackManager initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize RecordingCallbackManager: {e}")
        
        # ReplayBufferManagerの初期化
        try:
            from utils.replay_buffer_manager import initialize_replay_buffer_manager
            initialize_replay_buffer_manager(self.config)
            logger.info("ReplayBufferManager initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize ReplayBufferManager: {e}")
        
        # ログクリーンアップタスクの開始
        asyncio.create_task(start_log_cleanup_task(self.config))
        
        # ステータスの設定
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.listening,
                name="自動参加・退出対応 | /join"
            )
        )

        if self._refresh_task is None or self._refresh_task.done():
            self._refresh_task = asyncio.create_task(self._periodic_refresh())
    
    async def on_error(self, event_method: str, *args, **kwargs):
        """エラーハンドリング"""
        logger.error(f"Error in {event_method}", exc_info=True)
    
    async def on_application_command_error(self, ctx, error):
        """スラッシュコマンドのエラーハンドリング"""
        # HTTPException 40060 (Interaction already acknowledged) は警告レベルでログ
        if hasattr(error, 'status') and error.status == 400 and "40060" in str(error):
            logger.warning(f"Interaction already acknowledged in {ctx.command.name}: {error}")
        else:
            logger.error(f"Application command error in {ctx.command.name}: {error}", exc_info=True)
        
        # ユーザーへのエラー通知（重複応答を防ぐ）
        try:
            # HTTPException 40060 の場合は応答を試行しない
            if hasattr(error, 'status') and error.status == 400 and "40060" in str(error):
                logger.debug("Skipping error response due to interaction already acknowledged")
                return
                
            if ctx.response.is_done():
                # フォローアップメッセージも同様にチェック
                await ctx.followup.send(f"❌ コマンドの実行中にエラーが発生しました: {str(error)}", ephemeral=True)
            else:
                await ctx.respond(f"❌ コマンドの実行中にエラーが発生しました: {str(error)}", ephemeral=True)
        except discord.HTTPException as http_error:
            if http_error.status == 400 and "40060" in str(http_error):
                logger.debug("Failed to send error response: interaction already acknowledged")
            else:
                logger.error(f"Failed to send error message to user: {http_error}")
        except Exception as e:
            logger.error(f"Failed to send error message to user: {e}")
    
    async def on_command_error(self, ctx, error):
        """通常コマンドのエラーハンドリング"""
        logger.error(f"Command error in {ctx.command}: {error}", exc_info=True)
    
    async def close(self):
        """Bot終了時のクリーンアップ"""
        logger.info("Bot is shutting down, cleaning up resources...")

        if self._refresh_task:
            self._refresh_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._refresh_task
            self._refresh_task = None

        # 音声接続のクリーンアップ
        try:
            for vc in self.voice_clients:
                if vc.is_connected():
                    await vc.disconnect()
                    logger.info(f"Disconnected voice client from {vc.channel.name}")
        except Exception as e:
            logger.error(f"Failed to cleanup voice clients: {e}")
        
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
        
        # RecordingCallbackManagerのクリーンアップ
        try:
            from utils.recording_callback_manager import recording_callback_manager
            await recording_callback_manager.shutdown()
            logger.info("RecordingCallbackManager shutdown completed")
        except Exception as e:
            logger.error(f"Failed to cleanup RecordingCallbackManager: {e}")
        
        # ReplayBufferManagerのクリーンアップ
        try:
            from utils.replay_buffer_manager import replay_buffer_manager
            if replay_buffer_manager:
                await replay_buffer_manager.cleanup()
                logger.info("ReplayBufferManager cleanup completed")
        except Exception as e:
            logger.error(f"Failed to cleanup ReplayBufferManager: {e}")
        
        # HTTPセッションのクリーンアップ
        try:
            # 全体的なHTTPセッション情報をクリア（可能であれば）
            if hasattr(self, '_http') and self._http:
                if hasattr(self._http, '__aenter__'):
                    # aiohttp session があれば閉じる
                    await self._http._HTTPClient__session.close()
                    logger.info("HTTP session cleanup completed")
        except Exception as e:
            logger.error(f"Failed to cleanup HTTP sessions: {e}")
        
        logger.info("All cleanup completed")
        
        # 親クラスのクリーンアップを呼び出し
        await super().close()
    
    async def connect_to_voice(self, channel: discord.VoiceChannel) -> discord.VoiceClient:
        """カスタムVoiceClientで接続"""
        # 既存の接続を確認・クリーンアップ
        if channel.guild.voice_client:
            try:
                if channel.guild.voice_client.is_connected():
                    if channel.guild.voice_client.channel == channel:
                        # 実際にDiscordで参加しているか再検証
                        try:
                            # 音声状態を確認して実際の接続状態をテスト
                            members_in_channel = channel.members
                            bot_in_channel = any(member.id == channel.guild.me.id for member in members_in_channel)
                            if bot_in_channel:
                                logger.info(f"Already connected to {channel.name}, reusing connection")
                                return channel.guild.voice_client
                            else:
                                logger.warning(f"Bot not actually in {channel.name}, resetting connection")
                        except Exception:
                            logger.warning("Failed to verify actual channel membership, resetting connection")
                        # 状態不整合の場合は強制リセット
                        await channel.guild.voice_client.disconnect()
                        await asyncio.sleep(1.0)
                    else:
                        # 他のチャンネルに接続中の場合は切断
                        logger.info(f"Disconnecting from {channel.guild.voice_client.channel.name}")
                        await channel.guild.voice_client.disconnect()
                        await asyncio.sleep(1.0)
                else:
                    # 接続状態が不整合の場合はクリーンアップ
                    logger.warning("Voice client exists but not connected, cleaning up")
                    await channel.guild.voice_client.disconnect()
                    await asyncio.sleep(1.0)
            except Exception as cleanup_error:
                logger.error(f"Failed to cleanup existing voice connection: {cleanup_error}")
            finally:
                # 強制的に状態をリセット
                try:
                    channel.guild._voice_client = None
                    logger.info("Forced voice client state reset")
                except Exception:
                    pass
        
        # 安全な接続を試行
        try:
            return await self.connect_voice_safely(channel)
        except Exception as e:
            logger.error(f"Safe connection failed, trying EnhancedVoiceClient: {e}")
            # フォールバック：EnhancedVoiceClientを使用
            try:
                return await channel.connect(cls=EnhancedVoiceClient)
            except discord.errors.ClientException as client_error:
                if "Already connected" in str(client_error):
                    # 最終的に重複接続エラーが発生した場合は既存の接続を返す
                    logger.warning("Final connection attempt failed due to duplicate connection, returning existing client")
                    if channel.guild.voice_client:
                        return channel.guild.voice_client
                raise client_error
    
bot = YomiageBot()
bot.setup_cogs()

async def shutdown_handler():
    """シャットダウン時のクリーンアップハンドラ"""
    logger.info("Shutdown signal received, cleaning up...")
    cleanup_lock_file()  # ロックファイルを削除
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
    pst_protection_enabled = os.getenv("ENABLE_PST", "false").lower() not in {"0", "false", "off", "no"}
    protection_block_seconds = 5.0
    grace_interval = 30.0  # 秒
    last_sigint_time = 0.0
    protection_block_until = 0.0

    def signal_handler(signum, frame):
        nonlocal last_sigint_time, protection_block_until
        logger.info(f"Received signal {signum}, initiating shutdown...")
        if signum == signal.SIGINT and pst_protection_enabled:
            now = time.monotonic()
            if now < protection_block_until:
                logger.info("SIGINT received during protection window. Ignoring.")
                return
            if now - last_sigint_time < grace_interval:
                logger.warning("SIGINT received again before grace interval elapsed. Proceeding with shutdown.")
            else:
                logger.warning("SIGINT received - possibly from PST.exe. Checking source...")
                logger.info(f"Protected mode: Ignoring external termination signal for {protection_block_seconds:.0f} seconds...")
                last_sigint_time = now
                protection_block_until = now + protection_block_seconds

                def _end_protection():
                    logger.info("Protection period ended. Continuing normal operation...")

                threading.Timer(protection_block_seconds, _end_protection).start()
                return
        
        cleanup_lock_file()  # シグナル受信時にもロックファイルを削除
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
        cleanup_lock_file()  # Ctrl+C時にもロックファイルを削除
        # シャットダウン処理を実行
        asyncio.run(shutdown_handler())
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        cleanup_lock_file()  # 例外時にもロックファイルを削除
        # 例外発生時もクリーンアップを実行
        try:
            asyncio.run(shutdown_handler())
        except:
            pass
        sys.exit(1)
    finally:
        # 最終的なクリーンアップ（念のため）
        cleanup_lock_file()

if __name__ == "__main__":
    main()
