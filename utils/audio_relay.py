"""
音声横流し（リレー）機能ユーティリティ
TypeScript版のstartAudioStreaming()機能をPythonに移植
"""

import asyncio
import logging
import time
import queue
import threading
from typing import Dict, Optional, Set, Tuple, Any, NamedTuple
from dataclasses import dataclass
from enum import Enum
import io
import tempfile
import os

import discord
from discord import PCMVolumeTransformer


class AudioPacket(NamedTuple):
    """音声パケットデータ構造"""
    data: bytes
    user_id: int
    session_id: str
    timestamp: float


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
    
    def __init__(self, session, target_voice_client, logger, relay_config, bot, audio_queue):
        super().__init__()
        self.session = session
        self.target_voice_client = target_voice_client
        self.logger = logger
        self.volume = relay_config.get("volume", 0.5)
        self.processed_packets = set()
        self.bot = bot
        self.audio_queue = audio_queue
        
    def write(self, data, user):
        """音声データを受信してキューに転送（同期処理、DecodeManagerスレッドで実行）"""
        try:
            self.logger.info(f"🔊 WRITE CALLED: User {user}, data size: {len(data)}")
            
            if user == self.bot.user.id:
                self.logger.debug(f"Skipping bot audio from user {user}")
                return  # ボット自身の音声は除外
            
            # パケットIDを生成（重複防止）
            current_time = time.time()
            packet_id = f"{user}_{current_time}"
            if packet_id in self.processed_packets:
                return
            
            self.processed_packets.add(packet_id)
            
            # 古いパケットIDをクリーンアップ（メモリリーク防止）
            if len(self.processed_packets) > 1000:
                self.processed_packets.clear()
            
            # 音声パケットをキューに投入（同期処理、asyncio不要）
            audio_packet = AudioPacket(
                data=data,
                user_id=user,
                session_id=self.session.session_id,
                timestamp=current_time
            )
            
            try:
                # ノンブロッキングでキューに投入
                self.audio_queue.put_nowait(audio_packet)
                self.logger.info(f"🎤 AUDIO RECEIVED: User {user}, size: {len(data)} bytes, session: {self.session.session_id}")
            except queue.Full:
                self.logger.warning(f"Audio queue full, dropping packet from user {user}")
            
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
                    before_options='-f s16le -ar 48000 -ac 2',
                    options='-vn'
                )
                
                # ボリューム調整
                audio_source = PCMVolumeTransformer(audio_source, volume=self.volume)
                
                # 既存再生を停止して新しい音声を再生
                if self.target_voice_client.is_playing():
                    self.target_voice_client.stop()
                
                self.target_voice_client.play(audio_source)
                self.logger.info(f"🎵 LIVE RELAY: User {user_id} audio streamed to target channel")
                
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
        
        # キューベース音声転送システム
        self.audio_queue: queue.Queue = queue.Queue(maxsize=1000)  # 音声パケットキュー
        self.queue_processor_task: Optional[asyncio.Task] = None
        self.queue_processor_running = False
        
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
    
    def _start_queue_processor(self):
        """キュー処理タスクの開始"""
        try:
            if not self.queue_processor_running and (self.queue_processor_task is None or self.queue_processor_task.done()):
                self.queue_processor_running = True
                self.queue_processor_task = asyncio.create_task(self._process_audio_queue())
                self.logger.info("Audio queue processor started")
        except RuntimeError:
            # イベントループが存在しない場合は後で開始
            pass
    
    async def _process_audio_queue(self):
        """音声キューを処理してリアルタイム転送を実行"""
        self.logger.debug("Audio queue processor started")
        
        while self.queue_processor_running:
            try:
                # キューから音声パケットを取得（0.01秒タイムアウト）
                try:
                    audio_packet = self.audio_queue.get(timeout=0.01)
                except queue.Empty:
                    await asyncio.sleep(0.01)  # 短時間待機してループ継続
                    continue
                
                # セッションが存在するかチェック
                if audio_packet.session_id not in self.active_sessions:
                    continue
                
                session = self.active_sessions[audio_packet.session_id]
                
                # セッションがアクティブかチェック
                if session.status != RelayStatus.ACTIVE:
                    continue
                
                # ターゲット音声クライアントを取得
                target_guild = self.bot.get_guild(session.target_guild_id)
                if not target_guild or not target_guild.voice_client:
                    continue
                
                target_voice_client = target_guild.voice_client
                
                # 音声転送を実行
                await self._relay_audio_realtime_from_queue(
                    audio_packet.data, 
                    audio_packet.user_id, 
                    target_voice_client,
                    session
                )
                
            except Exception as e:
                self.logger.error(f"Error in audio queue processor: {e}")
                await asyncio.sleep(0.1)  # エラー時は少し長めに待機
        
        self.logger.debug("Audio queue processor stopped")
    
    async def _relay_audio_realtime_from_queue(self, data: bytes, user_id: int, target_voice_client: discord.VoiceClient, session: RelaySession):
        """キューから受信した音声データをリアルタイム転送"""
        try:
            if not target_voice_client.is_connected():
                return
            
            # PCMデータを一時ファイルに書き込み
            with tempfile.NamedTemporaryFile(delete=False, suffix='.pcm') as temp_pcm:
                temp_pcm.write(data)
                temp_pcm_path = temp_pcm.name
            
            try:
                # FFmpegでPCMをDiscord対応形式に変換
                audio_source = discord.FFmpegPCMAudio(
                    temp_pcm_path,
                    before_options='-f s16le -ar 48000 -ac 2',
                    options='-vn'
                )
                
                # ボリューム調整
                volume = self.relay_config.get("volume", 0.5)
                audio_source = PCMVolumeTransformer(audio_source, volume=volume)
                
                # 既存再生を停止して新しい音声を再生
                if target_voice_client.is_playing():
                    target_voice_client.stop()
                
                target_voice_client.play(audio_source)
                self.logger.info(f"🎵 LIVE RELAY: User {user_id} audio streamed to target channel")
                
                # セッションのアクティビティを更新
                session.last_activity = time.time()
                session.active_users.add(user_id)
                
            finally:
                # クリーンアップを遅延実行
                asyncio.get_event_loop().call_later(2.0, lambda: os.unlink(temp_pcm_path) if os.path.exists(temp_pcm_path) else None)
                
        except Exception as e:
            self.logger.error(f"Error relaying queued audio: {e}")
    
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
            
            # 音声クライアントの接続状態を確実にチェック
            if not source_voice_client or not source_voice_client.is_connected():
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
            
            # 音声クライアントの接続状態を確実にチェック
            if not target_voice_client or not target_voice_client.is_connected():
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
            # キュープロセッサを開始
            self._start_queue_processor()
            
            # リアルタイムリレー用Sinkを作成（audio_queueを渡す）
            sink = RealtimeRelaySink(session, target_voice_client, self.logger, self.relay_config, self.bot, self.audio_queue)
            
            # 録音完了時のコールバック
            def after_recording(sink, error=None):
                if error:
                    self.logger.error(f"Recording error in session {session.session_id}: {error}")
                else:
                    self.logger.info(f"Recording finished for session {session.session_id}")
            
            # 既存の録音を停止してからリレー録音を開始
            if source_voice_client.recording:
                self.logger.info(f"Stopping existing recording before starting relay for session: {session.session_id}")
                source_voice_client.stop_recording()
                # 少し待機
                await asyncio.sleep(0.1)
            
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
        
        # キュープロセッサ停止
        self.queue_processor_running = False
        if self.queue_processor_task and not self.queue_processor_task.done():
            self.queue_processor_task.cancel()
            try:
                await self.queue_processor_task
            except asyncio.CancelledError:
                pass
        
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