"""
スムーズ音声リレーシステム
連続ストリーミングで途切れない音声転送を実現
"""

import asyncio
import logging
import time
import tempfile
import os
import io
from typing import Dict, Optional, Set, Any
from dataclasses import dataclass
from enum import Enum

import discord
from discord.sinks import WaveSink

# RecordingCallbackManagerの安全なインポート
try:
    from .recording_callback_manager import recording_callback_manager
    RECORDING_CALLBACK_AVAILABLE = True
except ImportError:
    recording_callback_manager = None
    RECORDING_CALLBACK_AVAILABLE = False


class RelayStatus(Enum):
    """リレーセッションのステータス"""
    STARTING = "starting"
    ACTIVE = "active"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class RelaySession:
    """リレーセッション情報"""
    session_id: str
    source_guild_id: int
    source_channel_id: int
    target_guild_id: int
    target_channel_id: int
    status: RelayStatus
    created_at: float
    last_activity: float


class SmoothAudioRelay:
    """スムーズ音声リレーシステム"""
    
    def __init__(self, bot: discord.Bot, config: Dict[str, Any], logger: logging.Logger):
        self.bot = bot
        self.config = config.get("audio_relay", {})
        self.logger = logger
        self.active_sessions: Dict[str, RelaySession] = {}
        self.enabled = self.config.get("enabled", False)
        
        # リレータスク管理
        self.relay_tasks: Dict[str, asyncio.Task] = {}
        self.audio_streams: Dict[str, io.BytesIO] = {}
        
        # 最適化された設定
        self.recording_duration = 5.0  # 5秒サイクル（安定性重視）
        self.volume = self.config.get("volume", 0.8)
        self.max_sessions = self.config.get("max_sessions", 10)
        self.max_duration_hours = self.config.get("max_duration_hours", 1)
        
        # RecordingCallbackManager連携設定
        self.recording_callback_enabled = RECORDING_CALLBACK_AVAILABLE and self.enabled
        
        self.logger.info(f"Smooth Audio Relay initialized - {'enabled' if self.enabled else 'disabled'}")
        if self.recording_callback_enabled:
            self.logger.info("RecordingCallbackManager integration enabled")

    async def start_relay_session(
        self,
        source_guild_id: int,
        source_channel_id: int,
        target_guild_id: int,
        target_channel_id: int
    ) -> str:
        """スムーズな音声リレーセッションの開始"""
        
        if not self.enabled:
            raise ValueError("Audio relay is disabled")
        
        if len(self.active_sessions) >= self.max_sessions:
            raise ValueError(f"Maximum sessions reached ({self.max_sessions})")
        
        session_id = f"smooth_relay_{source_guild_id}_{target_guild_id}_{int(time.time())}"
        
        try:
            # セッション作成
            session = RelaySession(
                session_id=session_id,
                source_guild_id=source_guild_id,
                source_channel_id=source_channel_id,
                target_guild_id=target_guild_id,
                target_channel_id=target_channel_id,
                status=RelayStatus.STARTING,
                created_at=time.time(),
                last_activity=time.time()
            )
            
            self.active_sessions[session_id] = session
            
            # 音声接続のセットアップ
            source_guild = self.bot.get_guild(source_guild_id)
            target_guild = self.bot.get_guild(target_guild_id)
            source_channel = source_guild.get_channel(source_channel_id)
            target_channel = target_guild.get_channel(target_channel_id)
            
            source_voice_client, target_voice_client = await self._setup_voice_connections(
                source_guild, source_channel, target_guild, target_channel
            )
            
            # RecordingCallbackManagerにGuildを登録
            if self.recording_callback_enabled and recording_callback_manager:
                try:
                    await recording_callback_manager.register_guild(source_guild_id)
                    self.logger.info(f"Registered Guild {source_guild_id} for recording callback")
                except Exception as e:
                    self.logger.warning(f"Failed to register Guild {source_guild_id} for recording callback: {e}")
            
            # スムーズリレータスクを開始
            relay_task = asyncio.create_task(
                self._smooth_relay_loop(session, source_voice_client, target_voice_client)
            )
            self.relay_tasks[session_id] = relay_task
            
            session.status = RelayStatus.ACTIVE
            
            self.logger.info(f"🎵 SMOOTH RELAY ACTIVE: {source_channel.name} → {target_channel.name}")
            return session_id
            
        except Exception as e:
            self.logger.error(f"Failed to start smooth relay session {session_id}: {e}")
            if session_id in self.active_sessions:
                self.active_sessions[session_id].status = RelayStatus.ERROR
            await self._cleanup_session_resources(session_id)
            raise

    async def _setup_voice_connections(
        self,
        source_guild: discord.Guild,
        source_channel: discord.VoiceChannel,
        target_guild: discord.Guild,
        target_channel: discord.VoiceChannel
    ) -> tuple[discord.VoiceClient, discord.VoiceClient]:
        """音声接続のセットアップ"""
        
        # ソースチャンネル接続
        source_voice_client = source_guild.voice_client
        if not source_voice_client or not source_voice_client.is_connected():
            source_voice_client = await source_channel.connect()
            self.logger.info(f"Connected to source channel: {source_channel.name}")
        elif source_voice_client.channel.id != source_channel.id:
            await source_voice_client.move_to(source_channel)
            self.logger.info(f"Moved to source channel: {source_channel.name}")
        
        # ターゲットチャンネル接続
        target_voice_client = target_guild.voice_client
        if not target_voice_client or not target_voice_client.is_connected():
            target_voice_client = await target_channel.connect()
            self.logger.info(f"Connected to target channel: {target_channel.name}")
        elif target_voice_client.channel.id != target_channel.id:
            await target_voice_client.move_to(target_channel)
            self.logger.info(f"Moved to target channel: {target_channel.name}")
        
        return source_voice_client, target_voice_client

    async def _smooth_relay_loop(
        self,
        session: RelaySession,
        source_voice_client: discord.VoiceClient,
        target_voice_client: discord.VoiceClient
    ):
        """スムーズな音声リレーループ"""
        try:
            self.logger.info(f"Starting smooth relay loop for session {session.session_id}")
            
            # 連続音声ストリームの初期化
            self.audio_streams[session.session_id] = io.BytesIO()
            
            # メインリレーループ
            while session.status == RelayStatus.ACTIVE:
                try:
                    # **両方のVoiceClientが接続中かチェック（ユーザーリクエスト対応）**
                    if not source_voice_client or not source_voice_client.is_connected():
                        self.logger.warning(f"Source voice client not connected - stopping relay session {session.session_id}")
                        break
                    
                    if not target_voice_client or not target_voice_client.is_connected():
                        self.logger.warning(f"Target voice client not connected - stopping relay session {session.session_id}")
                        break
                    
                    # WaveSinkで高品質録音
                    sink = discord.sinks.WaveSink()
                    source_voice_client.start_recording(sink, self._recording_finished_callback)
                    
                    # 録音期間待機（長めで安定）
                    await asyncio.sleep(self.recording_duration)
                    
                    # 録音停止前に再度接続確認
                    if not source_voice_client.is_connected():
                        self.logger.warning(f"Source voice client disconnected during recording")
                        break
                    
                    # 録音停止
                    source_voice_client.stop_recording()
                    await asyncio.sleep(0.2)  # 安定化待機
                    
                    # スムーズな音声処理と再生
                    await self._process_smooth_audio(sink, target_voice_client, session)
                    
                    session.last_activity = time.time()
                    
                except Exception as e:
                    if "Not connected to voice channel" in str(e):
                        self.logger.warning(f"Voice connection lost - stopping relay session {session.session_id}")
                        break
                    else:
                        self.logger.warning(f"Error in smooth relay cycle: {e}")
                        await asyncio.sleep(2.0)  # エラー時の長め待機
                    
        except asyncio.CancelledError:
            self.logger.info(f"Smooth relay loop cancelled for session {session.session_id}")
            raise
        except Exception as e:
            self.logger.error(f"Error in smooth relay loop for session {session.session_id}: {e}")
            session.status = RelayStatus.ERROR
        finally:
            # クリーンアップ
            await self._cleanup_smooth_session(session.session_id, source_voice_client)

    async def _process_smooth_audio(
        self, 
        sink: discord.sinks.WaveSink, 
        target_voice_client: discord.VoiceClient,
        session: RelaySession
    ):
        """スムーズな音声処理"""
        try:
            if not sink.audio_data:
                return
            
            # RecordingCallbackManagerに音声データを転送（個別ユーザーごと）
            if self.recording_callback_enabled and recording_callback_manager:
                try:
                    for user_id, audio in sink.audio_data.items():
                        if audio and audio.file:
                            audio.file.seek(0)
                            audio_bytes = audio.file.read()
                            if audio_bytes and len(audio_bytes) > 44:  # WAVヘッダー以上
                                await recording_callback_manager.process_audio_data(
                                    guild_id=session.source_guild_id,
                                    user_id=user_id,
                                    audio_data=audio_bytes
                                )
                                self.logger.debug(f"Forwarded audio data to RecordingCallbackManager: user {user_id}, size {len(audio_bytes)}")
                except Exception as e:
                    self.logger.warning(f"Failed to forward audio data to RecordingCallbackManager: {e}")
            
            # 全ユーザーの音声をマージ
            merged_audio = await self._merge_all_audio(sink.audio_data)
            
            if not merged_audio or len(merged_audio) < 1000:  # 最小サイズチェック
                return
            
            # 音量調整
            adjusted_audio = self._adjust_volume_smooth(merged_audio, self.volume)
            
            # 連続再生（重複なし）
            await self._play_smooth_audio(target_voice_client, adjusted_audio, session.session_id)
            
        except Exception as e:
            self.logger.warning(f"Error processing smooth audio: {e}")

    async def _merge_all_audio(self, audio_data: Dict) -> bytes:
        """全ユーザーの音声をマージ"""
        try:
            if not audio_data:
                return b''
            
            # 最初の有効なユーザーの音声を基準とする
            for user_id, audio in audio_data.items():
                if audio and audio.file:
                    audio.file.seek(0)  # ファイルポインタを先頭に
                    audio_bytes = audio.file.read()
                    if audio_bytes and len(audio_bytes) > 44:  # WAVヘッダー以上
                        self.logger.debug(f"Using audio from user {user_id}: {len(audio_bytes)/1024:.1f}KB")
                        return audio_bytes
            
            return b''
            
        except Exception as e:
            self.logger.warning(f"Error merging audio: {e}")
            return b''

    def _adjust_volume_smooth(self, audio_data: bytes, volume: float) -> bytes:
        """スムーズな音量調整"""
        try:
            if len(audio_data) <= 44:  # WAVヘッダーのみ
                return audio_data
            
            import array
            # 16-bit signed PCMとして処理
            audio_array = array.array('h', audio_data[44:])  # WAVヘッダーをスキップ
            
            # 音量調整
            for i in range(len(audio_array)):
                audio_array[i] = int(audio_array[i] * volume)
                # ソフトクリッピング
                if audio_array[i] > 32000:
                    audio_array[i] = 32000
                elif audio_array[i] < -32000:
                    audio_array[i] = -32000
            
            # WAVヘッダーを追加して返す
            return audio_data[:44] + audio_array.tobytes()
            
        except Exception as e:
            self.logger.warning(f"Volume adjustment failed: {e}")
            return audio_data

    async def _play_smooth_audio(
        self, 
        target_voice_client: discord.VoiceClient, 
        audio_data: bytes,
        session_id: str
    ):
        """スムーズな音声再生 + RecordingCallbackManagerへの音声データ送信"""
        try:
            # **両方のVoiceClientが接続中かチェック（ユーザーリクエスト対応）**
            if not target_voice_client or not target_voice_client.is_connected():
                self.logger.debug(f"Target voice client not connected - skipping audio play for session {session_id}")
                return
            
            # セッション情報を取得してソースVCの接続もチェック
            session = next((s for s in self.active_sessions.values() if s.session_id == session_id), None)
            if session:
                source_voice_client = self.bot.get_guild(session.source_guild_id).voice_client if self.bot.get_guild(session.source_guild_id) else None
                if not source_voice_client or not source_voice_client.is_connected():
                    self.logger.debug(f"Source voice client not connected - skipping audio play for session {session_id}")
                    return
            
            # 前の再生の完了を待つ（重複防止）
            if target_voice_client.is_playing():
                return  # スキップして次のサイクルを待つ
            
            # 🚀 BREAKTHROUGH: RecordingCallbackManagerに音声データを直接送信（WaveSinkバグ回避）
            if self.recording_callback_enabled and recording_callback_manager and audio_data and len(audio_data) > 44:
                try:
                    # セッションからソースGuild IDを取得
                    session = next((s for s in self.active_sessions.values() if s.session_id == session_id), None)
                    if session:
                        # 統合ユーザーID（音声リレー用）を使用
                        relay_user_id = 999999999999999999  # 音声リレー専用の仮想ユーザーID
                        
                        success = await recording_callback_manager.process_audio_data(
                            guild_id=session.source_guild_id,
                            user_id=relay_user_id,
                            audio_data=audio_data
                        )
                        
                        if success:
                            self.logger.debug(f"🎵 RELAY AUDIO FORWARDED: {len(audio_data)} bytes to RecordingCallbackManager")
                        else:
                            self.logger.debug(f"⚠️ RELAY AUDIO FORWARD FAILED: Guild {session.source_guild_id}")
                except Exception as e:
                    self.logger.warning(f"Failed to forward relay audio to RecordingCallbackManager: {e}")
            
            # 一時ファイルに書き込み
            with tempfile.NamedTemporaryFile(delete=False, suffix='.wav') as temp_file:
                temp_file.write(audio_data)
                temp_file_path = temp_file.name
            
            # FFmpegで高品質再生
            audio_source = discord.FFmpegPCMAudio(
                temp_file_path,
                before_options='-f wav',
                options='-vn -ar 48000 -ac 2 -af "volume=0.8"'  # 音質最適化
            )
            
            # 音声を再生
            target_voice_client.play(audio_source)
            
            # ファイル削除（遅延実行）
            asyncio.get_event_loop().call_later(8.0, self._safe_delete_file, temp_file_path)
            
        except Exception as e:
            self.logger.warning(f"Error playing smooth audio: {e}")

    def _safe_delete_file(self, file_path: str):
        """安全なファイル削除"""
        try:
            if os.path.exists(file_path):
                os.unlink(file_path)
        except Exception as e:
            self.logger.debug(f"Could not delete temp file {file_path}: {e}")

    async def _recording_finished_callback(self, sink, error=None):
        """録音完了時のコールバック"""
        if error:
            self.logger.warning(f"Recording finished with error: {error}")

    async def _cleanup_smooth_session(
        self, 
        session_id: str, 
        source_voice_client: Optional[discord.VoiceClient] = None
    ):
        """セッションのクリーンアップ"""
        try:
            if source_voice_client and source_voice_client.recording:
                source_voice_client.stop_recording()
        except Exception as e:
            self.logger.debug(f"Error during session cleanup: {e}")
        
        # ストリームクリーンアップ
        if session_id in self.audio_streams:
            del self.audio_streams[session_id]

    async def stop_relay_session(self, session_id: str) -> bool:
        """リレーセッション停止"""
        try:
            if session_id not in self.active_sessions:
                return False
            
            session = self.active_sessions[session_id]
            session.status = RelayStatus.STOPPING
            
            # タスクの停止
            if session_id in self.relay_tasks:
                self.relay_tasks[session_id].cancel()
                try:
                    await self.relay_tasks[session_id]
                except asyncio.CancelledError:
                    pass
                del self.relay_tasks[session_id]
            
            # セッション削除
            del self.active_sessions[session_id]
            session.status = RelayStatus.STOPPED
            
            await self._cleanup_session_resources(session_id)
            
            self.logger.info(f"🛑 Smooth relay session stopped: {session_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error stopping smooth relay session {session_id}: {e}")
            return False

    async def _cleanup_session_resources(self, session_id: str):
        """セッションリソースのクリーンアップ"""
        try:
            if session_id in self.relay_tasks:
                del self.relay_tasks[session_id]
            if session_id in self.audio_streams:
                del self.audio_streams[session_id]
        except Exception as e:
            self.logger.debug(f"Error cleaning session resources: {e}")

    def get_session_status(self, session_id: str) -> Optional[Dict[str, Any]]:
        """セッション状態の取得"""
        if session_id not in self.active_sessions:
            return None
        
        session = self.active_sessions[session_id]
        return {
            "session_id": session.session_id,
            "source_guild_id": session.source_guild_id,
            "source_channel_id": session.source_channel_id,
            "target_guild_id": session.target_guild_id,
            "target_channel_id": session.target_channel_id,
            "status": session.status.value,
            "created_at": session.created_at,
            "last_activity": session.last_activity,
            "duration": time.time() - session.created_at
        }

    def get_all_sessions(self) -> Dict[str, Dict[str, Any]]:
        """全セッション状態の取得"""
        return {
            session_id: self.get_session_status(session_id)
            for session_id in self.active_sessions
        }