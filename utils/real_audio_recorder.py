"""
リアルな音声録音システム（py-cord + WaveSink統合版）
bot_simple.pyの動作する録音機能をutils/に移植
"""

import asyncio
import logging
import time
import io
import json
import base64
from pathlib import Path
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
        # Guild別のユーザー音声バッファ: {guild_id: {user_id: [(buffer, timestamp), ...]}}
        self.guild_user_buffers: Dict[int, Dict[int, list]] = {}
        self.active_recordings: Dict[int, asyncio.Task] = {}
        self.BUFFER_EXPIRATION = 900  # 15分
        self.is_available = PYCORD_AVAILABLE
        
        # 永続化設定
        self.buffer_file = Path("data/audio_buffers.json")
        self.buffer_file.parent.mkdir(parents=True, exist_ok=True)
        
        # 起動時にバッファを復元
        self.load_buffers()
        
    async def start_recording(self, guild_id: int, voice_client: discord.VoiceClient):
        """録音開始"""
        if not self.is_available:
            logger.warning("py-cord not available, cannot start real recording")
            return
            
        try:
            # 既存の録音タスクがあれば停止
            if guild_id in self.active_recordings:
                self.active_recordings[guild_id].cancel()
            
            # 既に録音中かチェック
            if hasattr(voice_client, 'recording') and voice_client.recording:
                logger.info(f"RealTimeRecorder: Already recording for guild {guild_id}, stopping first")
                voice_client.stop_recording()
                await asyncio.sleep(0.5)  # 停止を待つ
            
            # WaveSinkを使用した録音開始
            sink = WaveSink()
            self.connections[guild_id] = voice_client
            
            # コールバック関数をラムダで包む（guild_idを渡すため）
            def callback(sink_obj):
                self._finished_callback(sink_obj, guild_id)
            
            voice_client.start_recording(sink, callback)
            logger.info(f"RealTimeRecorder: Started recording for guild {guild_id} with channel {voice_client.channel.name}")
            logger.info(f"RealTimeRecorder: Voice client recording status: {voice_client.recording}")
                
        except Exception as e:
            logger.error(f"RealTimeRecorder: Failed to start recording: {e}", exc_info=True)
    
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
    
    def _finished_callback(self, sink: WaveSink, guild_id: int):
        """録音完了時のコールバック（bot_simple.pyから移植）"""
        try:
            logger.info(f"RealTimeRecorder: Finished callback called for guild {guild_id}")
            logger.info(f"RealTimeRecorder: Sink audio_data keys: {list(sink.audio_data.keys())}")
            
            audio_count = 0
            for user_id, audio in sink.audio_data.items():
                logger.info(f"RealTimeRecorder: Processing audio for user {user_id}")
                if audio.file:
                    audio.file.seek(0)
                    audio_data = audio.file.read()
                    
                    logger.info(f"RealTimeRecorder: Audio data size for user {user_id}: {len(audio_data)} bytes")
                    
                    if audio_data and len(audio_data) > 44:  # WAVヘッダー以上のサイズ
                        user_audio_buffer = io.BytesIO(audio_data)
                        
                        # Guild別バッファに追加
                        if guild_id not in self.guild_user_buffers:
                            self.guild_user_buffers[guild_id] = {}
                        if user_id not in self.guild_user_buffers[guild_id]:
                            self.guild_user_buffers[guild_id][user_id] = []
                        self.guild_user_buffers[guild_id][user_id].append((user_audio_buffer, time.time()))
                        
                        # RecordingManagerにも追加
                        if self.recording_manager:
                            self.recording_manager.add_audio_data(guild_id, audio_data, user_id)
                        
                        logger.info(f"RealTimeRecorder: Added audio buffer for guild {guild_id}, user {user_id} ({len(audio_data)} bytes)")
                        audio_count += 1
                    else:
                        logger.warning(f"RealTimeRecorder: Audio data too small for user {user_id}: {len(audio_data)} bytes")
                else:
                    logger.warning(f"RealTimeRecorder: No audio.file for user {user_id}")
            
            logger.info(f"RealTimeRecorder: Processed {audio_count} audio files in callback")
            
            # バッファを永続化
            if audio_count > 0:
                self.save_buffers()
                        
        except Exception as e:
            logger.error(f"RealTimeRecorder: Error in finished_callback: {e}", exc_info=True)


    async def clean_old_buffers(self, guild_id: Optional[int] = None):
        """古いバッファを削除（Guild別対応）"""
        current_time = time.time()
        
        if guild_id:
            # 特定のGuildのみクリーンアップ
            if guild_id in self.guild_user_buffers:
                for user_id in list(self.guild_user_buffers[guild_id].keys()):
                    self.guild_user_buffers[guild_id][user_id] = [
                        (buffer, timestamp) for buffer, timestamp in self.guild_user_buffers[guild_id][user_id]
                        if current_time - timestamp <= self.BUFFER_EXPIRATION
                    ]
                    
                    if not self.guild_user_buffers[guild_id][user_id]:
                        del self.guild_user_buffers[guild_id][user_id]
                
                if not self.guild_user_buffers[guild_id]:
                    del self.guild_user_buffers[guild_id]
        else:
            # 全Guildをクリーンアップ
            for gid in list(self.guild_user_buffers.keys()):
                for user_id in list(self.guild_user_buffers[gid].keys()):
                    self.guild_user_buffers[gid][user_id] = [
                        (buffer, timestamp) for buffer, timestamp in self.guild_user_buffers[gid][user_id]
                        if current_time - timestamp <= self.BUFFER_EXPIRATION
                    ]
                    
                    if not self.guild_user_buffers[gid][user_id]:
                        del self.guild_user_buffers[gid][user_id]
                
                if not self.guild_user_buffers[gid]:
                    del self.guild_user_buffers[gid]
        
        # バッファが変更された場合は保存
        self.save_buffers()
    
    def get_user_audio_buffers(self, guild_id: int, user_id: Optional[int] = None) -> Dict[int, list]:
        """ユーザーの音声バッファを取得（Guild別対応）"""
        logger.info(f"RealTimeRecorder: Getting buffers for guild {guild_id}, user {user_id}")
        
        if guild_id not in self.guild_user_buffers:
            logger.info(f"RealTimeRecorder: No buffers for guild {guild_id}")
            return {}
        
        guild_buffers = self.guild_user_buffers[guild_id]
        logger.info(f"RealTimeRecorder: Available users in guild {guild_id}: {list(guild_buffers.keys())}")
        
        for uid, buffers in guild_buffers.items():
            logger.info(f"RealTimeRecorder: Guild {guild_id}, User {uid} has {len(buffers)} buffers")
        
        if user_id:
            result = {user_id: guild_buffers.get(user_id, [])}
            logger.info(f"RealTimeRecorder: Returning buffers for guild {guild_id}, user {user_id}: {len(result[user_id])} items")
            return result
        return guild_buffers.copy()
    
    def debug_recording_status(self, guild_id: int):
        """録音状況のデバッグ情報を出力"""
        try:
            if guild_id in self.connections:
                vc = self.connections[guild_id]
                logger.info(f"RealTimeRecorder Debug: Guild {guild_id}")
                logger.info(f"  - Voice client exists: {vc is not None}")
                logger.info(f"  - Is connected: {vc.is_connected() if vc else False}")
                logger.info(f"  - Is recording: {getattr(vc, 'recording', False)}")
                logger.info(f"  - Channel: {vc.channel.name if vc and vc.channel else 'None'}")
                logger.info(f"  - Channel members: {[m.display_name for m in vc.channel.members] if vc and vc.channel else []}")
            else:
                logger.info(f"RealTimeRecorder Debug: No connection for guild {guild_id}")
        except Exception as e:
            logger.error(f"RealTimeRecorder Debug: Error getting status: {e}")
    
    def save_buffers(self):
        """音声バッファを永続化（最新20件のみ）"""
        try:
            # バッファサイズを制限
            simplified_buffers = {}
            
            for guild_id, users in self.guild_user_buffers.items():
                simplified_buffers[str(guild_id)] = {}
                
                for user_id, buffers in users.items():
                    # 最新5件のみ保存
                    recent_buffers = sorted(buffers, key=lambda x: x[1])[-5:]
                    encoded_buffers = []
                    
                    for buffer, timestamp in recent_buffers:
                        try:
                            buffer.seek(0)
                            audio_data = buffer.read()
                            # Base64エンコードで文字列化
                            encoded_data = base64.b64encode(audio_data).decode('utf-8')
                            encoded_buffers.append({
                                'data': encoded_data,
                                'timestamp': timestamp,
                                'size': len(audio_data)
                            })
                        except Exception as e:
                            logger.warning(f"Failed to encode buffer for user {user_id}: {e}")
                            continue
                    
                    if encoded_buffers:
                        simplified_buffers[str(guild_id)][str(user_id)] = encoded_buffers
            
            # JSONファイルに保存
            with open(self.buffer_file, 'w', encoding='utf-8') as f:
                json.dump(simplified_buffers, f, indent=2)
            
            total_buffers = sum(len(users) for users in simplified_buffers.values())
            logger.info(f"RealTimeRecorder: Saved {total_buffers} user buffers to {self.buffer_file}")
            
        except Exception as e:
            logger.error(f"RealTimeRecorder: Failed to save buffers: {e}")
    
    def load_buffers(self):
        """永続化された音声バッファを復元"""
        try:
            if not self.buffer_file.exists():
                logger.info("RealTimeRecorder: No saved buffers found")
                return
            
            with open(self.buffer_file, 'r', encoding='utf-8') as f:
                saved_buffers = json.load(f)
            
            current_time = time.time()
            restored_count = 0
            
            for guild_id_str, users in saved_buffers.items():
                guild_id = int(guild_id_str)
                self.guild_user_buffers[guild_id] = {}
                
                for user_id_str, buffers in users.items():
                    user_id = int(user_id_str)
                    user_buffers = []
                    
                    for buffer_data in buffers:
                        timestamp = buffer_data['timestamp']
                        
                        # 期限切れバッファをスキップ
                        if current_time - timestamp > self.BUFFER_EXPIRATION:
                            continue
                        
                        try:
                            # Base64デコードしてBytesIOに復元
                            audio_data = base64.b64decode(buffer_data['data'])
                            audio_buffer = io.BytesIO(audio_data)
                            user_buffers.append((audio_buffer, timestamp))
                            restored_count += 1
                            
                        except Exception as e:
                            logger.warning(f"Failed to decode buffer for user {user_id}: {e}")
                            continue
                    
                    if user_buffers:
                        self.guild_user_buffers[guild_id][user_id] = user_buffers
                
                # 空のギルドを削除
                if not self.guild_user_buffers[guild_id]:
                    del self.guild_user_buffers[guild_id]
            
            logger.info(f"RealTimeRecorder: Restored {restored_count} audio buffers from disk")
            
            # 復元後にファイルサイズチェック
            if self.buffer_file.exists():
                file_size = self.buffer_file.stat().st_size / 1024  # KB
                logger.info(f"RealTimeRecorder: Buffer file size: {file_size:.1f} KB")
            
        except Exception as e:
            logger.error(f"RealTimeRecorder: Failed to load buffers: {e}")

    def cleanup(self):
        """クリーンアップ"""
        try:
            # バッファを保存してからクリア
            self.save_buffers()
        except:
            pass
        
        # 全ての録音タスクを停止
        for task in self.active_recordings.values():
            task.cancel()
        self.active_recordings.clear()
        
        # 接続をクリア
        self.connections.clear()
        self.guild_user_buffers.clear()


class RealEnhancedVoiceClient(discord.VoiceClient):
    """py-cord の WaveSink を使用したリアル音声録音クライアント"""
    
    def __init__(self, client: discord.Client, channel: discord.abc.Connectable):
        super().__init__(client, channel)
        self.recording_manager = None
        self.guild_id = channel.guild.id
        
    def set_recording_manager(self, recording_manager):
        """録音マネージャーを設定"""
        self.recording_manager = recording_manager