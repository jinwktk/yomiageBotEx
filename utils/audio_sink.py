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
        
    def get_audio_sink(self, guild_id: int) -> AudioSink:
        """ギルド用の音声シンクを取得"""
        if guild_id not in self.guild_sinks:
            def audio_callback(user_id: int, audio_data: bytes):
                self.recording_manager.add_audio_data(guild_id, audio_data)
                
            self.guild_sinks[guild_id] = AudioSink(audio_callback)
        
        return self.guild_sinks[guild_id]
    
    def start_recording(self, guild_id: int, voice_client: discord.VoiceClient):
        """録音開始"""
        try:
            sink = self.get_audio_sink(guild_id)
            sink.is_recording = True
            
            # voice_clientに音声受信を開始
            # 注意: discord.pyのバージョンによって方法が異なる場合がある
            if hasattr(voice_client, 'start_recording'):
                voice_client.start_recording(sink)
                logger.info(f"RealTimeRecorder: Started real-time recording for guild {guild_id}")
            else:
                logger.warning(f"RealTimeRecorder: voice_client.start_recording not available")
                # フォールバック: ダミーデータでの録音シミュレーション
                asyncio.create_task(self._simulate_recording(guild_id))
                
        except Exception as e:
            logger.error(f"RealTimeRecorder: Failed to start recording: {e}")
            # エラー時はシミュレーション録音にフォールバック
            asyncio.create_task(self._simulate_recording(guild_id))
    
    def stop_recording(self, guild_id: int, voice_client: Optional[discord.VoiceClient] = None):
        """録音停止"""
        try:
            if guild_id in self.guild_sinks:
                sink = self.guild_sinks[guild_id]
                sink.is_recording = False
                
                if voice_client and hasattr(voice_client, 'stop_recording'):
                    voice_client.stop_recording()
                    
                logger.info(f"RealTimeRecorder: Stopped recording for guild {guild_id}")
                
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