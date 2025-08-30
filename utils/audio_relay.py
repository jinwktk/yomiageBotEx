"""
音声横流し（リレー）機能ユーティリティ
TypeScript版のstartAudioStreaming()機能をPythonに移植
"""

import asyncio
import logging
import time
from typing import Dict, Optional, Set, Tuple, Any
from dataclasses import dataclass
from enum import Enum
import io
import tempfile
import os

import discord
from discord import PCMVolumeTransformer


class RelayStatus(Enum):
    """リレー状態"""
    STOPPED = "stopped"
    STARTING = "starting"
    ACTIVE = "active"
    STOPPING = "stopping"
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
    active_users: Set[int]


class RealtimeRelaySink(discord.sinks.Sink):
    """リアルタイム音声リレー用Sink"""
    
    def __init__(self, session, target_voice_client, logger, relay_config, bot):
        super().__init__()
        self.session = session
        self.target_voice_client = target_voice_client
        self.logger = logger
        self.volume = relay_config.get("volume", 0.5)
        self.processed_packets = set()
        self.bot = bot
        
    def write(self, data, user):
        """音声データを受信してリアルタイムでターゲットに転送"""
        try:
            if user == self.bot.user.id:
                return  # ボット自身の音声は除外
            
            # デバッグ: 音声データ受信をログ出力
            self.logger.info(f"RealtimeRelaySink received audio data from user {user}, size: {len(data)} bytes")
            
            # パケットIDを生成（重複防止）
            current_time = time.time()
            packet_id = f"{user}_{current_time}"
            if packet_id in self.processed_packets:
                return
            
            self.processed_packets.add(packet_id)
            
            # 古いパケットIDをクリーンアップ（メモリリーク防止）
            if len(self.processed_packets) > 1000:
                self.processed_packets.clear()
            
            # イベントループを取得してタスクをスケジュール
            try:
                loop = asyncio.get_event_loop()
                if loop and loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        self._relay_audio_realtime(data, user), loop
                    )
                else:
                    self.logger.warning("No running event loop found for audio relay")
            except Exception as loop_error:
                self.logger.error(f"Error scheduling audio relay task: {loop_error}")
            
        except Exception as e:
            self.logger.error(f"Error in RealtimeRelaySink.write: {e}")
    
    async def _relay_audio_realtime(self, data, user_id):
        """リアルタイム音声転送"""
        try:
            if not self.target_voice_client.is_connected():
                return
            
            # PCMデータを一時ファイルに書き込み
            with tempfile.NamedTemporaryFile(delete=False, suffix='.pcm') as temp_pcm:
                temp_pcm.write(data)
                temp_pcm_path = temp_pcm.name
            
            try:
                # FFmpegでPCMをDiscord対応形式に変換
                audio_source = discord.FFmpegPCMAudio(
                    temp_pcm_path,
                    options='-f s16le -ar 48000 -ac 2'
                )
                
                # ボリューム調整
                audio_source = PCMVolumeTransformer(audio_source, volume=self.volume)
                
                # 既存再生を停止して新しい音声を再生
                if self.target_voice_client.is_playing():
                    self.target_voice_client.stop()
                
                self.target_voice_client.play(audio_source)
                self.logger.debug(f"Relaying realtime audio from user {user_id}")
                
            finally:
                # クリーンアップを遅延実行
                asyncio.get_event_loop().call_later(2.0, lambda: os.unlink(temp_pcm_path) if os.path.exists(temp_pcm_path) else None)
                
        except Exception as e:
            self.logger.error(f"Error relaying realtime audio: {e}")


class AudioRelay:
    """音声横流し（リレー）機能マネージャー"""
    
    def __init__(self, bot: discord.Bot, config: Dict[str, Any]):
        self.bot = bot
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # セッション管理
        self.active_sessions: Dict[str, RelaySession] = {}
        self.user_audio_sources: Dict[Tuple[int, int], discord.AudioSource] = {}  # (guild_id, user_id) -> AudioSource
        
        # レート制限
        self.last_stream_switch: Dict[int, float] = {}  # user_id -> timestamp
        self.stream_switch_cooldown = 2.0  # 2秒のクールダウン
        
        # バッファ管理
        self.buffer_flush_interval = 5.0
        self.max_session_duration = 3600.0  # 1時間
        
        # 設定
        self.relay_config = config.get("audio_relay", {})
        self.enabled = self.relay_config.get("enabled", False)
        
        # 定期クリーンアップタスク
        self._cleanup_task: Optional[asyncio.Task] = None
        # クリーンアップタスクはボット準備完了後に開始
    
    def _start_cleanup_task(self):
        """クリーンアップタスクの開始"""
        try:
            if self._cleanup_task is None or self._cleanup_task.done():
                self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
        except RuntimeError:
            # イベントループが存在しない場合は後で開始
            pass
    
    async def _periodic_cleanup(self):
        """定期的なクリーンアップ"""
        while True:
            try:
                await asyncio.sleep(60)  # 1分ごと
                await self._cleanup_inactive_sessions()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in periodic cleanup: {e}")
    
    async def _cleanup_inactive_sessions(self):
        """非アクティブセッションのクリーンアップ"""
        current_time = time.time()
        sessions_to_remove = []
        
        for session_id, session in self.active_sessions.items():
            # 最大セッション時間を超えた場合
            if current_time - session.created_at > self.max_session_duration:
                self.logger.info(f"Session {session_id} exceeded maximum duration, stopping")
                sessions_to_remove.append(session_id)
                continue
                
            # 長時間アクティビティがない場合
            if current_time - session.last_activity > 300:  # 5分間非アクティブ
                self.logger.info(f"Session {session_id} inactive for 5 minutes, stopping")
                sessions_to_remove.append(session_id)
        
        for session_id in sessions_to_remove:
            await self.stop_relay_session(session_id)
    
    async def start_relay_session(
        self, 
        source_guild_id: int, 
        source_channel_id: int,
        target_guild_id: int, 
        target_channel_id: int
    ) -> str:
        """音声リレーセッションの開始"""
        if not self.enabled:
            raise ValueError("Audio relay is disabled in config")
        
        # セッションIDの生成
        session_id = f"relay_{source_guild_id}_{source_channel_id}_{target_guild_id}_{target_channel_id}_{int(time.time())}"
        
        self.logger.debug(f"Starting audio relay session: {session_id}")
        
        try:
            # ソースとターゲットのチャンネルを取得
            source_guild = self.bot.get_guild(source_guild_id)
            target_guild = self.bot.get_guild(target_guild_id)
            
            if not source_guild or not target_guild:
                raise ValueError("Source or target guild not found")
            
            source_channel = source_guild.get_channel(source_channel_id)
            target_channel = target_guild.get_channel(target_channel_id)
            
            if not isinstance(source_channel, discord.VoiceChannel) or not isinstance(target_channel, discord.VoiceChannel):
                raise ValueError("Source or target channel is not a voice channel")
            
            # セッション情報を作成
            session = RelaySession(
                session_id=session_id,
                source_guild_id=source_guild_id,
                source_channel_id=source_channel_id,
                target_guild_id=target_guild_id,
                target_channel_id=target_channel_id,
                status=RelayStatus.STARTING,
                created_at=time.time(),
                last_activity=time.time(),
                active_users=set()
            )
            
            self.active_sessions[session_id] = session
            
            # ソースチャンネルに接続（既に接続していない場合）
            source_voice_client = source_guild.voice_client
            if not source_voice_client:
                # 接続していない場合のみ新規接続
                source_voice_client = await source_channel.connect()
                self.logger.debug(f"Connected to source channel: {source_channel.name}")
            elif source_voice_client.channel != source_channel:
                # 既に別のチャンネルに接続している場合
                current_channel = source_voice_client.channel
                # 現在のチャンネルに人がいるかチェック（ボット以外）
                non_bot_members = [m for m in current_channel.members if not m.bot]
                
                if len(non_bot_members) == 0:
                    # 人がいない場合は移動OK
                    await source_voice_client.move_to(source_channel)
                    self.logger.debug(f"Moved from empty channel {current_channel.name} to source channel: {source_channel.name}")
                else:
                    # 人がいる場合は移動しない
                    self.logger.debug(f"Bot staying in {current_channel.name} with {len(non_bot_members)} users, using current connection for relay")
            else:
                self.logger.debug(f"Bot already connected to source channel: {source_channel.name}")
            
            # ターゲットチャンネルに接続（既に接続していない場合）
            target_voice_client = target_guild.voice_client
            if not target_voice_client:
                # 接続していない場合のみ新規接続
                target_voice_client = await target_channel.connect()
                self.logger.debug(f"Connected to target channel: {target_channel.name}")
            elif target_voice_client.channel != target_channel:
                # 既に別のチャンネルに接続している場合
                current_channel = target_voice_client.channel
                # 現在のチャンネルに人がいるかチェック（ボット以外）
                non_bot_members = [m for m in current_channel.members if not m.bot]
                
                if len(non_bot_members) == 0:
                    # 人がいない場合は移動OK
                    await target_voice_client.move_to(target_channel)
                    self.logger.debug(f"Moved from empty channel {current_channel.name} to target channel: {target_channel.name}")
                else:
                    # 人がいる場合は移動しない
                    self.logger.debug(f"Bot staying in {current_channel.name} with {len(non_bot_members)} users, using current connection for relay")
            else:
                self.logger.debug(f"Bot already connected to target channel: {target_channel.name}")
            
            # 音声リレーの開始
            await self._start_audio_streaming(session, source_voice_client, target_voice_client)
            
            session.status = RelayStatus.ACTIVE
            self.logger.debug(f"Audio relay session started successfully: {session_id}")
            
            return session_id
            
        except Exception as e:
            self.logger.error(f"Failed to start relay session {session_id}: {e}")
            if session_id in self.active_sessions:
                self.active_sessions[session_id].status = RelayStatus.ERROR
            raise
    
    async def _start_audio_streaming(
        self, 
        session: RelaySession, 
        source_voice_client: discord.VoiceClient,
        target_voice_client: discord.VoiceClient
    ):
        """リアルタイム音声ストリーミング処理"""
        try:
            # リアルタイムリレー用Sinkを作成
            sink = RealtimeRelaySink(session, target_voice_client, self.logger, self.relay_config, self.bot)
            
            # 録音完了時のコールバック
            def after_recording(sink, error=None):
                if error:
                    self.logger.error(f"Recording error in session {session.session_id}: {error}")
                else:
                    self.logger.info(f"Recording finished for session {session.session_id}")
            
            # リアルタイム音声キャプチャを開始
            source_voice_client.start_recording(sink, after_recording)
            
            self.logger.info(f"Started realtime audio streaming for session: {session.session_id}")
            
            # セッションにsinkを保存
            session.sink = sink
            
        except Exception as e:
            self.logger.error(f"Failed to start audio streaming for session {session.session_id}: {e}")
            raise
    
    # 古いループベースのメソッドを削除（RealtimeRelaySinkに置き換え）
    
    async def stop_relay_session(self, session_id: str) -> bool:
        """リレーセッションの停止"""
        if session_id not in self.active_sessions:
            self.logger.warning(f"Session {session_id} not found")
            return False
        
        session = self.active_sessions[session_id]
        session.status = RelayStatus.STOPPING
        
        self.logger.info(f"Stopping relay session: {session_id}")
        
        try:
            # ストリーミングタスクの停止
            if hasattr(session, 'streaming_task') and session.streaming_task:
                session.streaming_task.cancel()
                try:
                    await session.streaming_task
                except asyncio.CancelledError:
                    pass
            
            # 録音停止
            source_guild = self.bot.get_guild(session.source_guild_id)
            if source_guild and source_guild.voice_client:
                source_guild.voice_client.stop_recording()
                self.logger.debug(f"Stopped recording for session {session_id}")
            
            # セッション削除
            del self.active_sessions[session_id]
            session.status = RelayStatus.STOPPED
            
            self.logger.info(f"Relay session stopped successfully: {session_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error stopping relay session {session_id}: {e}")
            session.status = RelayStatus.ERROR
            return False
    
    async def stop_all_sessions(self):
        """すべてのリレーセッションを停止"""
        session_ids = list(self.active_sessions.keys())
        for session_id in session_ids:
            await self.stop_relay_session(session_id)
        
        # クリーンアップタスク停止
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
    
    def get_active_sessions(self) -> Dict[str, Dict[str, Any]]:
        """アクティブセッションの情報取得"""
        result = {}
        for session_id, session in self.active_sessions.items():
            result[session_id] = {
                "source_guild_id": session.source_guild_id,
                "source_channel_id": session.source_channel_id,
                "target_guild_id": session.target_guild_id,
                "target_channel_id": session.target_channel_id,
                "status": session.status.value,
                "created_at": session.created_at,
                "last_activity": session.last_activity,
                "active_users": list(session.active_users),
                "duration": time.time() - session.created_at
            }
        return result
    
    def is_session_active(self, session_id: str) -> bool:
        """セッションがアクティブかチェック"""
        return (
            session_id in self.active_sessions and 
            self.active_sessions[session_id].status == RelayStatus.ACTIVE
        )