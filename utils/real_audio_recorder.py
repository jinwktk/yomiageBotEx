"""
py-cordのdiscord.sinksを使った実際の音声録音実装
"""

import asyncio
import logging
import time
import io
from typing import Dict, Callable, Optional

try:
    import discord
    from discord.sinks import WaveSink
    PYCORD_AVAILABLE = True
except ImportError:
    PYCORD_AVAILABLE = False
    logging.warning("py-cord not available. Real audio recording will not work.")

logger = logging.getLogger(__name__)


class RealAudioRecorder:
    """py-cordのWaveSinkを使った実際の音声録音"""
    
    def __init__(self, audio_callback: Callable[[int, bytes], None]):
        """
        Args:
            audio_callback: 音声データ受信時のコールバック (user_id, pcm_data)
        """
        self.audio_callback = audio_callback
        self.recording_connections: Dict[int, discord.VoiceClient] = {}
        self.is_available = PYCORD_AVAILABLE
        
    def start_recording(self, guild_id: int, voice_client: discord.VoiceClient) -> bool:
        """実際の音声録音を開始"""
        if not self.is_available:
            logger.warning("py-cord not available, cannot start real recording")
            return False
            
        try:
            # WaveSinkを作成
            sink = WaveSink()
            
            # 録音開始
            voice_client.start_recording(
                sink, 
                self._finished_callback,
                guild_id
            )
            
            self.recording_connections[guild_id] = voice_client
            logger.info(f"RealAudioRecorder: Started recording for guild {guild_id}")
            return True
            
        except Exception as e:
            logger.error(f"RealAudioRecorder: Failed to start recording: {e}")
            return False
    
    def stop_recording(self, guild_id: int, voice_client: discord.VoiceClient):
        """音声録音を停止"""
        try:
            if guild_id in self.recording_connections:
                voice_client.stop_recording()
                del self.recording_connections[guild_id]
                logger.info(f"RealAudioRecorder: Stopped recording for guild {guild_id}")
        except Exception as e:
            logger.error(f"RealAudioRecorder: Failed to stop recording: {e}")
    
    async def _finished_callback(self, sink: WaveSink, guild_id: int):
        """録音完了時のコールバック"""
        try:
            logger.debug(f"RealAudioRecorder: Processing audio data for {len(sink.audio_data)} users")
            
            for user_id, audio in sink.audio_data.items():
                if audio.file:
                    # 音声データを読み取り
                    audio.file.seek(0)
                    audio_data = audio.file.read()
                    
                    if audio_data:
                        # コールバックに音声データを渡す
                        self.audio_callback(user_id, audio_data)
                        logger.debug(f"RealAudioRecorder: Processed {len(audio_data)} bytes for user {user_id}")
                    else:
                        logger.debug(f"RealAudioRecorder: No audio data for user {user_id}")
                        
        except Exception as e:
            logger.error(f"RealAudioRecorder: Error in finished callback: {e}")


class RealEnhancedVoiceClient(discord.VoiceClient):
    """実際の音声録音機能を追加したVoiceClient（py-cord版）"""
    
    def __init__(self, client, channel):
        super().__init__(client, channel)
        self.recorder: Optional[RealAudioRecorder] = None
        
    def start_recording(self, callback: Callable[[int, bytes], None]) -> bool:
        """録音開始"""
        if not self.is_connected():
            raise RuntimeError("Not connected to voice channel")
            
        if self.recorder:
            self.recorder.stop_recording(self.guild.id, self)
            
        self.recorder = RealAudioRecorder(callback)
        success = self.recorder.start_recording(self.guild.id, self)
        
        if success:
            logger.info("RealEnhancedVoiceClient: Started recording")
        else:
            logger.warning("RealEnhancedVoiceClient: Failed to start recording, falling back")
            
        return success
        
    def stop_recording(self):
        """録音停止"""
        if self.recorder:
            self.recorder.stop_recording(self.guild.id, self)
            self.recorder = None
            logger.info("RealEnhancedVoiceClient: Stopped recording")
            
    async def disconnect(self, *, force: bool = False):
        """切断時にレコーダーも停止"""
        if self.recorder:
            self.recorder.stop_recording(self.guild.id, self)
            
        await super().disconnect(force=force)