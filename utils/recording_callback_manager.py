"""
録音コールバック管理システム - 音声リレー機能から音声データを取得
py-cord WaveSinkバグを完全回避し、動作中の音声リレー機能を活用

Author: Claude Code
Date: 2025-08-30
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional, Callable, Any
import io
import wave
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class AudioChunk:
    """音声チャンクデータクラス"""
    user_id: int
    guild_id: int
    data: bytes
    timestamp: float
    duration: float
    sample_rate: int = 48000
    channels: int = 2
    sample_width: int = 2
    pcm_data: bytes = b""

class RecordingCallbackManager:
    """
    録音コールバック管理システム
    音声リレー機能からの音声データを受信・処理する
    """
    
    def __init__(self):
        """初期化"""
        self.recording_callbacks: Dict[int, List[Callable]] = {}  # guild_id -> callbacks
        self.audio_buffers: Dict[int, Dict[int, List[AudioChunk]]] = {}  # guild_id -> user_id -> chunks
        self.buffer_lock = asyncio.Lock()
        self.max_buffer_duration = 300  # 最大5分間保持
        self.cleanup_interval = 30  # 30秒ごとにクリーンアップ
        self.max_chunk_size = 1024 * 1024 * 10  # 最大10MBまでのチャンク
        self.max_user_buffer_bytes = 64 * 1024 * 1024  # ユーザーごとに最大64MB
        self.max_guild_buffer_bytes = 256 * 1024 * 1024  # ギルドごとに最大256MB
        self.max_total_buffer_bytes = 1024 * 1024 * 1024  # 全体で最大1GB
        self.is_initialized = False
        
        logger.info("RecordingCallbackManager: Initialized")

    def apply_recording_config(self, recording_config: Dict[str, Any]) -> None:
        """recording設定を反映"""
        if not isinstance(recording_config, dict):
            return

        def _coerce_mb(value: Any, default_bytes: int) -> int:
            try:
                mb = float(value)
                if mb <= 0:
                    return default_bytes
                return int(mb * 1024 * 1024)
            except (TypeError, ValueError):
                return default_bytes

        def _coerce_seconds(value: Any, default_seconds: float) -> float:
            try:
                seconds = float(value)
                if seconds <= 0:
                    return default_seconds
                return seconds
            except (TypeError, ValueError):
                return default_seconds

        current_chunk_mb = self.max_chunk_size / (1024 * 1024)
        self.max_chunk_size = _coerce_mb(
            recording_config.get("callback_max_chunk_size_mb", current_chunk_mb),
            self.max_chunk_size,
        )
        self.max_user_buffer_bytes = _coerce_mb(
            recording_config.get("callback_buffer_max_user_mb", self.max_user_buffer_bytes / (1024 * 1024)),
            self.max_user_buffer_bytes,
        )
        self.max_guild_buffer_bytes = _coerce_mb(
            recording_config.get("callback_buffer_max_guild_mb", self.max_guild_buffer_bytes / (1024 * 1024)),
            self.max_guild_buffer_bytes,
        )
        self.max_total_buffer_bytes = _coerce_mb(
            recording_config.get("callback_buffer_max_total_mb", self.max_total_buffer_bytes / (1024 * 1024)),
            self.max_total_buffer_bytes,
        )
        self.max_buffer_duration = _coerce_seconds(
            recording_config.get("callback_buffer_duration_seconds", self.max_buffer_duration),
            self.max_buffer_duration,
        )

        logger.info(
            "RecordingCallbackManager: Applied config user=%sMB guild=%sMB total=%sMB chunk=%sMB duration=%ss",
            self.max_user_buffer_bytes // (1024 * 1024),
            self.max_guild_buffer_bytes // (1024 * 1024),
            self.max_total_buffer_bytes // (1024 * 1024),
            self.max_chunk_size // (1024 * 1024),
            int(self.max_buffer_duration),
        )

    def _chunk_memory_bytes(self, chunk: AudioChunk) -> int:
        return len(chunk.data) + len(chunk.pcm_data)

    def _user_buffer_bytes_unlocked(self, guild_id: int, user_id: int) -> int:
        return sum(
            self._chunk_memory_bytes(chunk)
            for chunk in self.audio_buffers.get(guild_id, {}).get(user_id, [])
        )

    def _guild_buffer_bytes_unlocked(self, guild_id: int) -> int:
        guild_users = self.audio_buffers.get(guild_id, {})
        return sum(
            self._chunk_memory_bytes(chunk)
            for user_chunks in guild_users.values()
            for chunk in user_chunks
        )

    def _total_buffer_bytes_unlocked(self) -> int:
        return sum(
            self._chunk_memory_bytes(chunk)
            for guild_users in self.audio_buffers.values()
            for user_chunks in guild_users.values()
            for chunk in user_chunks
        )

    def _prune_empty_user_unlocked(self, guild_id: int, user_id: int) -> None:
        guild_users = self.audio_buffers.get(guild_id, {})
        if user_id in guild_users and not guild_users[user_id]:
            del guild_users[user_id]
        if guild_id in self.audio_buffers and not self.audio_buffers[guild_id]:
            del self.audio_buffers[guild_id]

    def _remove_oldest_from_user_unlocked(self, guild_id: int, user_id: int) -> bool:
        user_chunks = self.audio_buffers.get(guild_id, {}).get(user_id, [])
        if not user_chunks:
            return False
        oldest_index = min(range(len(user_chunks)), key=lambda idx: user_chunks[idx].timestamp)
        user_chunks.pop(oldest_index)
        self._prune_empty_user_unlocked(guild_id, user_id)
        return True

    def _remove_oldest_from_guild_unlocked(self, guild_id: int) -> bool:
        guild_users = self.audio_buffers.get(guild_id, {})
        oldest_user_id = None
        oldest_index = None
        oldest_timestamp = None
        for user_id, chunks in guild_users.items():
            for idx, chunk in enumerate(chunks):
                if oldest_timestamp is None or chunk.timestamp < oldest_timestamp:
                    oldest_timestamp = chunk.timestamp
                    oldest_user_id = user_id
                    oldest_index = idx
        if oldest_user_id is None or oldest_index is None:
            return False
        guild_users[oldest_user_id].pop(oldest_index)
        self._prune_empty_user_unlocked(guild_id, oldest_user_id)
        return True

    def _remove_oldest_globally_unlocked(self) -> bool:
        oldest_guild_id = None
        oldest_user_id = None
        oldest_index = None
        oldest_timestamp = None

        for guild_id, guild_users in self.audio_buffers.items():
            for user_id, chunks in guild_users.items():
                for idx, chunk in enumerate(chunks):
                    if oldest_timestamp is None or chunk.timestamp < oldest_timestamp:
                        oldest_timestamp = chunk.timestamp
                        oldest_guild_id = guild_id
                        oldest_user_id = user_id
                        oldest_index = idx

        if oldest_guild_id is None or oldest_user_id is None or oldest_index is None:
            return False

        self.audio_buffers[oldest_guild_id][oldest_user_id].pop(oldest_index)
        self._prune_empty_user_unlocked(oldest_guild_id, oldest_user_id)
        return True

    def _enforce_memory_limits_unlocked(self, guild_id: int, user_id: int) -> None:
        # ユーザー単位の上限
        while (
            self.max_user_buffer_bytes > 0
            and self._user_buffer_bytes_unlocked(guild_id, user_id) > self.max_user_buffer_bytes
        ):
            if not self._remove_oldest_from_user_unlocked(guild_id, user_id):
                break

        # ギルド単位の上限
        while (
            self.max_guild_buffer_bytes > 0
            and self._guild_buffer_bytes_unlocked(guild_id) > self.max_guild_buffer_bytes
        ):
            if not self._remove_oldest_from_guild_unlocked(guild_id):
                break

        # 全体上限
        while (
            self.max_total_buffer_bytes > 0
            and self._total_buffer_bytes_unlocked() > self.max_total_buffer_bytes
        ):
            if not self._remove_oldest_globally_unlocked():
                break
    
    async def initialize(self):
        """非同期初期化"""
        if self.is_initialized:
            return
            
        # クリーンアップタスクを開始
        self.cleanup_task = asyncio.create_task(self._periodic_cleanup())
        self.is_initialized = True
        
        logger.info("RecordingCallbackManager: Async initialization completed")
    
    async def register_guild(self, guild_id: int) -> bool:
        """Guildを録音対象として登録"""
        try:
            async with self.buffer_lock:
                if guild_id not in self.recording_callbacks:
                    self.recording_callbacks[guild_id] = []
                if guild_id not in self.audio_buffers:
                    self.audio_buffers[guild_id] = {}
            
            logger.info(f"RecordingCallbackManager: Registered guild {guild_id}")
            return True
            
        except Exception as e:
            logger.error(f"RecordingCallbackManager: Failed to register guild {guild_id}: {e}")
            return False
    
    async def add_callback(self, guild_id: int, callback: Callable) -> bool:
        """コールバック関数を追加"""
        try:
            if guild_id not in self.recording_callbacks:
                await self.register_guild(guild_id)
            
            async with self.buffer_lock:
                if callback not in self.recording_callbacks[guild_id]:
                    self.recording_callbacks[guild_id].append(callback)
            
            logger.info(f"RecordingCallbackManager: Added callback for guild {guild_id}")
            return True
            
        except Exception as e:
            logger.error(f"RecordingCallbackManager: Failed to add callback for guild {guild_id}: {e}")
            return False
    
    async def process_audio_data(self, guild_id: int, user_id: int, audio_data: bytes) -> bool:
        """
        音声データを処理してバッファに追加
        音声リレー機能から呼び出される
        """
        try:
            if not audio_data or len(audio_data) <= 44:  # WAVヘッダー以下はスキップ
                logger.debug(f"RecordingCallbackManager: Skipping empty audio data for user {user_id}")
                return False
            
            # 音声データサイズ制限
            if len(audio_data) > self.max_chunk_size:
                logger.warning(f"RecordingCallbackManager: Audio data too large ({len(audio_data)} bytes), truncating")
                audio_data = audio_data[:self.max_chunk_size]
            
            # WAVファイル解析
            duration = 0.0
            sample_rate = 48000
            channels = 2
            sample_width = 2
            pcm_data = b""
            
            try:
                with wave.open(io.BytesIO(audio_data), 'rb') as wav_file:
                    sample_rate = wav_file.getframerate()
                    channels = wav_file.getnchannels()
                    sample_width = wav_file.getsampwidth()
                    frames = wav_file.getnframes()
                    duration = frames / sample_rate if sample_rate > 0 else 0.0
                    
                    # PCMデータの有無をチェック
                    pcm_data = wav_file.readframes(frames)
                    if not pcm_data or len(pcm_data) == 0:
                        logger.debug(f"RecordingCallbackManager: No PCM data for user {user_id}")
                        return False
                        
            except Exception as wav_e:
                logger.debug(f"RecordingCallbackManager: WAV analysis failed for user {user_id}: {wav_e}")
                # フォールバック: 推定値を使用
                duration = max(1.0, len(audio_data) / (sample_rate * channels * sample_width))
            
            # AudioChunk作成
            chunk_data = b"" if pcm_data else audio_data
            chunk = AudioChunk(
                user_id=user_id,
                guild_id=guild_id,
                data=chunk_data,
                timestamp=time.time(),
                duration=duration,
                sample_rate=sample_rate,
                channels=channels,
                sample_width=sample_width,
                pcm_data=pcm_data,
            )
            
            # バッファに追加
            async with self.buffer_lock:
                if guild_id not in self.audio_buffers:
                    self.audio_buffers[guild_id] = {}
                if user_id not in self.audio_buffers[guild_id]:
                    self.audio_buffers[guild_id][user_id] = []
                
                # 古いチャンクを削除（最大持続時間を超える場合）
                current_time = time.time()
                self.audio_buffers[guild_id][user_id] = [
                    c for c in self.audio_buffers[guild_id][user_id]
                    if current_time - c.timestamp <= self.max_buffer_duration
                ]
                
                # 新しいチャンクを追加
                self.audio_buffers[guild_id][user_id].append(chunk)
                self._enforce_memory_limits_unlocked(guild_id, user_id)
            
            logger.debug(f"RecordingCallbackManager: Added audio chunk for guild {guild_id}, user {user_id} ({duration:.1f}s)")
            
            # 登録されたコールバックを呼び出し
            await self._notify_callbacks(guild_id, user_id, chunk)
            
            return True
            
        except Exception as e:
            logger.error(f"RecordingCallbackManager: Failed to process audio data: {e}", exc_info=True)
            return False
    
    async def _notify_callbacks(self, guild_id: int, user_id: int, chunk: AudioChunk):
        """登録されたコールバックに通知"""
        try:
            if guild_id not in self.recording_callbacks:
                return
            
            for callback in self.recording_callbacks[guild_id]:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(chunk)
                    else:
                        callback(chunk)
                except Exception as cb_e:
                    logger.error(f"RecordingCallbackManager: Callback error: {cb_e}")
                    
        except Exception as e:
            logger.error(f"RecordingCallbackManager: Failed to notify callbacks: {e}")
    
    async def get_recent_audio(self, guild_id: int, duration_seconds: float = 30.0, 
                             user_id: Optional[int] = None) -> List[AudioChunk]:
        """指定時間分の最新音声チャンクを取得"""
        try:
            async with self.buffer_lock:
                if guild_id not in self.audio_buffers:
                    return []
                
                current_time = time.time()
                start_time = current_time - duration_seconds
                result_chunks = []
                
                if user_id:
                    # 特定ユーザーのみ
                    if user_id in self.audio_buffers[guild_id]:
                        user_chunks = [
                            chunk for chunk in self.audio_buffers[guild_id][user_id]
                            if chunk.timestamp >= start_time
                        ]
                        result_chunks.extend(user_chunks)
                else:
                    # 全ユーザー
                    for uid, chunks in self.audio_buffers[guild_id].items():
                        user_chunks = [
                            chunk for chunk in chunks
                            if chunk.timestamp >= start_time
                        ]
                        result_chunks.extend(user_chunks)
                
                # タイムスタンプでソート
                result_chunks.sort(key=lambda c: c.timestamp)
                
                logger.info(f"RecordingCallbackManager: Retrieved {len(result_chunks)} chunks for guild {guild_id}")
                return result_chunks
                
        except Exception as e:
            logger.error(f"RecordingCallbackManager: Failed to get recent audio: {e}")
            return []
    
    async def _periodic_cleanup(self):
        """定期的なバッファクリーンアップ"""
        while True:
            try:
                await asyncio.sleep(self.cleanup_interval)
                
                current_time = time.time()
                async with self.buffer_lock:
                    for guild_id in list(self.audio_buffers.keys()):
                        for user_id in list(self.audio_buffers[guild_id].keys()):
                            # 古いチャンクを削除
                            old_count = len(self.audio_buffers[guild_id][user_id])
                            self.audio_buffers[guild_id][user_id] = [
                                chunk for chunk in self.audio_buffers[guild_id][user_id]
                                if current_time - chunk.timestamp <= self.max_buffer_duration
                            ]
                            new_count = len(self.audio_buffers[guild_id][user_id])
                            
                            if old_count != new_count:
                                logger.debug(f"RecordingCallbackManager: Cleaned {old_count - new_count} old chunks for user {user_id}")
                            
                            # 空のユーザーバッファを削除
                            if not self.audio_buffers[guild_id][user_id]:
                                del self.audio_buffers[guild_id][user_id]

                        # 定期掃除時にもギルドごとの上限を再チェック
                        for user_id in list(self.audio_buffers.get(guild_id, {}).keys()):
                            self._enforce_memory_limits_unlocked(guild_id, user_id)
                        
                        # 空のGuildバッファを削除
                        guild_buffers = self.audio_buffers.get(guild_id)
                        if not guild_buffers:
                            self.audio_buffers.pop(guild_id, None)
                            if guild_id in self.recording_callbacks:
                                del self.recording_callbacks[guild_id]
                
                logger.debug("RecordingCallbackManager: Periodic cleanup completed")
                
            except Exception as e:
                logger.error(f"RecordingCallbackManager: Cleanup error: {e}")
    
    def get_buffer_status(self) -> Dict[str, Any]:
        """バッファの状態を取得（デバッグ用）"""
        try:
            total_guilds = len(self.audio_buffers)
            total_users = sum(len(users) for users in self.audio_buffers.values())
            total_chunks = sum(
                sum(len(chunks) for chunks in users.values()) 
                for users in self.audio_buffers.values()
            )
            total_bytes = self._total_buffer_bytes_unlocked()
            
            return {
                'total_guilds': total_guilds,
                'total_users': total_users,  
                'total_chunks': total_chunks,
                'total_bytes': total_bytes,
                'buffer_duration': self.max_buffer_duration,
                'max_user_buffer_bytes': self.max_user_buffer_bytes,
                'max_guild_buffer_bytes': self.max_guild_buffer_bytes,
                'max_total_buffer_bytes': self.max_total_buffer_bytes,
                'initialized': self.is_initialized
            }
            
        except Exception as e:
            logger.error(f"RecordingCallbackManager: Failed to get buffer status: {e}")
            return {'error': str(e)}
    
    async def shutdown(self):
        """シャットダウン処理"""
        try:
            if hasattr(self, 'cleanup_task'):
                self.cleanup_task.cancel()
                try:
                    await self.cleanup_task
                except asyncio.CancelledError:
                    pass
            
            async with self.buffer_lock:
                self.audio_buffers.clear()
                self.recording_callbacks.clear()
            
            self.is_initialized = False
            logger.info("RecordingCallbackManager: Shutdown completed")
            
        except Exception as e:
            logger.error(f"RecordingCallbackManager: Shutdown error: {e}")

# グローバルインスタンス
recording_callback_manager = RecordingCallbackManager()
