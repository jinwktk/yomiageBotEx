"""
Audio Recorder v2 - シンプルな音声録音機能
- Discord音声録音
- リプレイ機能
"""

import asyncio
import logging
import tempfile
import wave
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
import io

import discord
from discord.sinks import WaveSink

logger = logging.getLogger(__name__)

class AudioRecorderV2:
    """シンプルな音声録音クラス"""
    
    def __init__(self, config: dict):
        self.config = config
        
        # 設定値
        self.max_duration = config.get('max_duration', 300)
        self.default_duration = config.get('default_duration', 30) 
        self.buffer_size = config.get('buffer_size', 10)
        
        # 録音状態管理
        self.recording_states: Dict[int, bool] = {}  # guild_id: is_recording
        self.audio_buffers: Dict[int, List[tuple]] = {}  # guild_id: [(audio_data, timestamp), ...]
        
        logger.info(f"Audio Recorder v2 initialized - Max duration: {self.max_duration}s")
    
    async def start_recording(self, voice_client: discord.VoiceClient) -> bool:
        """録音開始"""
        try:
            guild_id = voice_client.guild.id
            
            # 既に録音中の場合はスキップ
            if self.recording_states.get(guild_id, False):
                logger.debug(f"Already recording in guild {guild_id}")
                return True
            
            # WaveSinkを使用した録音開始
            sink = WaveSink()
            voice_client.start_recording(
                sink,
                self._recording_finished_callback,
                guild_id
            )
            
            self.recording_states[guild_id] = True
            logger.info(f"Started recording in guild {guild_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start recording: {e}", exc_info=True)
            return False
    
    async def stop_recording(self, voice_client: discord.VoiceClient) -> bool:
        """録音停止"""
        try:
            guild_id = voice_client.guild.id
            
            if not self.recording_states.get(guild_id, False):
                return False
            
            voice_client.stop_recording()
            self.recording_states[guild_id] = False
            
            logger.info(f"Stopped recording in guild {guild_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to stop recording: {e}", exc_info=True)
            return False
    
    async def _recording_finished_callback(self, sink: WaveSink, guild_id: int):
        """録音完了時のコールバック"""
        try:
            if not sink.audio_data:
                logger.warning("No audio data in recording")
                return
            
            # 全ユーザーの音声を結合
            combined_audio = self._combine_user_audio(sink.audio_data)
            
            if combined_audio:
                # バッファに保存
                timestamp = datetime.now()
                await self._save_to_buffer(guild_id, combined_audio, timestamp)
                
                logger.debug(f"Saved audio buffer for guild {guild_id}")
            
        except Exception as e:
            logger.error(f"Recording callback error: {e}", exc_info=True)
    
    def _combine_user_audio(self, audio_data: Dict[int, any]) -> Optional[bytes]:
        """複数ユーザーの音声を結合"""
        try:
            if not audio_data:
                return None
            
            # 最初のユーザーの音声を基準にする
            first_user_id = next(iter(audio_data.keys()))
            first_audio = audio_data[first_user_id]
            
            # 単一ユーザーの場合はそのまま返す
            if len(audio_data) == 1:
                # py-cordのWaveSinkから音声データを取得
                if hasattr(first_audio, 'file'):
                    return first_audio.file.getvalue()
                else:
                    # バイトデータの場合はそのまま返す
                    return first_audio if isinstance(first_audio, bytes) else None
            
            # 複数ユーザーの場合は単純に最初のユーザーのみ（簡略化）
            # 実際のミキシングは複雑なので、v2では簡略化
            logger.debug(f"Combined audio from {len(audio_data)} users (simplified)")
            if hasattr(first_audio, 'file'):
                return first_audio.file.getvalue()
            else:
                return first_audio if isinstance(first_audio, bytes) else None
            
        except Exception as e:
            logger.error(f"Audio combination error: {e}", exc_info=True)
            return None
    
    async def _save_to_buffer(self, guild_id: int, audio_data: bytes, timestamp: datetime):
        """音声データをバッファに保存"""
        try:
            if guild_id not in self.audio_buffers:
                self.audio_buffers[guild_id] = []
            
            # バッファに追加
            self.audio_buffers[guild_id].append((audio_data, timestamp))
            
            # バッファサイズ制限
            if len(self.audio_buffers[guild_id]) > self.buffer_size:
                self.audio_buffers[guild_id] = self.audio_buffers[guild_id][-self.buffer_size:]
            
            logger.debug(f"Audio buffer saved - Guild: {guild_id}, Size: {len(audio_data)} bytes")
            
        except Exception as e:
            logger.error(f"Buffer save error: {e}", exc_info=True)
    
    async def get_recent_audio(self, guild_id: int, duration: int = None) -> Optional[io.BytesIO]:
        """指定時間分の音声を取得"""
        try:
            if guild_id not in self.audio_buffers:
                return None
            
            duration = duration or self.default_duration
            buffers = self.audio_buffers[guild_id]
            
            if not buffers:
                return None
            
            # 最新のバッファから指定時間分を取得（簡略化版）
            # 実際の時間計算は複雑なので、最新のバッファのみを返す
            latest_buffer = buffers[-1][0]
            
            if not latest_buffer:
                return None
            
            # BytesIOオブジェクトとして返す
            audio_io = io.BytesIO(latest_buffer)
            audio_io.seek(0)
            
            logger.debug(f"Retrieved recent audio - Guild: {guild_id}, Size: {len(latest_buffer)} bytes")
            return audio_io
            
        except Exception as e:
            logger.error(f"Get recent audio error: {e}", exc_info=True)
            return None
    
    def is_recording(self, guild_id: int) -> bool:
        """録音中かチェック"""
        return self.recording_states.get(guild_id, False)
    
    def get_buffer_count(self, guild_id: int) -> int:
        """バッファ数を取得"""
        if guild_id not in self.audio_buffers:
            return 0
        return len(self.audio_buffers[guild_id])