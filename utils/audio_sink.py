"""
Discord音声受信用のAudioSinkクラス
discord.pyでの実際の音声データ受信を処理
"""

import asyncio
import logging
import wave
import io
from typing import Dict, Any, Optional, Callable
from pathlib import Path

import discord
import numpy as np

logger = logging.getLogger(__name__)


class AudioSink:
    """Discord音声を受信するためのシンククラス"""
    
    def __init__(self, callback: Callable[[int, bytes], None]):
        """
        Args:
            callback: 音声データを受信した際に呼び出される関数
                     (user_id: int, audio_data: bytes) -> None
        """
        self.callback = callback
        self.is_recording = False
        self.users = {}  # user_id -> user情報
        
    def wants_opus(self) -> bool:
        """Opus音声データを受信するかどうか"""
        return False  # PCMデータを受信
    
    def write(self, data, user):
        """音声データの受信処理"""
        if not self.is_recording:
            return
            
        try:
            if user and not user.bot and data:
                # PCMデータを取得
                pcm_data = data.pcm if hasattr(data, 'pcm') else data
                if pcm_data:
                    self.callback(user.id, pcm_data)
                    
        except Exception as e:
            logger.error(f"AudioSink: Error in write: {e}")
    
    def cleanup(self):
        """クリーンアップ処理"""
        self.is_recording = False
        self.users.clear()


class RealTimeAudioRecorder:
    """リアルタイム音声録音管理クラス"""
    
    def __init__(self, recording_manager):
        self.recording_manager = recording_manager
        self.audio_sink = None
        self.guild_sinks: Dict[int, AudioSink] = {}
        self.sample_rate = 48000  # Discordの標準サンプルレート
        self.channels = 2  # ステレオ
        self.sample_width = 2  # 16-bit
        self.use_enhanced_client = True  # 拡張VoiceClientを使用
        self.active_recordings: Dict[int, asyncio.Task] = {}  # ギルドごとの録音タスク
        
    def get_audio_sink(self, guild_id: int) -> AudioSink:
        """ギルド用の音声シンクを取得"""
        if guild_id not in self.guild_sinks:
            def audio_callback(user_id: int, audio_data: bytes):
                self.recording_manager.add_audio_data(guild_id, audio_data, user_id)
                
            self.guild_sinks[guild_id] = AudioSink(audio_callback)
        
        return self.guild_sinks[guild_id]
    
    def start_recording(self, guild_id: int, voice_client: discord.VoiceClient):
        """録音開始 - 定期的な録音サイクルを開始"""
        try:
            # 既存の録音タスクがあれば停止
            if guild_id in self.active_recordings:
                self.active_recordings[guild_id].cancel()
            
            # 定期録音タスクを開始
            task = asyncio.create_task(self._continuous_recording_cycle(guild_id, voice_client))
            self.active_recordings[guild_id] = task
            logger.info(f"RealTimeRecorder: Started continuous recording cycle for guild {guild_id}")
                
        except Exception as e:
            logger.error(f"RealTimeRecorder: Failed to start recording: {e}")
            # エラー時はシミュレーション録音にフォールバック
            asyncio.create_task(self._simulate_recording(guild_id))
    
    async def _continuous_recording_cycle(self, guild_id: int, voice_client: discord.VoiceClient):
        """継続的な録音サイクル（10秒ごとに録音停止・再開）"""
        try:
            while True:
                # py-cordのWaveSinkを使用した録音
                if hasattr(voice_client, 'start_recording') and callable(voice_client.start_recording):
                    from discord.sinks import WaveSink
                    sink = WaveSink()
                    
                    # 録音完了時のコールバック
                    async def finished_callback(sink_obj, guild_id_param):
                        """録音完了時の処理"""
                        try:
                            for user_id, audio in sink_obj.audio_data.items():
                                if audio.file:
                                    audio.file.seek(0)
                                    audio_data = audio.file.read()
                                    
                                    if audio_data:
                                        # 録音データをRecordingManagerに追加
                                        self.recording_manager.add_audio_data(guild_id_param, audio_data, user_id)
                                        logger.debug(f"Added audio data for user {user_id}: {len(audio_data)} bytes")
                        except Exception as e:
                            logger.error(f"Error in finished_callback: {e}")
                    
                    # 録音開始
                    voice_client.start_recording(sink, finished_callback, guild_id)
                    logger.debug(f"RealTimeRecorder: Started 10s recording segment for guild {guild_id}")
                    
                    # 10秒待機
                    await asyncio.sleep(10)
                    
                    # 録音停止（これでfinished_callbackが呼ばれる）
                    if hasattr(voice_client, 'stop_recording') and voice_client.recording:
                        voice_client.stop_recording()
                        logger.debug(f"RealTimeRecorder: Stopped 10s recording segment for guild {guild_id}")
                    
                    # 短時間待機してから次のサイクル
                    await asyncio.sleep(0.5)
                else:
                    logger.warning(f"RealTimeRecorder: Voice client lacks recording capability")
                    break
                    
        except asyncio.CancelledError:
            logger.info(f"RealTimeRecorder: Recording cycle cancelled for guild {guild_id}")
        except Exception as e:
            logger.error(f"RealTimeRecorder: Error in recording cycle: {e}")
    
    def stop_recording(self, guild_id: int, voice_client: Optional[discord.VoiceClient] = None):
        """録音停止"""
        try:
            # 継続的な録音タスクを停止
            if guild_id in self.active_recordings:
                self.active_recordings[guild_id].cancel()
                del self.active_recordings[guild_id]
                logger.info(f"RealTimeRecorder: Cancelled recording cycle for guild {guild_id}")
            
            # 現在の録音を停止
            if voice_client and hasattr(voice_client, 'stop_recording') and hasattr(voice_client, 'recording') and voice_client.recording:
                voice_client.stop_recording()
                logger.info(f"RealTimeRecorder: Stopped py-cord recording for guild {guild_id}")
            
            # シンクのクリーンアップ
            if guild_id in self.guild_sinks:
                sink = self.guild_sinks[guild_id]
                sink.is_recording = False
                logger.info(f"RealTimeRecorder: Cleaned up sink for guild {guild_id}")
                
        except Exception as e:
            logger.error(f"RealTimeRecorder: Failed to stop recording: {e}")
    
    async def _simulate_recording(self, guild_id: int):
        """録音シミュレーション（フォールバック）"""
        try:
            sink = self.guild_sinks.get(guild_id)
            if not sink:
                return
                
            logger.info(f"RealTimeRecorder: Starting simulated recording for guild {guild_id}")
            
            while sink and sink.is_recording:
                # ダミーの音声データを生成（無音）
                duration = 0.1  # 100ms
                samples = int(self.sample_rate * duration)
                
                # 16-bit PCMデータを生成（無音）
                audio_data = np.zeros(samples * self.channels, dtype=np.int16).tobytes()
                
                # コールバックを呼び出し
                if sink.callback:
                    sink.callback(0, audio_data)  # user_id=0でダミーデータ
                
                await asyncio.sleep(duration)
                
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"RealTimeRecorder: Error in simulated recording: {e}")
    
    def cleanup(self):
        """クリーンアップ"""
        # 全ての録音タスクを停止
        for task in self.active_recordings.values():
            task.cancel()
        self.active_recordings.clear()
        
        # シンクのクリーンアップ
        for sink in self.guild_sinks.values():
            sink.cleanup()
        self.guild_sinks.clear()


def create_wav_from_pcm(pcm_data: bytes, sample_rate: int = 48000, channels: int = 2, sample_width: int = 2) -> bytes:
    """PCMデータからWAVファイルのバイト配列を生成"""
    try:
        buffer = io.BytesIO()
        
        with wave.open(buffer, 'wb') as wav_file:
            wav_file.setnchannels(channels)
            wav_file.setsampwidth(sample_width)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm_data)
        
        return buffer.getvalue()
        
    except Exception as e:
        logger.error(f"Failed to create WAV from PCM: {e}")
        return b""


def convert_opus_to_pcm(opus_data: bytes) -> bytes:
    """Opus音声データをPCMに変換（将来的な実装用）"""
    # 実際の実装では、opus-pythonライブラリなどを使用
    # 現在は簡易的にそのまま返す
    logger.warning("Opus to PCM conversion not implemented")
    return opus_data