#!/usr/bin/env python3
"""
シンプル音声リレーシステム - WaveSinkベース
複雑なRealtimeRelaySinkシステムを置き換える簡潔な実装
"""

import asyncio
import tempfile
import time
import os
import logging
from typing import Dict, Optional, Set
from dataclasses import dataclass
from enum import Enum

import discord
from discord.sinks import WaveSink


class RelayStatus(Enum):
    """リレーセッションのステータス"""
    STARTING = "starting"
    ACTIVE = "active" 
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class SimpleRelaySession:
    """シンプルなリレーセッション情報"""
    session_id: str
    source_guild_id: int
    source_channel_id: int
    target_guild_id: int
    target_channel_id: int
    status: RelayStatus
    created_at: float
    last_activity: float
    active_users: Set[int]
    relay_sink: Optional['SimpleRelaySink'] = None


class SimpleRelaySink(WaveSink):
    """WaveSinkベースのシンプル音声リレーSink"""
    
    def __init__(self, session: SimpleRelaySession, target_voice_client: discord.VoiceClient, logger: logging.Logger, bot):
        super().__init__()
        self.session = session
        self.target_voice_client = target_voice_client
        self.logger = logger
        self.bot = bot
        self.relay_buffer = []
        self.buffer_size = 48000 * 2 * 2 * 0.5  # 0.5秒分のPCMデータ (48kHz, 16bit, stereo) - より高速リアルタイム
        self.last_relay_time = 0
        self.relay_interval = 0.2  # 0.2秒間隔でリレー実行 - 超高速リアルタイム
        
    def write(self, data, user):
        """音声データ受信（WaveSink標準処理 + リレー処理）"""
        try:
            # 標準のWaveSink処理
            super().write(data, user)
            
            # ボット自身の音声は除外
            if user == self.bot.user.id:
                return
            
            # リレー用バッファに追加
            current_time = time.time()
            self.relay_buffer.append({
                'data': data,
                'user_id': user,
                'timestamp': current_time
            })
            
            # セッションアクティビティ更新
            self.session.last_activity = current_time
            self.session.active_users.add(user)
            
            # バッファサイズまたは時間間隔でリレー実行
            total_buffer_size = sum(len(item['data']) for item in self.relay_buffer)
            time_since_last_relay = current_time - self.last_relay_time
            
            if (total_buffer_size >= self.buffer_size or 
                time_since_last_relay >= self.relay_interval):
                
                # 非同期でリレー実行（メインスレッドをブロックしない）
                asyncio.create_task(self._relay_buffered_audio())
                
        except Exception as e:
            self.logger.error(f"Error in SimpleRelaySink.write: {e}")
    
    async def _relay_buffered_audio(self):
        """バッファされた音声をリレー"""
        try:
            if not self.relay_buffer:
                return
            
            # ターゲットVCの接続確認
            if not self.target_voice_client or not self.target_voice_client.is_connected():
                self.logger.warning("Target voice client not connected, skipping relay")
                self.relay_buffer.clear()
                return
            
            # バッファ音声を結合
            combined_audio = b''.join(item['data'] for item in self.relay_buffer)
            user_count = len(set(item['user_id'] for item in self.relay_buffer))
            
            self.logger.info(f"🎵 RELAY: Relaying {len(combined_audio)} bytes from {user_count} users")
            
            # バッファクリア
            self.relay_buffer.clear()
            self.last_relay_time = time.time()
            
            # 一時ファイルに音声データを保存
            with tempfile.NamedTemporaryFile(delete=False, suffix='.pcm') as temp_file:
                temp_file.write(combined_audio)
                temp_file_path = temp_file.name
            
            try:
                # FFmpegでPCM音声をDiscord対応形式に変換
                audio_source = discord.FFmpegPCMAudio(
                    temp_file_path,
                    before_options='-f s16le -ar 48000 -ac 2',
                    options='-vn'
                )
                
                # 既存再生を停止して新しい音声を再生
                if self.target_voice_client.is_playing():
                    self.target_voice_client.stop()
                
                self.target_voice_client.play(audio_source)
                self.logger.info(f"🔊 AUDIO RELAYED: Successfully played audio in target channel")
                
            finally:
                # 一時ファイルのクリーンアップ（遅延実行）
                asyncio.get_event_loop().call_later(3.0, self._cleanup_temp_file, temp_file_path)
                
        except Exception as e:
            self.logger.error(f"Error relaying audio: {e}")
    
    def _cleanup_temp_file(self, file_path: str):
        """一時ファイルのクリーンアップ"""
        try:
            if os.path.exists(file_path):
                os.unlink(file_path)
        except Exception as e:
            self.logger.warning(f"Failed to cleanup temp file {file_path}: {e}")


class SimpleAudioRelay:
    """シンプルな音声リレー管理クラス"""
    
    def __init__(self, bot, config: dict, logger: logging.Logger):
        self.bot = bot
        self.config = config.get("audio_relay", {})
        self.logger = logger
        self.active_sessions: Dict[str, SimpleRelaySession] = {}
        self.enabled = self.config.get("enabled", False)
        
        if self.enabled:
            self.logger.info("Simple Audio Relay initialized - enabled")
        else:
            self.logger.info("Simple Audio Relay initialized - disabled")
    
    async def start_relay_session(
        self, 
        source_guild_id: int, 
        source_channel_id: int,
        target_guild_id: int, 
        target_channel_id: int
    ) -> str:
        """既存録音システム統合版リレーセッション開始"""
        if not self.enabled:
            raise ValueError("Audio relay is disabled in config")
        
        # セッションID生成
        session_id = f"simple_relay_{source_guild_id}_{source_channel_id}_{target_guild_id}_{target_channel_id}_{int(time.time())}"
        
        self.logger.info(f"Starting integrated relay session: {session_id}")
        
        try:
            # ギルドとチャンネル取得
            source_guild = self.bot.get_guild(source_guild_id)
            target_guild = self.bot.get_guild(target_guild_id)
            
            if not source_guild or not target_guild:
                raise ValueError(f"Guild not found: source={source_guild_id}, target={target_guild_id}")
            
            source_channel = source_guild.get_channel(source_channel_id)
            target_channel = target_guild.get_channel(target_channel_id)
            
            if not source_channel or not target_channel:
                raise ValueError(f"Channel not found: source={source_channel_id}, target={target_channel_id}")
            
            # セッション作成
            session = SimpleRelaySession(
                session_id=session_id,
                source_guild_id=source_guild_id,
                source_channel_id=source_channel_id,
                target_guild_id=target_guild_id,
                target_channel_id=target_channel_id,
                status=RelayStatus.STARTING,
                created_at=time.time(),
                last_activity=time.time(),
                active_users=set()
            )
            
            # ターゲットチャンネルに接続（音声出力用）
            target_voice_client = target_guild.voice_client
            if not target_voice_client or not target_voice_client.is_connected():
                target_voice_client = await target_channel.connect()
                self.logger.info(f"Connected to target channel: {target_channel.name}")
            elif target_voice_client.channel.id != target_channel_id:
                await target_voice_client.move_to(target_channel)
                self.logger.info(f"Moved to target channel: {target_channel.name}")
            
            # 既存録音システムとの統合：リレーコールバック登録
            recording_cog = self.bot.get_cog("RecordingCog")
            if recording_cog and hasattr(recording_cog, 'recorder_manager') and hasattr(recording_cog.recorder_manager, 'register_relay_callback'):
                # リレーコールバック関数を定義
                async def relay_callback(sink):
                    await self._process_audio_relay(sink, session, target_voice_client)
                
                # 既存録音システムにリレーコールバック登録
                recording_cog.recorder_manager.register_relay_callback(source_guild_id, relay_callback)
                self.logger.info(f"Registered relay callback with existing recording system for guild {source_guild_id}")
                
                session.status = RelayStatus.ACTIVE
                self.active_sessions[session_id] = session
                
                self.logger.info(f"🎤 INTEGRATED RELAY STARTED: {source_channel.name} -> {target_channel.name} (Session: {session_id})")
                
                return session_id
            else:
                raise ValueError("RecordingCog or recorder_manager not available for integration")
            
        except Exception as e:
            self.logger.error(f"Failed to start integrated relay session: {e}")
            raise
    
    async def _process_audio_relay(self, sink, session: SimpleRelaySession, target_voice_client):
        """既存録音システムから音声データを受信してリレー処理"""
        try:
            if not target_voice_client or not target_voice_client.is_connected():
                self.logger.warning("Target voice client not connected, skipping relay")
                return
            
            # WaveSinkから音声データを取得
            combined_audio = b''
            user_count = 0
            
            for user_id, audio in sink.audio_data.items():
                # ボット自身の音声は除外
                if user_id == self.bot.user.id:
                    continue
                
                if audio.file:
                    audio.file.seek(0)
                    audio_data = audio.file.read()
                    
                    if audio_data and len(audio_data) > 44:  # WAVヘッダー以上のサイズ
                        # WAVヘッダーをスキップしてPCMデータのみ取得
                        if user_count == 0:
                            # 最初のユーザーのみヘッダーを保持
                            combined_audio += audio_data
                        else:
                            # 他のユーザーはPCMデータ部分のみ追加（ヘッダースキップ）
                            combined_audio += audio_data[44:]
                        
                        user_count += 1
                        
                        # セッションの活動更新
                        session.last_activity = time.time()
                        session.active_users.add(user_id)
            
            if combined_audio and user_count > 0:
                self.logger.info(f"🎵 RELAY: Processing {len(combined_audio)} bytes from {user_count} users")
                
                # 一時ファイルに音声データを保存してリレー
                import tempfile
                import os
                
                with tempfile.NamedTemporaryFile(delete=False, suffix='.wav') as temp_file:
                    temp_file.write(combined_audio)
                    temp_file_path = temp_file.name
                
                try:
                    # Discord対応形式で音声を再生
                    import discord
                    audio_source = discord.FFmpegPCMAudio(
                        temp_file_path,
                        before_options='-f wav',
                        options='-vn'
                    )
                    
                    # 既存再生を停止して新しい音声を再生
                    if target_voice_client.is_playing():
                        target_voice_client.stop()
                    
                    target_voice_client.play(audio_source)
                    self.logger.info(f"🔊 AUDIO RELAYED: Successfully played audio in target channel")
                    
                finally:
                    # 一時ファイルのクリーンアップ（遅延実行）
                    import asyncio
                    asyncio.get_event_loop().call_later(3.0, self._cleanup_temp_file, temp_file_path)
            
        except Exception as e:
            self.logger.error(f"Error processing audio relay: {e}")
    
    def _cleanup_temp_file(self, file_path: str):
        """一時ファイルのクリーンアップ"""
        try:
            import os
            if os.path.exists(file_path):
                os.unlink(file_path)
        except Exception as e:
            self.logger.warning(f"Failed to cleanup temp file {file_path}: {e}")
    
    def _recording_finished_callback(self, sink, error=None):
        """録音終了時のコールバック（必要に応じて）"""
        if error:
            self.logger.error(f"Recording finished with error: {error}")
        else:
            self.logger.info("Recording finished successfully")
    
    async def stop_relay_session(self, session_id: str) -> bool:
        """統合版リレーセッションの停止"""
        if session_id not in self.active_sessions:
            self.logger.warning(f"Session {session_id} not found")
            return False
        
        session = self.active_sessions[session_id]
        session.status = RelayStatus.STOPPING
        
        try:
            # 既存録音システムからリレーコールバック登録解除
            recording_cog = self.bot.get_cog("RecordingCog")
            if recording_cog and hasattr(recording_cog, 'recorder_manager') and hasattr(recording_cog.recorder_manager, 'unregister_relay_callback'):
                recording_cog.recorder_manager.unregister_relay_callback(session.source_guild_id)
                self.logger.info(f"Unregistered relay callback for guild {session.source_guild_id}")
            
            # セッション削除
            del self.active_sessions[session_id]
            session.status = RelayStatus.STOPPED
            
            self.logger.info(f"🛑 INTEGRATED RELAY STOPPED: Session {session_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error stopping integrated relay session {session_id}: {e}")
            return False
    
    async def stop_all_sessions(self):
        """すべてのリレーセッションを停止"""
        sessions_to_stop = list(self.active_sessions.keys())
        for session_id in sessions_to_stop:
            await self.stop_relay_session(session_id)
        
        self.logger.info("All relay sessions stopped")
    
    def get_active_sessions(self) -> Dict[str, SimpleRelaySession]:
        """アクティブセッション一覧を取得"""
        return self.active_sessions.copy()