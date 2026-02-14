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
        self.is_initialized = False
        
        logger.info("RecordingCallbackManager: Initialized")
    
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
            chunk = AudioChunk(
                user_id=user_id,
                guild_id=guild_id,
                data=audio_data,
                timestamp=time.time(),
                duration=duration,
                sample_rate=sample_rate,
                channels=channels,
                sample_width=sample_width
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
                        
                        # 空のGuildバッファを削除
                        if not self.audio_buffers[guild_id]:
                            del self.audio_buffers[guild_id]
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
            
            return {
                'total_guilds': total_guilds,
                'total_users': total_users,  
                'total_chunks': total_chunks,
                'buffer_duration': self.max_buffer_duration,
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