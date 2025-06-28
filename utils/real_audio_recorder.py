"""
リアルな音声録音システム（py-cord + WaveSink統合版）
bot_simple.pyの動作する録音機能をutils/に移植
"""

import asyncio
import logging
import time
import io
from typing import Dict, Callable, Optional, Any

try:
    import discord
    from discord.sinks import WaveSink
    PYCORD_AVAILABLE = True
except ImportError:
    PYCORD_AVAILABLE = False
    logging.warning("py-cord not available. Real audio recording will not work.")

logger = logging.getLogger(__name__)


class RealTimeAudioRecorder:
    """リアルタイム音声録音管理クラス（bot_simple.py統合版）"""
    
    def __init__(self, recording_manager):
        self.recording_manager = recording_manager
        self.connections: Dict[int, discord.VoiceClient] = {}
        self.user_audio_buffers: Dict[int, list] = {}
        self.active_recordings: Dict[int, asyncio.Task] = {}
        self.BUFFER_EXPIRATION = 900  # 15分
        self.is_available = PYCORD_AVAILABLE
        
    async def start_recording(self, guild_id: int, voice_client: discord.VoiceClient):
        """録音開始"""
        if not self.is_available:
            logger.warning("py-cord not available, cannot start real recording")
            return
            
        try:
            # 既存の録音タスクがあれば停止
            if guild_id in self.active_recordings:
                self.active_recordings[guild_id].cancel()
            
            # WaveSinkを使用した録音開始
            sink = WaveSink()
            self.connections[guild_id] = voice_client
            voice_client.start_recording(sink, self._finished_callback, guild_id)
            logger.info(f"RealTimeRecorder: Started recording for guild {guild_id}")
                
        except Exception as e:
            logger.error(f"RealTimeRecorder: Failed to start recording: {e}")
    
    async def stop_recording(self, guild_id: int, voice_client: Optional[discord.VoiceClient] = None):
        """録音停止"""
        try:
            if guild_id in self.connections:
                vc = self.connections[guild_id]
                if hasattr(vc, 'recording') and vc.recording:
                    vc.stop_recording()
                del self.connections[guild_id]
                logger.info(f"RealTimeRecorder: Stopped recording for guild {guild_id}")
        except Exception as e:
            logger.error(f"RealTimeRecorder: Failed to stop recording: {e}")
    
    async def _finished_callback(self, sink: WaveSink, guild_id: int):
        """録音完了時のコールバック（bot_simple.pyから移植）"""
        try:
            for user_id, audio in sink.audio_data.items():
                if audio.file:
                    audio.file.seek(0)
                    audio_data = audio.file.read()
                    
                    if audio_data:
                        user_audio_buffer = io.BytesIO(audio_data)
                        
                        # バッファに追加
                        if user_id not in self.user_audio_buffers:
                            self.user_audio_buffers[user_id] = []
                        self.user_audio_buffers[user_id].append((user_audio_buffer, time.time()))
                        
                        # RecordingManagerにも追加
                        if self.recording_manager:
                            self.recording_manager.add_audio_data(guild_id, audio_data, user_id)
                        
                        logger.debug(f"RealTimeRecorder: Added audio buffer for user {user_id}")
                        
        except Exception as e:
            logger.error(f"RealTimeRecorder: Error in finished_callback: {e}")


    async def clean_old_buffers(self):
        """古いバッファを削除（bot_simple.pyから移植）"""
        current_time = time.time()
        for user_id in list(self.user_audio_buffers.keys()):
            self.user_audio_buffers[user_id] = [
                (buffer, timestamp) for buffer, timestamp in self.user_audio_buffers[user_id]
                if current_time - timestamp <= self.BUFFER_EXPIRATION
            ]
            
            if not self.user_audio_buffers[user_id]:
                del self.user_audio_buffers[user_id]
    
    def get_user_audio_buffers(self, user_id: Optional[int] = None) -> Dict[int, list]:
        """ユーザーの音声バッファを取得"""
        if user_id:
            return {user_id: self.user_audio_buffers.get(user_id, [])}
        return self.user_audio_buffers.copy()
    
    def cleanup(self):
        """クリーンアップ"""
        # 全ての録音タスクを停止
        for task in self.active_recordings.values():
            task.cancel()
        self.active_recordings.clear()
        
        # 接続をクリア
        self.connections.clear()
        self.user_audio_buffers.clear()


class RealEnhancedVoiceClient(discord.VoiceClient):
    """py-cord の WaveSink を使用したリアル音声録音クライアント"""
    
    def __init__(self, client: discord.Client, channel: discord.abc.Connectable):
        super().__init__(client, channel)
        self.recording_manager = None
        self.guild_id = channel.guild.id
        
    def set_recording_manager(self, recording_manager):
        """録音マネージャーを設定"""
        self.recording_manager = recording_manager