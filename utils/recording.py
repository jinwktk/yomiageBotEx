"""
録音・リプレイ機能ユーティリティ
- 音声バッファ管理
- 録音ファイル管理
- 自動クリーンアップ
"""

import asyncio
import aiofiles
import logging
import io
import wave
import hashlib
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Deque
from collections import deque
import json
import threading
import discord

logger = logging.getLogger(__name__)


class AudioBuffer:
    """音声データのリングバッファ"""
    
    def __init__(self, max_duration_minutes: int = 10, sample_rate: int = 48000):
        self.max_duration = max_duration_minutes * 60  # 秒
        self.sample_rate = sample_rate
        self.buffer: Deque[bytes] = deque()
        self.timestamps: Deque[datetime] = deque()
        self.lock = threading.Lock()
        self.total_duration = 0.0
    
    def add_audio_chunk(self, audio_data: bytes, chunk_duration: float):
        """音声チャンクをバッファに追加"""
        with self.lock:
            current_time = datetime.now()
            
            # 新しいチャンクを追加
            self.buffer.append(audio_data)
            self.timestamps.append(current_time)
            self.total_duration += chunk_duration
            
            # 最大時間を超えた古いチャンクを削除
            while (self.total_duration > self.max_duration and 
                   len(self.buffer) > 1):
                old_chunk = self.buffer.popleft()
                self.timestamps.popleft()
                # 削除したチャンクの推定時間を計算（簡易）
                estimated_chunk_duration = len(old_chunk) / (self.sample_rate * 2)  # 16bit = 2bytes
                self.total_duration -= estimated_chunk_duration
            
            logger.debug(f"Buffer: {len(self.buffer)} chunks, {self.total_duration:.1f}s")
    
    def get_recent_audio(self, duration_seconds: float = 30.0) -> Optional[bytes]:
        """指定した時間分の最新音声を取得"""
        with self.lock:
            if not self.buffer:
                return None
            
            # 指定時間分のチャンクを収集
            target_time = datetime.now() - timedelta(seconds=duration_seconds)
            recent_chunks = []
            
            for i, timestamp in enumerate(reversed(self.timestamps)):
                if timestamp >= target_time:
                    chunk_index = len(self.buffer) - 1 - i
                    recent_chunks.insert(0, self.buffer[chunk_index])
                else:
                    break
            
            if not recent_chunks:
                return None
            
            # チャンクを結合
            return b''.join(recent_chunks)
    
    def clear(self):
        """バッファをクリア"""
        with self.lock:
            self.buffer.clear()
            self.timestamps.clear()
            self.total_duration = 0.0


class RecordingManager:
    """録音ファイルの管理"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.recording_dir = Path("recordings")
        self.recording_dir.mkdir(parents=True, exist_ok=True)
        self.cleanup_hours = config.get("recording", {}).get("cleanup_hours", 1)
        self.max_duration = config.get("recording", {}).get("max_duration", 300)  # 5分
        self.sample_rate = 48000  # Discordの標準サンプルレート
        
        # ギルドごとの音声バッファ
        self.buffers: Dict[int, AudioBuffer] = {}
        
        # ユーザーごとの音声バッファ（ギルドID -> ユーザーID -> AudioBuffer）
        self.user_buffers: Dict[int, Dict[int, AudioBuffer]] = {}
        
        # 録音ファイル情報
        self.recordings_info_file = self.recording_dir / "recordings_info.json"
        self.recordings_info = self.load_recordings_info()
    
    def load_recordings_info(self) -> Dict[str, Any]:
        """録音ファイル情報を読み込み"""
        try:
            if self.recordings_info_file.exists():
                with open(self.recordings_info_file, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load recordings info: {e}")
        return {}
    
    def save_recordings_info(self):
        """録音ファイル情報を保存"""
        try:
            with open(self.recordings_info_file, "w", encoding="utf-8") as f:
                json.dump(self.recordings_info, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save recordings info: {e}")
    
    def get_buffer(self, guild_id: int) -> AudioBuffer:
        """ギルド用の音声バッファを取得"""
        if guild_id not in self.buffers:
            buffer_minutes = self.config.get("audio", {}).get("buffer_minutes", 10)
            self.buffers[guild_id] = AudioBuffer(
                max_duration_minutes=buffer_minutes,
                sample_rate=self.sample_rate
            )
        return self.buffers[guild_id]
    
    def add_audio_data(self, guild_id: int, audio_data: bytes, user_id: Optional[int] = None):
        """音声データをバッファに追加"""
        # 全体バッファに追加
        buffer = self.get_buffer(guild_id)
        
        # チャンクの推定時間（簡易計算）
        # ステレオ16bitなので、1サンプル = 4バイト
        chunk_duration = len(audio_data) / (self.sample_rate * 2 * 2)  # 16bit stereo = 4bytes/sample
        buffer.add_audio_chunk(audio_data, chunk_duration)
        
        # ユーザー別バッファに追加
        if user_id is not None:
            if guild_id not in self.user_buffers:
                self.user_buffers[guild_id] = {}
            if user_id not in self.user_buffers[guild_id]:
                buffer_minutes = self.config.get("audio", {}).get("buffer_minutes", 10)
                self.user_buffers[guild_id][user_id] = AudioBuffer(
                    max_duration_minutes=buffer_minutes,
                    sample_rate=self.sample_rate
                )
            user_buffer = self.user_buffers[guild_id][user_id]
            user_buffer.add_audio_chunk(audio_data, chunk_duration)
        
        # デバッグ: 音声データの詳細をログ出力
        if len(buffer.buffer) % 50 == 0:  # 50チャンクごと（約1秒）
            # 音声データの中身をチェック
            import numpy as np
            audio_array = np.frombuffer(audio_data, dtype=np.int16)
            max_amplitude = np.max(np.abs(audio_array)) if len(audio_array) > 0 else 0
            logger.debug(f"Recording buffer (guild {guild_id}, user {user_id}): {len(buffer.buffer)} chunks, {buffer.total_duration:.1f}s, latest chunk: {len(audio_data)} bytes, max_amp: {max_amplitude}, first 8 bytes: {audio_data[:8].hex()}")
    
    async def save_recent_audio(
        self, 
        guild_id: int, 
        duration_seconds: float = 30.0,
        requester_id: Optional[int] = None,
        target_user_id: Optional[int] = None
    ) -> Optional[str]:
        """最近の音声を録音ファイルとして保存"""
        if target_user_id is not None:
            # 特定ユーザーの音声
            if guild_id not in self.user_buffers or target_user_id not in self.user_buffers[guild_id]:
                logger.warning(f"No audio data for user {target_user_id}")
                return None
            buffer = self.user_buffers[guild_id][target_user_id]
            audio_data = buffer.get_recent_audio(duration_seconds)
            user_suffix = f"_user{target_user_id}"
        else:
            # 全体の音声（全ユーザーマージ）
            if guild_id not in self.user_buffers or not self.user_buffers[guild_id]:
                # ユーザー別バッファがない場合は全体バッファを使用
                buffer = self.get_buffer(guild_id)
                audio_data = buffer.get_recent_audio(duration_seconds)
                user_suffix = "_all"
            else:
                # 全ユーザーの音声をマージ
                audio_data = await self._merge_user_audio(guild_id, duration_seconds)
                user_count = len(self.user_buffers[guild_id])
                user_suffix = f"_all_{user_count}users"
        
        if not audio_data:
            logger.warning("No audio data to save")
            return None
        
        # ファイル名生成
        timestamp = datetime.now()
        filename = f"recording_{guild_id}{user_suffix}_{timestamp.strftime('%Y%m%d_%H%M%S')}.wav"
        file_path = self.recording_dir / filename
        
        try:
            # WAVファイルとして保存
            await self.save_as_wav(file_path, audio_data)
            
            # 録音情報を記録
            recording_id = hashlib.md5(filename.encode()).hexdigest()[:12]
            self.recordings_info[recording_id] = {
                "filename": filename,
                "guild_id": guild_id,
                "requester_id": requester_id,
                "duration": duration_seconds,
                "created_at": timestamp.isoformat(),
                "file_size": file_path.stat().st_size
            }
            self.save_recordings_info()
            
            logger.info(f"Saved recording: {filename} ({duration_seconds}s)")
            return recording_id
            
        except Exception as e:
            logger.error(f"Failed to save recording: {e}")
            return None
    
    async def _merge_user_audio(self, guild_id: int, duration_seconds: float) -> Optional[bytes]:
        """全ユーザーの音声をマージ"""
        if guild_id not in self.user_buffers:
            return None
        
        all_audio_data = []
        for user_id, buffer in self.user_buffers[guild_id].items():
            user_audio = buffer.get_recent_audio(duration_seconds)
            if user_audio:
                all_audio_data.append(user_audio)
        
        if not all_audio_data:
            return None
        
        # 単純に連結（より高度なミキシングも可能）
        return b''.join(all_audio_data)
    
    async def save_as_wav(self, file_path: Path, audio_data: bytes):
        """音声データをWAVファイルとして保存"""
        try:
            # デバッグ: 保存する音声データの詳細をログ出力
            import numpy as np
            audio_array = np.frombuffer(audio_data, dtype=np.int16)
            max_amplitude = np.max(np.abs(audio_array)) if len(audio_array) > 0 else 0
            logger.info(f"Saving WAV file: {len(audio_data)} bytes, max amplitude: {max_amplitude}, first 16 bytes: {audio_data[:16].hex()}")
            
            async with aiofiles.open(file_path, "wb") as f:
                # WAVヘッダーを作成
                wav_buffer = io.BytesIO()
                with wave.open(wav_buffer, 'wb') as wav_file:
                    wav_file.setnchannels(2)  # ステレオ
                    wav_file.setsampwidth(2)  # 16-bit
                    wav_file.setframerate(self.sample_rate)
                    wav_file.writeframes(audio_data)
                
                wav_buffer.seek(0)
                wav_data = wav_buffer.read()
                await f.write(wav_data)
                
                # デバッグ: 作成されたWAVファイルのサイズ
                logger.info(f"Created WAV file: {len(wav_data)} bytes total")
                
        except Exception as e:
            logger.error(f"Failed to write WAV file: {e}")
            raise
    
    async def get_recording_path(self, recording_id: str) -> Optional[Path]:
        """録音IDから録音ファイルのパスを取得"""
        if recording_id not in self.recordings_info:
            return None
        
        filename = self.recordings_info[recording_id]["filename"]
        file_path = self.recording_dir / filename
        
        if not file_path.exists():
            logger.warning(f"Recording file not found: {filename}")
            return None
        
        return file_path
    
    async def list_recent_recordings(self, guild_id: int, limit: int = 5) -> List[Dict[str, Any]]:
        """最近の録音リストを取得"""
        guild_recordings = []
        
        for recording_id, info in self.recordings_info.items():
            if info["guild_id"] == guild_id:
                guild_recordings.append({
                    "id": recording_id,
                    "created_at": info["created_at"],
                    "duration": info["duration"],
                    "file_size": info.get("file_size", 0)
                })
        
        # 作成日時順にソート（新しい順）
        guild_recordings.sort(key=lambda x: x["created_at"], reverse=True)
        
        return guild_recordings[:limit]
    
    async def cleanup_old_recordings(self):
        """古い録音ファイルを削除"""
        try:
            cutoff_time = datetime.now() - timedelta(hours=self.cleanup_hours)
            deleted_count = 0
            
            to_delete = []
            for recording_id, info in self.recordings_info.items():
                created_time = datetime.fromisoformat(info["created_at"])
                if created_time < cutoff_time:
                    to_delete.append(recording_id)
            
            for recording_id in to_delete:
                info = self.recordings_info[recording_id]
                file_path = self.recording_dir / info["filename"]
                
                try:
                    if file_path.exists():
                        file_path.unlink()
                    del self.recordings_info[recording_id]
                    deleted_count += 1
                except Exception as e:
                    logger.error(f"Failed to delete recording {recording_id}: {e}")
            
            if deleted_count > 0:
                self.save_recordings_info()
                logger.info(f"Deleted {deleted_count} old recording(s)")
                
        except Exception as e:
            logger.error(f"Failed to cleanup old recordings: {e}")
    
    async def start_cleanup_task(self):
        """録音ファイルのクリーンアップタスクを開始"""
        while True:
            try:
                await self.cleanup_old_recordings()
                # 1時間ごとにクリーンアップ
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in recording cleanup task: {e}")
                # エラー時は30分後にリトライ
                await asyncio.sleep(1800)
    
    def clear_buffer(self, guild_id: int):
        """指定ギルドのバッファをクリア"""
        if guild_id in self.buffers:
            self.buffers[guild_id].clear()
            logger.info(f"Cleared audio buffer for guild {guild_id}")


# 簡易音声受信クラス（discord.sinksが利用できない場合のメイン実装）
class SimpleRecordingSink:
    """シンプルな録音管理クラス"""
    
    def __init__(self, recording_manager: RecordingManager, guild_id: int):
        self.recording_manager = recording_manager
        self.guild_id = guild_id
        self.is_recording = False
        self._recording_task = None
    
    def start_recording(self):
        """録音開始（ダミーデータでテスト）"""
        self.is_recording = True
        logger.info(f"Started recording for guild {self.guild_id}")
        
        # テスト用のダミー音声データを定期的に追加
        if not self._recording_task:
            self._recording_task = asyncio.create_task(self._simulate_audio())
    
    def stop_recording(self):
        """録音停止"""
        self.is_recording = False
        if self._recording_task:
            self._recording_task.cancel()
            self._recording_task = None
        logger.info(f"Stopped recording for guild {self.guild_id}")
    
    async def _simulate_audio(self):
        """音声データのシミュレート（テスト用）"""
        try:
            while self.is_recording:
                # ダミーの音声データを生成（無音）
                import numpy as np
                sample_rate = 48000
                duration = 0.1  # 100ms
                samples = int(sample_rate * duration)
                audio_data = np.zeros(samples, dtype=np.int16).tobytes()
                
                self.recording_manager.add_audio_data(self.guild_id, audio_data)
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass
    
    def cleanup(self):
        """クリーンアップ"""
        self.stop_recording()