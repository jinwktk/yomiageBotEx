#!/usr/bin/env python3
"""
修正版音声リレーシステム
シンプルで確実に動作する音声横流し機能
"""

import asyncio
import logging
import time
import tempfile
import os
import struct
from typing import Dict, Optional, Set, Any, Callable
from dataclasses import dataclass
from enum import Enum

import discord
from discord.sinks import WaveSink

# RecordingCallbackManager統合のためのインポート
try:
    from .recording_callback_manager import recording_callback_manager
    RECORDING_CALLBACK_AVAILABLE = True
except ImportError:
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
    sink: Optional[WaveSink] = None


class FixedAudioRelay:
    """安定した音声リレーシステム（固定サイクル方式）"""
    
    def __init__(self, bot: discord.Bot, config: Dict[str, Any], logger: logging.Logger):
        self.bot = bot
        self.config = config.get("audio_relay", {})
        self.logger = logger
        self.active_sessions: Dict[str, RelaySession] = {}
        self.enabled = self.config.get("enabled", False)
        
        # リレータスク管理
        self.relay_tasks: Dict[str, asyncio.Task] = {}
        
        # 安定した音声処理設定
        self.recording_duration = 3.0  # 3秒サイクルで録音
        self.volume = self.config.get("volume", 0.7)
        self.max_sessions = self.config.get("max_sessions", 10)
        self.max_duration_hours = self.config.get("max_duration_hours", 1)
        
        # RecordingCallbackManager統合
        self.recording_callback_enabled = RECORDING_CALLBACK_AVAILABLE
        if self.recording_callback_enabled:
            self.logger.info("FixedAudioRelay: RecordingCallbackManager integration enabled")
        
        self.logger.info(f"Fixed Audio Relay initialized - {'enabled' if self.enabled else 'disabled'}")

    async def start_relay_session(
        self,
        source_guild_id: int,
        source_channel_id: int,
        target_guild_id: int,
        target_channel_id: int
    ) -> str:
        """リアルタイム音声リレーセッションの開始"""
        if not self.enabled:
            raise ValueError("Audio relay is disabled in config")
        
        # セッションID生成
        session_id = f"streaming_relay_{source_guild_id}_{target_guild_id}_{int(time.time())}"
        
        self.logger.info(f"🎤 Starting streaming relay session: {session_id}")
        
        try:
            # ギルドとチャンネル取得
            source_guild = self.bot.get_guild(source_guild_id)
            target_guild = self.bot.get_guild(target_guild_id)
            
            if not source_guild or not target_guild:
                raise ValueError(f"Guild not found: source={source_guild_id}, target={target_guild_id}")
            
            source_channel = source_guild.get_channel(source_channel_id)
            target_channel = target_guild.get_channel(target_channel_id)
            
            if not isinstance(source_channel, discord.VoiceChannel) or not isinstance(target_channel, discord.VoiceChannel):
                raise ValueError(f"Invalid voice channels: source={source_channel}, target={target_channel}")
            
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
            self.stream_buffers[session_id] = asyncio.Queue(maxsize=self.max_buffer_size)
            
            # 音声接続を確立
            source_voice_client, target_voice_client = await self._setup_voice_connections(
                source_guild, source_channel, target_guild, target_channel
            )
            
            # ストリーミングタスクを開始
            relay_task = asyncio.create_task(
                self._streaming_relay_loop(session, source_voice_client, target_voice_client)
            )
            self.relay_tasks[session_id] = relay_task
            
            session.status = RelayStatus.ACTIVE
            
            self.logger.info(f"🔊 STREAMING RELAY ACTIVE: {source_channel.name} → {target_channel.name}")
            return session_id
            
        except Exception as e:
            self.logger.error(f"Failed to start streaming relay session {session_id}: {e}")
            if session_id in self.active_sessions:
                self.active_sessions[session_id].status = RelayStatus.ERROR
            # クリーンアップ
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
            # スマートな移動判定
            if await self._should_move_connection(source_voice_client, source_channel):
                await source_voice_client.move_to(source_channel)
                self.logger.info(f"Moved to source channel: {source_channel.name}")
        
        # ターゲットチャンネル接続
        target_voice_client = target_guild.voice_client
        if not target_voice_client or not target_voice_client.is_connected():
            target_voice_client = await target_channel.connect()
            self.logger.info(f"Connected to target channel: {target_channel.name}")
        elif target_voice_client.channel.id != target_channel.id:
            # スマートな移動判定
            if await self._should_move_connection(target_voice_client, target_channel):
                await target_voice_client.move_to(target_channel)
                self.logger.info(f"Moved to target channel: {target_channel.name}")
        
        return source_voice_client, target_voice_client

    async def _should_move_connection(
        self, 
        voice_client: discord.VoiceClient, 
        target_channel: discord.VoiceChannel
    ) -> bool:
        """接続移動の判定"""
        current_channel = voice_client.channel
        if not current_channel:
            return True
        
        # 現在のチャンネルに人がいるかチェック
        non_bot_members = [m for m in current_channel.members if not m.bot]
        
        # 人がいない場合は移動OK
        return len(non_bot_members) == 0

    async def _streaming_relay_loop(
        self,
        session: RelaySession,
        source_voice_client: discord.VoiceClient,
        target_voice_client: discord.VoiceClient
    ):
        """リアルタイムストリーミングリレーループ"""
        try:
            # カスタムSinkでリアルタイム処理
            def audio_callback(chunk_data, user=None, guild_id=None):
                """音声チャンクを受信してバッファに追加"""
                try:
                    # 既存の音声リレー処理（変更なし）
                    self.stream_buffers[session.session_id].put_nowait(chunk_data)
                    
                    # RecordingCallbackManagerに音声データを通知（新機能）
                    if self.recording_callback_enabled and user and guild_id and chunk_data:
                        # 非同期処理でRecordingCallbackManagerに通知
                        asyncio.create_task(
                            recording_callback_manager.process_audio_data(
                                guild_id=guild_id,
                                user_id=user.id,
                                audio_data=chunk_data
                            )
                        )
                        
                except asyncio.QueueFull:
                    self.logger.warning(f"Stream buffer full for session {session.session_id}")
                except Exception as e:
                    # RecordingCallbackManager関連のエラーは音声リレー機能に影響しない
                    self.logger.debug(f"RecordingCallbackManager error: {e}")
            
            streaming_sink = StreamingSink(
                chunk_duration=self.chunk_duration,
                callback=audio_callback,
                guild_id=session.source_guild_id
            )
            
            # 録音開始
            source_voice_client.start_recording(streaming_sink, self._recording_finished_callback)
            
            # 再生ループ
            playback_task = asyncio.create_task(
                self._playback_loop(session, target_voice_client)
            )
            
            # セッション監視
            while session.status == RelayStatus.ACTIVE:
                # 接続状態チェック
                if not source_voice_client.is_connected() or not target_voice_client.is_connected():
                    self.logger.warning(f"Voice clients disconnected for session {session.session_id}")
                    break
                
                # アクティビティ更新
                session.last_activity = time.time()
                
                # 短い間隔でチェック
                await asyncio.sleep(1.0)
            
            # クリーンアップ
            playback_task.cancel()
            try:
                await playback_task
            except asyncio.CancelledError:
                pass
                
        except asyncio.CancelledError:
            self.logger.info(f"Streaming relay loop cancelled for session {session.session_id}")
            raise
        except Exception as e:
            self.logger.error(f"Error in streaming relay loop for session {session.session_id}: {e}")
            session.status = RelayStatus.ERROR
        finally:
            # 録音停止
            try:
                if source_voice_client.recording:
                    source_voice_client.stop_recording()
            except Exception as e:
                self.logger.warning(f"Error stopping recording: {e}")

    async def _playback_loop(self, session: RelaySession, target_voice_client: discord.VoiceClient):
        """音声再生ループ"""
        session_id = session.session_id
        buffer = self.stream_buffers[session_id]
        
        try:
            while session.status == RelayStatus.ACTIVE:
                try:
                    # バッファから音声チャンクを取得（タイムアウト付き）
                    audio_chunk = await asyncio.wait_for(buffer.get(), timeout=2.0)
                    
                    if audio_chunk and len(audio_chunk) > 44:  # WAVヘッダー分をスキップ
                        # 音量調整
                        adjusted_chunk = self._adjust_volume(audio_chunk, self.volume)
                        
                        # リアルタイム再生
                        await self._play_audio_chunk(target_voice_client, adjusted_chunk)
                        
                except asyncio.TimeoutError:
                    # タイムアウトは正常（無音期間）
                    continue
                except Exception as e:
                    self.logger.warning(f"Error in playback loop: {e}")
                    continue
                    
        except asyncio.CancelledError:
            self.logger.debug(f"Playback loop cancelled for session {session_id}")
            raise

    def _adjust_volume(self, audio_data: bytes, volume: float) -> bytes:
        """音量調整"""
        if volume == 1.0:
            return audio_data
        
        try:
            import array
            # 16-bit signed PCMとして処理
            audio_array = array.array('h', audio_data[44:])  # WAVヘッダーをスキップ
            
            # 音量調整
            for i in range(len(audio_array)):
                audio_array[i] = int(audio_array[i] * volume)
                # クリッピング防止
                if audio_array[i] > 32767:
                    audio_array[i] = 32767
                elif audio_array[i] < -32768:
                    audio_array[i] = -32768
            
            # WAVヘッダーを追加して返す
            return audio_data[:44] + audio_array.tobytes()
            
        except Exception as e:
            self.logger.warning(f"Volume adjustment failed: {e}")
            return audio_data

    async def _play_audio_chunk(self, target_voice_client: discord.VoiceClient, audio_chunk: bytes):
        """音声チャンクの再生"""
        try:
            # 一時ファイルに書き込み
            with tempfile.NamedTemporaryFile(delete=False, suffix='.wav') as temp_file:
                temp_file.write(audio_chunk)
                temp_file_path = temp_file.name
            
            # FFmpegで再生
            audio_source = discord.FFmpegPCMAudio(
                temp_file_path,
                before_options='-f wav',
                options='-vn -filter:a "volume=1.0"'
            )
            
            # 既存再生を停止して新しい音声を再生
            if target_voice_client.is_playing():
                target_voice_client.stop()
            
            target_voice_client.play(audio_source)
            
            # クリーンアップ（少し遅延させて確実にファイルが使用終了してから）
            asyncio.get_event_loop().call_later(0.5, self._cleanup_temp_file, temp_file_path)
            
        except Exception as e:
            self.logger.warning(f"Error playing audio chunk: {e}")

    async def _recording_finished_callback(self, sink, error=None):
        """録音完了時のコールバック"""
        if error:
            self.logger.warning(f"Recording finished with error: {error}")

    def _cleanup_temp_file(self, file_path: str):
        """一時ファイルのクリーンアップ"""
        try:
            if os.path.exists(file_path):
                os.unlink(file_path)
        except Exception as e:
            self.logger.warning(f"Failed to cleanup temp file {file_path}: {e}")

    async def _cleanup_session_resources(self, session_id: str):
        """セッションリソースのクリーンアップ"""
        try:
            # バッファクリーンアップ
            if session_id in self.stream_buffers:
                del self.stream_buffers[session_id]
            
            # タスククリーンアップ
            if session_id in self.relay_tasks:
                task = self.relay_tasks[session_id]
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                del self.relay_tasks[session_id]
                
        except Exception as e:
            self.logger.warning(f"Error cleaning up session resources for {session_id}: {e}")

    async def stop_relay_session(self, session_id: str) -> bool:
        """リレーセッションの停止"""
        if session_id not in self.active_sessions:
            self.logger.warning(f"Session {session_id} not found")
            return False
        
        session = self.active_sessions[session_id]
        session.status = RelayStatus.STOPPING
        
        try:
            # リソースクリーンアップ
            await self._cleanup_session_resources(session_id)
            
            # 録音停止
            source_guild = self.bot.get_guild(session.source_guild_id)
            if source_guild and source_guild.voice_client and source_guild.voice_client.recording:
                source_guild.voice_client.stop_recording()
            
            # セッション削除
            del self.active_sessions[session_id]
            session.status = RelayStatus.STOPPED
            
            self.logger.info(f"🛑 STREAMING RELAY STOPPED: Session {session_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error stopping streaming relay session {session_id}: {e}")
            return False

    async def stop_all_sessions(self):
        """すべてのリレーセッションを停止"""
        sessions_to_stop = list(self.active_sessions.keys())
        for session_id in sessions_to_stop:
            await self.stop_relay_session(session_id)
        
        self.logger.info("All streaming relay sessions stopped")

    def get_active_sessions(self) -> Dict[str, Dict[str, Any]]:
        """アクティブセッション情報を取得"""
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
                "duration": time.time() - session.created_at,
                "buffer_size": self.stream_buffers[session_id].qsize() if session_id in self.stream_buffers else 0
            }
        return result

    def is_session_active(self, session_id: str) -> bool:
        """セッションがアクティブかチェック"""
        return (
            session_id in self.active_sessions and 
            self.active_sessions[session_id].status == RelayStatus.ACTIVE
        )


class StreamingSink(discord.sinks.WaveSink):
    """
    リアルタイムストリーミング用のオーディオSink
    
    小さなチャンク（100ms）でオーディオデータを処理し、
    リアルタイムでストリーミングバッファに送信
    """

    def __init__(self, chunk_duration: float = 2.0, callback=None, guild_id: Optional[int] = None):
        """
        StreamingSinkを初期化
        
        Args:
            chunk_duration: チャンクの長さ（秒）
            callback: オーディオチャンクを受信するコールバック関数
            guild_id: Guild ID（録音機能統合用）
        """
        super().__init__()
        self.chunk_duration = chunk_duration
        self.callback = callback
        self.guild_id = guild_id
        self.chunk_size_bytes = int(48000 * 2 * 2 * chunk_duration)  # 48kHz, 16bit, stereo
        self.last_chunk_time = time.time()
        
    def write(self, data, user):
        """
        オーディオデータを受信して処理
        
        Args:
            data: PCMオーディオデータ
            user: Discordユーザーオブジェクト
        """
        if not data:
            return
            
        current_time = time.time()
        
        # ユーザー別のバッファを取得または作成
        if user not in self.audio_data:
            self.audio_data[user] = bytearray()
            
        self.audio_data[user].extend(data)
        
        # チャンクサイズに達した場合、またはタイムアウトした場合にコールバック実行
        if (len(self.audio_data[user]) >= self.chunk_size_bytes or 
            current_time - self.last_chunk_time >= self.chunk_duration):
            
            if self.callback and len(self.audio_data[user]) > 0:
                # WAVファイル形式でチャンクを作成
                chunk_wav = self._create_wav_chunk(self.audio_data[user], user)
                self.callback(chunk_wav, user, self.guild_id)
                
                # バッファをクリア
                self.audio_data[user] = bytearray()
                self.last_chunk_time = current_time
    
    def _create_wav_chunk(self, pcm_data: bytes, user) -> bytes:
        """
        PCMデータからWAVチャンクを作成
        
        Args:
            pcm_data: PCMオーディオデータ
            user: Discordユーザーオブジェクト
            
        Returns:
            WAVファイル形式のバイトデータ
        """
        try:
            # WAVヘッダーを作成
            sample_rate = 48000
            channels = 2
            bits_per_sample = 16
            byte_rate = sample_rate * channels * bits_per_sample // 8
            block_align = channels * bits_per_sample // 8
            
            # WAVヘッダー構造
            header = struct.pack(
                '<4sI4s4sIHHIIHH4sI',
                b'RIFF',                    # ChunkID
                36 + len(pcm_data),         # ChunkSize
                b'WAVE',                    # Format
                b'fmt ',                    # Subchunk1ID
                16,                         # Subchunk1Size
                1,                          # AudioFormat (PCM)
                channels,                   # NumChannels
                sample_rate,                # SampleRate
                byte_rate,                  # ByteRate
                block_align,                # BlockAlign
                bits_per_sample,            # BitsPerSample
                b'data',                    # Subchunk2ID
                len(pcm_data)               # Subchunk2Size
            )
            
            return header + pcm_data
            
        except Exception as e:
            logger.error(f"WAVチャンク作成エラー: {e}")
            return b''
    
    def cleanup(self):
        """リソースのクリーンアップ"""
        super().cleanup()
        self.callback = None
        if hasattr(self, 'audio_data'):
            self.audio_data.clear()
