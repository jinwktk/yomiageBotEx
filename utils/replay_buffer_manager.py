"""
リプレイバッファマネージャー - 高度な録音データ管理システム
RecordingCallbackManagerから受信したデータを効率的に管理・提供

Author: Claude Code
Date: 2025-08-30
"""

import asyncio
import logging
import time
import io
import wave
import array
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from collections import defaultdict, deque
import tempfile
import os

from .recording_callback_manager import recording_callback_manager, AudioChunk

logger = logging.getLogger(__name__)

@dataclass
class ReplayRequest:
    """リプレイリクエスト情報"""
    guild_id: int
    user_id: Optional[int]  # Noneの場合は全ユーザー
    duration_seconds: float
    request_time: float
    normalize: bool = True
    mix_users: bool = True

@dataclass 
class ReplayResult:
    """リプレイ結果データ"""
    audio_data: bytes
    total_duration: float
    user_count: int
    file_size: int
    sample_rate: int
    channels: int
    generation_time: float

class ReplayBufferManager:
    """
    リプレイバッファマネージャー
    RecordingCallbackManagerと連携し、高度なリプレイ機能を提供
    """
    
    def __init__(self, config: Dict[str, Any]):
        """初期化"""
        self.config = config
        self.replay_config = config.get("recording", {})
        self.logger = logging.getLogger(__name__)
        
        # バッファ管理設定
        self.max_duration = self.replay_config.get("max_duration", 300)  # 最大5分
        self.max_file_size_mb = self.replay_config.get("max_file_size_mb", 50)  # 最大50MB
        self.default_duration = self.replay_config.get("default_duration", 30)  # デフォルト30秒
        
        # リクエスト処理管理
        self.processing_requests: Dict[str, asyncio.Event] = {}
        self.request_lock = asyncio.Lock()
        
        # キャッシュ管理
        self.result_cache: Dict[str, ReplayResult] = {}
        self.cache_max_age = 60.0  # キャッシュ有効期間60秒
        
        # 統計情報
        self.stats = {
            'total_requests': 0,
            'successful_requests': 0,
            'failed_requests': 0,
            'cache_hits': 0,
            'average_generation_time': 0.0
        }
        
        self.logger.info("ReplayBufferManager initialized")
    
    def _generate_cache_key(self, request: ReplayRequest) -> str:
        """キャッシュキー生成"""
        user_key = f"user_{request.user_id}" if request.user_id else "all_users"
        return f"guild_{request.guild_id}_{user_key}_{request.duration_seconds}s_{int(request.request_time/10)*10}"
    
    async def get_replay_audio(
        self,
        guild_id: int,
        duration_seconds: float = None,
        user_id: Optional[int] = None,
        normalize: bool = True,
        mix_users: bool = True
    ) -> Optional[ReplayResult]:
        """
        リプレイ音声データを取得
        
        Args:
            guild_id: Guild ID
            duration_seconds: 取得する音声の長さ（秒）
            user_id: 特定ユーザーID（Noneで全ユーザー）
            normalize: 音声正規化の有効/無効
            mix_users: 複数ユーザーをミックスするか
        
        Returns:
            ReplayResult: 音声データと関連情報
        """
        start_time = time.time()
        
        if duration_seconds is None:
            duration_seconds = self.default_duration
        
        # リクエスト作成
        request = ReplayRequest(
            guild_id=guild_id,
            user_id=user_id,
            duration_seconds=duration_seconds,
            request_time=start_time,
            normalize=normalize,
            mix_users=mix_users
        )
        
        # 統計更新
        self.stats['total_requests'] += 1
        
        try:
            # キャッシュチェック
            cache_key = self._generate_cache_key(request)
            cached_result = await self._check_cache(cache_key)
            if cached_result:
                self.stats['cache_hits'] += 1
                return cached_result
            
            # 重複リクエスト処理
            async with self.request_lock:
                if cache_key in self.processing_requests:
                    # 既に処理中の同じリクエストを待機
                    self.logger.info(f"Waiting for existing request: {cache_key}")
                    await self.processing_requests[cache_key].wait()
                    return await self._check_cache(cache_key)
                
                # 新しいリクエストを処理開始
                self.processing_requests[cache_key] = asyncio.Event()
            
            # 音声データ取得・処理
            result = await self._process_replay_request(request)
            
            # キャッシュに保存
            if result:
                self.result_cache[cache_key] = result
                self.stats['successful_requests'] += 1
            else:
                self.stats['failed_requests'] += 1
            
            # 処理完了通知
            self.processing_requests[cache_key].set()
            del self.processing_requests[cache_key]
            
            # 統計更新
            generation_time = time.time() - start_time
            self._update_average_time(generation_time)
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error in get_replay_audio: {e}", exc_info=True)
            self.stats['failed_requests'] += 1
            
            # エラー時も処理完了通知
            if cache_key in self.processing_requests:
                self.processing_requests[cache_key].set()
                del self.processing_requests[cache_key]
            
            return None
    
    async def _check_cache(self, cache_key: str) -> Optional[ReplayResult]:
        """キャッシュチェック"""
        if cache_key not in self.result_cache:
            return None
        
        result = self.result_cache[cache_key]
        # キャッシュ有効期限チェック
        if time.time() - result.generation_time > self.cache_max_age:
            del self.result_cache[cache_key]
            return None
        
        return result
    
    async def _process_replay_request(self, request: ReplayRequest) -> Optional[ReplayResult]:
        """リプレイリクエストを処理"""
        try:
            # RecordingCallbackManagerから音声データを取得
            if not recording_callback_manager.is_initialized:
                self.logger.warning("RecordingCallbackManager is not initialized")
                return None
            
            # 音声チャンクを取得
            audio_chunks = await recording_callback_manager.get_recent_audio(
                guild_id=request.guild_id,
                duration_seconds=request.duration_seconds,
                user_id=request.user_id
            )
            
            if not audio_chunks:
                self.logger.info(f"No audio chunks found for guild {request.guild_id}")
                return None
            
            self.logger.info(f"Retrieved {len(audio_chunks)} audio chunks for processing")
            
            # ユーザー別にチャンクを分類
            user_chunks = defaultdict(list)
            for chunk in audio_chunks:
                user_chunks[chunk.user_id].append(chunk)
            
            # 音声データを処理
            if request.user_id:
                # 特定ユーザーのみ
                if request.user_id not in user_chunks:
                    self.logger.info(f"No audio data found for user {request.user_id}")
                    return None
                
                processed_audio = await self._process_user_audio(
                    user_chunks[request.user_id], 
                    request.normalize
                )
                user_count = 1
                
            else:
                # 全ユーザー処理
                if request.mix_users and len(user_chunks) > 1:
                    # ミックス処理
                    processed_audio = await self._mix_multiple_users(
                        user_chunks, 
                        request.normalize
                    )
                else:
                    # 最初のユーザーの音声のみ
                    first_user_chunks = list(user_chunks.values())[0]
                    processed_audio = await self._process_user_audio(
                        first_user_chunks,
                        request.normalize
                    )
                
                user_count = len(user_chunks)
            
            if not processed_audio or len(processed_audio) <= 44:
                self.logger.warning("Processed audio is empty or invalid")
                return None

            # 要求秒数を超える場合は末尾側を優先してトリム
            processed_audio = self._trim_audio_to_duration(
                processed_audio,
                request.duration_seconds,
            )
            
            # ファイルサイズチェック
            max_size_bytes = self.max_file_size_mb * 1024 * 1024
            if len(processed_audio) > max_size_bytes:
                self.logger.warning(f"Audio too large: {len(processed_audio)} bytes > {max_size_bytes}")
                # 音声を短縮
                processed_audio = await self._compress_audio(processed_audio, max_size_bytes)
            
            # 音声メタデータを取得
            sample_rate, channels, duration = await self._get_audio_metadata(processed_audio)
            
            # ReplayResult作成
            result = ReplayResult(
                audio_data=processed_audio,
                total_duration=duration,
                user_count=user_count,
                file_size=len(processed_audio),
                sample_rate=sample_rate,
                channels=channels,
                generation_time=time.time()
            )
            
            self.logger.info(f"Replay audio generated: {len(processed_audio)} bytes, {duration:.1f}s, {user_count} users")
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error processing replay request: {e}", exc_info=True)
            return None
    
    async def _process_user_audio(self, chunks: List[AudioChunk], normalize: bool) -> bytes:
        """単一ユーザーの音声チャンクを処理"""
        try:
            if not chunks:
                return b""
            
            # チャンクをタイムスタンプでソート
            sorted_chunks = sorted(chunks, key=lambda c: c.timestamp)

            combined_pcm = io.BytesIO()
            target_params: Optional[Tuple[int, int, int]] = None  # (channels, sample_width, sample_rate)
            last_end_time: Optional[float] = None

            for chunk in sorted_chunks:
                if not chunk.data or len(chunk.data) <= 44:
                    continue

                try:
                    with wave.open(io.BytesIO(chunk.data), "rb") as wav_file:
                        params = (
                            wav_file.getnchannels(),
                            wav_file.getsampwidth(),
                            wav_file.getframerate(),
                        )

                        if target_params is None:
                            target_params = params
                        elif params != target_params:
                            self.logger.warning(
                                "Skipping chunk with mismatched WAV params: expected=%s actual=%s",
                                target_params,
                                params,
                            )
                            continue

                        frame_count = wav_file.getnframes()
                        frames = wav_file.readframes(frame_count)
                        if frames:
                            # チャンク間の重複区間を除去（チェックポイント再開時の重複対策）
                            sample_rate = params[2]
                            channels = params[0]
                            sample_width = params[1]
                            duration = frame_count / sample_rate if sample_rate > 0 else 0.0
                            chunk_end = float(getattr(chunk, "timestamp", 0.0))
                            chunk_start = chunk_end - duration

                            if last_end_time is not None and chunk_start < last_end_time:
                                overlap_seconds = last_end_time - chunk_start
                                if overlap_seconds > 0 and sample_rate > 0:
                                    skip_frames = int(overlap_seconds * sample_rate)
                                    skip_bytes = skip_frames * channels * sample_width
                                    if skip_bytes >= len(frames):
                                        continue
                                    frames = frames[skip_bytes:]

                            combined_pcm.write(frames)
                            last_end_time = chunk_end if last_end_time is None else max(last_end_time, chunk_end)
                except Exception as e:
                    self.logger.warning(f"Failed to parse user audio chunk as WAV: {e}")
                    continue

            if target_params is None:
                return b""

            pcm_bytes = combined_pcm.getvalue()
            if not pcm_bytes:
                return b""

            channels, sample_width, sample_rate = target_params
            if normalize and sample_width == 2:
                pcm_bytes = self._normalize_pcm_16bit(pcm_bytes)

            output = io.BytesIO()
            with wave.open(output, "wb") as wav_out:
                wav_out.setnchannels(channels)
                wav_out.setsampwidth(sample_width)
                wav_out.setframerate(sample_rate)
                wav_out.writeframes(pcm_bytes)
            return output.getvalue()
            
        except Exception as e:
            self.logger.error(f"Error processing user audio: {e}")
            return b""

    def _normalize_pcm_16bit(self, pcm_bytes: bytes, target_peak_ratio: float = 0.90) -> bytes:
        """16bit PCMのピークを抑えてクリップ歪みを軽減"""
        try:
            samples = array.array("h")
            samples.frombytes(pcm_bytes)
            if not samples:
                return pcm_bytes

            peak = max(abs(s) for s in samples)
            if peak <= 0:
                return pcm_bytes

            target_peak = int(32767 * target_peak_ratio)
            if peak <= target_peak:
                return pcm_bytes

            scale = target_peak / peak
            normalized = array.array(
                "h",
                (
                    max(-32768, min(32767, int(sample * scale)))
                    for sample in samples
                ),
            )
            return normalized.tobytes()
        except Exception as e:
            self.logger.warning(f"PCM normalization failed, using original data: {e}")
            return pcm_bytes

    def _trim_audio_to_duration(self, audio_data: bytes, max_duration_seconds: float) -> bytes:
        """WAV音声の長さを上限秒数以内に収める（末尾優先）"""
        if max_duration_seconds <= 0:
            return audio_data
        try:
            with wave.open(io.BytesIO(audio_data), "rb") as wav_file:
                channels = wav_file.getnchannels()
                sample_width = wav_file.getsampwidth()
                sample_rate = wav_file.getframerate()
                total_frames = wav_file.getnframes()
                frames = wav_file.readframes(total_frames)

            if sample_rate <= 0:
                return audio_data

            max_frames = int(max_duration_seconds * sample_rate)
            if total_frames <= max_frames:
                return audio_data

            frame_size = channels * sample_width
            keep_bytes = max_frames * frame_size
            trimmed_frames = frames[-keep_bytes:]

            output = io.BytesIO()
            with wave.open(output, "wb") as wav_out:
                wav_out.setnchannels(channels)
                wav_out.setsampwidth(sample_width)
                wav_out.setframerate(sample_rate)
                wav_out.writeframes(trimmed_frames)
            return output.getvalue()
        except Exception as e:
            self.logger.warning(f"Failed to trim audio to {max_duration_seconds}s: {e}")
            return audio_data
    
    async def _mix_multiple_users(self, user_chunks: Dict[int, List[AudioChunk]], normalize: bool) -> bytes:
        """複数ユーザーの音声をミックス"""
        try:
            import numpy as np
            
            # 各ユーザーの音声を処理
            user_audio_data = {}
            for user_id, chunks in user_chunks.items():
                user_audio = await self._process_user_audio(chunks, False)  # ミックス前は正規化しない
                if len(user_audio) > 44:
                    user_audio_data[user_id] = user_audio
            
            if not user_audio_data:
                return b""
            
            if len(user_audio_data) == 1:
                # 1ユーザーのみの場合
                return list(user_audio_data.values())[0]
            
            # 複数ユーザーの音声をミックス
            mixed_audio = await self._numpy_audio_mix(user_audio_data)
            return mixed_audio
            
        except ImportError:
            self.logger.warning("NumPy not available for audio mixing")
            # フォールバック: 最初のユーザーの音声のみ
            if user_chunks:
                first_user_chunks = list(user_chunks.values())[0]
                return await self._process_user_audio(first_user_chunks, normalize)
            return b""
        
        except Exception as e:
            self.logger.error(f"Error mixing multiple users: {e}")
            return b""
    
    async def _numpy_audio_mix(self, user_audio_data: Dict[int, bytes]) -> bytes:
        """NumPyを使用した音声ミックス"""
        try:
            import numpy as np
            
            audio_arrays = []
            max_length = 0
            sample_rate = 48000
            
            # 各ユーザーの音声をnumpy配列に変換
            for user_id, audio_data in user_audio_data.items():
                try:
                    audio_io = io.BytesIO(audio_data)
                    with wave.open(audio_io, 'rb') as wav:
                        frames = wav.readframes(-1)
                        params = wav.getparams()
                        sample_rate = params.framerate
                        
                        # 16bit PCMとして読み込み
                        audio_array = np.frombuffer(frames, dtype=np.int16)
                        
                        # ステレオをモノラルに変換
                        if params.nchannels == 2:
                            audio_array = audio_array.reshape(-1, 2)
                            audio_array = np.mean(audio_array, axis=1).astype(np.int16)
                        
                        audio_arrays.append(audio_array)
                        max_length = max(max_length, len(audio_array))
                        
                except Exception as e:
                    self.logger.warning(f"Failed to process audio for user {user_id}: {e}")
                    continue
            
            if not audio_arrays:
                return b""
            
            # 配列を同じ長さに調整
            padded_arrays = []
            for arr in audio_arrays:
                if len(arr) < max_length:
                    padded = np.zeros(max_length, dtype=np.int16)
                    padded[:len(arr)] = arr
                    padded_arrays.append(padded)
                else:
                    padded_arrays.append(arr[:max_length])
            
            # ミックス（平均値）
            mixed_array = np.zeros(max_length, dtype=np.float32)
            for arr in padded_arrays:
                mixed_array += arr.astype(np.float32)
            
            mixed_array = mixed_array / len(padded_arrays)
            mixed_array *= 0.8  # 音量調整
            mixed_array = np.clip(mixed_array, -32767, 32767)
            mixed_array = mixed_array.astype(np.int16)
            
            # WAVファイルとして出力
            output = io.BytesIO()
            with wave.open(output, 'wb') as wav_out:
                wav_out.setnchannels(1)  # モノラル
                wav_out.setsampwidth(2)  # 16bit
                wav_out.setframerate(sample_rate)
                wav_out.writeframes(mixed_array.tobytes())
            
            return output.getvalue()
            
        except Exception as e:
            self.logger.error(f"NumPy audio mixing failed: {e}")
            return b""
    
    def _fix_wav_header(self, wav_data: bytes, pcm_size: int) -> bytes:
        """WAVヘッダーのファイルサイズ情報を修正"""
        try:
            if len(wav_data) < 44:
                return wav_data
            
            # WAVヘッダーを修正
            wav_array = bytearray(wav_data)
            
            # ChunkSize (ファイル全体サイズ - 8)
            total_size = len(wav_data) - 8
            wav_array[4:8] = total_size.to_bytes(4, 'little')
            
            # Subchunk2Size (PCMデータサイズ)
            wav_array[40:44] = pcm_size.to_bytes(4, 'little')
            
            return bytes(wav_array)
            
        except Exception as e:
            self.logger.warning(f"Failed to fix WAV header: {e}")
            return wav_data
    
    async def _compress_audio(self, audio_data: bytes, max_size: int) -> bytes:
        """音声データを圧縮"""
        try:
            # 単純な切り詰め（より高度な処理も可能）
            compression_ratio = max_size / len(audio_data)
            if compression_ratio >= 1.0:
                return audio_data
            
            # WAVヘッダーを保持して音声部分を圧縮
            if len(audio_data) > 44:
                header = audio_data[:44]
                pcm_data = audio_data[44:]
                compressed_pcm_size = int(len(pcm_data) * compression_ratio * 0.9)  # 90%まで圧縮
                compressed_pcm = pcm_data[:compressed_pcm_size]
                
                # ヘッダーを修正
                compressed_audio = header + compressed_pcm
                return self._fix_wav_header(compressed_audio, len(compressed_pcm))
            
            return audio_data[:max_size]
            
        except Exception as e:
            self.logger.error(f"Audio compression failed: {e}")
            return audio_data
    
    async def _get_audio_metadata(self, audio_data: bytes) -> Tuple[int, int, float]:
        """音声メタデータを取得"""
        try:
            audio_io = io.BytesIO(audio_data)
            with wave.open(audio_io, 'rb') as wav:
                params = wav.getparams()
                duration = params.nframes / params.framerate if params.framerate > 0 else 0.0
                return params.framerate, params.nchannels, duration
        except Exception:
            # デフォルト値
            return 48000, 1, 0.0
    
    def _update_average_time(self, new_time: float):
        """平均生成時間を更新"""
        total_requests = self.stats['successful_requests'] + self.stats['failed_requests']
        if total_requests > 0:
            current_avg = self.stats['average_generation_time']
            self.stats['average_generation_time'] = (current_avg * (total_requests - 1) + new_time) / total_requests
    
    async def clear_cache(self):
        """キャッシュをクリア"""
        self.result_cache.clear()
        self.logger.info("ReplayBufferManager cache cleared")
    
    async def get_stats(self) -> Dict[str, Any]:
        """統計情報を取得"""
        return {
            **self.stats,
            'cache_size': len(self.result_cache),
            'active_requests': len(self.processing_requests)
        }
    
    async def cleanup(self):
        """クリーンアップ処理"""
        try:
            # 処理中のリクエストを待機
            for event in self.processing_requests.values():
                event.set()
            
            # キャッシュクリア
            await self.clear_cache()
            
            self.logger.info("ReplayBufferManager cleanup completed")
            
        except Exception as e:
            self.logger.error(f"ReplayBufferManager cleanup error: {e}")

# グローバルインスタンス（後で初期化）
replay_buffer_manager = None

def initialize_replay_buffer_manager(config: Dict[str, Any]):
    """ReplayBufferManagerを初期化"""
    global replay_buffer_manager
    if replay_buffer_manager is None:
        replay_buffer_manager = ReplayBufferManager(config)
    return replay_buffer_manager
