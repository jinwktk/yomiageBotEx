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
        # 録音状態管理（Guild別）
        self.recording_status: Dict[int, bool] = {}
        self.BUFFER_EXPIRATION = 300  # 5分（短縮）
        self.is_available = PYCORD_AVAILABLE
        
        # 永続化設定
        self.buffer_file = Path("data/audio_buffers.json")
        self.buffer_file.parent.mkdir(parents=True, exist_ok=True)
        
        # ファイル書き込みロック
        self._file_write_lock = asyncio.Lock()
        
        # 起動時にバッファを復元（サイズチェック付き）
        self.load_buffers_safe()
        
    async def start_recording(self, guild_id: int, voice_client: discord.VoiceClient):
        """録音開始"""
        if not self.is_available:
            logger.warning("py-cord not available, cannot start real recording")
            return
            
        try:
            # 内部状態チェック：既に録音を開始している場合はスキップ
            if self.recording_status.get(guild_id, False):
                logger.debug(f"RealTimeRecorder: Recording already active for guild {guild_id} (internal state), skipping")
                return
            
            # 既に録音中の場合は停止してから開始
            if hasattr(voice_client, 'recording') and voice_client.recording:
                logger.info(f"RealTimeRecorder: Already recording for guild {guild_id}, stopping first")
                voice_client.stop_recording()
                # 停止の完了を確実に待つ
                for i in range(10):  # 最大1秒待機
                    await asyncio.sleep(0.1)
                    if not (hasattr(voice_client, 'recording') and voice_client.recording):
                        break
                    logger.debug(f"RealTimeRecorder: Waiting for recording to stop... ({i+1}/10)")
                
                # それでも録音中の場合はスキップ
                if hasattr(voice_client, 'recording') and voice_client.recording:
                    logger.warning(f"RealTimeRecorder: Could not stop existing recording for guild {guild_id}, skipping")
                    return
            
            # 既存の録音タスクがあれば停止
            if guild_id in self.active_recordings:
                self.active_recordings[guild_id].cancel()
                await asyncio.sleep(0.1)  # 短時間待機
            
            # WaveSinkを使用した録音開始
            sink = WaveSink()
            self.connections[guild_id] = voice_client
            
            # コールバック関数をラムダで包む（guild_idを渡すため、asyncで包む）
            async def callback(sink_obj):
                await self._finished_callback(sink_obj, guild_id)
            
            voice_client.start_recording(sink, callback)
            # 録音状態を設定
            self.recording_status[guild_id] = True
            logger.info(f"RealTimeRecorder: Started recording for guild {guild_id} with channel {voice_client.channel.name}")
            logger.info(f"RealTimeRecorder: Voice client recording status: {voice_client.recording}")
            
            # 録音開始のデバッグ情報
            logger.info(f"RealTimeRecorder: Recording setup complete:")
            logger.info(f"  - Guild ID: {guild_id}")
            logger.info(f"  - Channel: {voice_client.channel.name}")
            logger.info(f"  - Current members: {[m.display_name for m in voice_client.channel.members]}")
            logger.info(f"  - Recording active: {getattr(voice_client, 'recording', False)}")
            logger.info(f"  - Sink type: {type(sink).__name__}")
            
            # 現在のバッファ状況（簡略化）
            current_buffers = self.guild_user_buffers.get(guild_id, {})
            logger.info(f"  - Existing buffers: {len(current_buffers)} users")
                
        except Exception as e:
            logger.error(f"RealTimeRecorder: Failed to start recording: {e}", exc_info=True)
            # エラー時も状態をクリア
            self.recording_status[guild_id] = False
    
    async def stop_recording(self, guild_id: int, voice_client: Optional[discord.VoiceClient] = None):
        """録音停止"""
        try:
            if guild_id in self.connections:
                vc = self.connections[guild_id]
                if hasattr(vc, 'recording') and vc.recording:
                    vc.stop_recording()
                del self.connections[guild_id]
                # 録音状態をクリア
                self.recording_status[guild_id] = False
                logger.info(f"RealTimeRecorder: Stopped recording for guild {guild_id}")
        except Exception as e:
            logger.error(f"RealTimeRecorder: Failed to stop recording: {e}")
    
    async def _finished_callback(self, sink: WaveSink, guild_id: int):
        """録音完了時のコールバック（bot_simple.pyから移植）"""
        try:
            logger.info(f"RealTimeRecorder: Finished callback called for guild {guild_id}")
            logger.info(f"RealTimeRecorder: Callback details:")
            logger.info(f"  - Sink type: {type(sink).__name__}")
            logger.info(f"  - Audio data keys: {list(sink.audio_data.keys())}")
            logger.info(f"  - Number of users: {len(sink.audio_data)}")
            
            # ユーザー数のみログ（詳細は省略）
            logger.debug(f"  - Processing audio for {len(sink.audio_data)} users")
            
            audio_count = 0
            for user_id, audio in sink.audio_data.items():
                logger.info(f"RealTimeRecorder: Processing audio for user {user_id}")
                if audio.file:
                    audio.file.seek(0)
                    audio_data = audio.file.read()
                    
                    # 音声データサイズ制限（100MB上限）
                    MAX_AUDIO_SIZE = 100 * 1024 * 1024  # 100MB
                    
                    if len(audio_data) > MAX_AUDIO_SIZE:
                        logger.warning(f"RealTimeRecorder: Audio data too large for user {user_id}: {len(audio_data)/1024/1024:.1f}MB > 100MB limit")
                        # 先頭100MBのみ保持（WAVヘッダーを保持）
                        audio_data = audio_data[:MAX_AUDIO_SIZE]
                        logger.info(f"RealTimeRecorder: Truncated audio to {len(audio_data)/1024/1024:.1f}MB")
                    
                    logger.info(f"RealTimeRecorder: Audio data size for user {user_id}: {len(audio_data)/1024/1024:.1f}MB")
                    
                    if audio_data and len(audio_data) > 44:  # WAVヘッダー以上のサイズ
                        user_audio_buffer = io.BytesIO(audio_data)
                        
                        # Guild別バッファに追加
                        if guild_id not in self.guild_user_buffers:
                            self.guild_user_buffers[guild_id] = {}
                        if user_id not in self.guild_user_buffers[guild_id]:
                            self.guild_user_buffers[guild_id][user_id] = []
                        
                        # バッファ数制限（最大3個まで保持）
                        MAX_BUFFERS_PER_USER = 3
                        if len(self.guild_user_buffers[guild_id][user_id]) >= MAX_BUFFERS_PER_USER:
                            # 古いバッファを削除
                            self.guild_user_buffers[guild_id][user_id].pop(0)
                            logger.info(f"RealTimeRecorder: Removed old buffer for user {user_id} (limit: {MAX_BUFFERS_PER_USER})")
                        
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
            
            # バッファを永続化（非同期タスクとして実行）
            if audio_count > 0:
                # save_buffers()は内部で非同期タスクを作成するので、awaitは不要
                self.save_buffers()
            
            # 録音状態をクリア
            self.recording_status[guild_id] = False
                        
        except Exception as e:
            logger.error(f"RealTimeRecorder: Error in finished_callback: {e}", exc_info=True)
            # エラー時も状態をクリア
            self.recording_status[guild_id] = False


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
        
        # バッファが変更された場合は保存（save_buffers内で非同期化される）
        self.save_buffers()
    
    def get_user_audio_buffers(self, guild_id: int, user_id: Optional[int] = None) -> Dict[int, list]:
        """ユーザーの音声バッファを取得（Guild別対応）"""
        logger.info(f"RealTimeRecorder: Getting buffers for guild {guild_id}, user {user_id}")
        logger.info(f"RealTimeRecorder: Current recording state for guild {guild_id}:")
        
        # 録音状況を詳細に確認
        if guild_id in self.connections:
            vc = self.connections[guild_id]
            logger.info(f"  - Voice client connected: {vc.is_connected() if vc else False}")
            logger.info(f"  - Currently recording: {getattr(vc, 'recording', False)}")
            logger.info(f"  - Channel: {vc.channel.name if vc and vc.channel else 'None'}")
        else:
            logger.info(f"  - No active connection for guild {guild_id}")
        
        # バッファの詳細状況
        logger.info(f"  - All guild buffers: {list(self.guild_user_buffers.keys())}")
        
        if guild_id not in self.guild_user_buffers:
            logger.warning(f"RealTimeRecorder: No buffers for guild {guild_id}")
            logger.info(f"  - Available guilds: {list(self.guild_user_buffers.keys())}")
            
            # 録音中にも関わらずバッファがない場合の警告
            if guild_id in self.connections:
                vc = self.connections[guild_id]
                if hasattr(vc, 'recording') and vc.recording:
                    logger.warning(f"RealTimeRecorder: WARNING - Currently recording but no buffers exist!")
                    logger.warning(f"  - This suggests audio data is not being saved to buffers yet")
                    logger.warning(f"  - Buffers are created only when recording is stopped")
            
            return {}
        
        guild_buffers = self.guild_user_buffers[guild_id]
        logger.info(f"RealTimeRecorder: Available users in guild {guild_id}: {list(guild_buffers.keys())}")
        
        # バッファ数のサマリーのみ（詳細はdebugレベルで）
        buffer_summary = {uid: len(buffers) for uid, buffers in guild_buffers.items()}
        logger.info(f"RealTimeRecorder: Guild {guild_id} buffer summary: {buffer_summary}")
        
        if user_id:
            result = {user_id: guild_buffers.get(user_id, [])}
            logger.info(f"RealTimeRecorder: Returning buffers for guild {guild_id}, user {user_id}: {len(result[user_id])} items")
            return result
        return guild_buffers.copy()
    
    async def force_recording_checkpoint(self, guild_id: int):
        """録音中でも現在までの音声データを強制的にバッファに保存"""
        try:
            if guild_id in self.connections:
                vc = self.connections[guild_id]
                if hasattr(vc, 'recording') and vc.recording:
                    logger.info(f"RealTimeRecorder: Forcing checkpoint for guild {guild_id}")
                    
                    # 現在の録音を一時停止してバッファに保存
                    vc.stop_recording()
                    await asyncio.sleep(0.5)  # コールバック完了を待つ
                    
                    # 録音を再開
                    await self.start_recording(guild_id, vc)
                    logger.info(f"RealTimeRecorder: Checkpoint complete, recording restarted")
                    return True
            return False
        except Exception as e:
            logger.error(f"RealTimeRecorder: Failed to create checkpoint: {e}")
            return False
    
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
        """音声バッファを永続化（非同期タスクとして実行されることを推奨）"""
        # 即座に非同期タスクを作成して戻る
        asyncio.create_task(self._save_buffers_async())
    
    def _prepare_buffer_data(self):
        """バッファデータの準備（CPU集約的な処理）"""
        simplified_buffers = {}
        
        for guild_id, users in self.guild_user_buffers.items():
            simplified_buffers[str(guild_id)] = {}
            
            for user_id, buffers in users.items():
                # 最新3件のみ保存（I/O負荷を軽減）
                recent_buffers = sorted(buffers, key=lambda x: x[1])[-3:]
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
        
        return simplified_buffers
    
    def _write_buffer_file(self, data):
        """ファイルへの書き込み（ブロッキングI/O）"""
        import time
        
        # Windows ファイルロック問題に対するリトライ機構
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # 一時ファイルに書き込んでから置き換える（アトミック操作）
                temp_file = self.buffer_file.with_suffix('.tmp')
                with open(temp_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, separators=(',', ':'))  # indent削除でサイズ削減
                
                # アトミックに置き換え
                temp_file.replace(self.buffer_file)
                
                total_buffers = sum(len(users) for users in data.values())
                logger.info(f"RealTimeRecorder: Saved {total_buffers} user buffers to {self.buffer_file}")
                return  # 成功したら終了
                
            except (PermissionError, OSError) as e:
                if attempt < max_retries - 1:
                    logger.warning(f"RealTimeRecorder: File write failed (attempt {attempt+1}/{max_retries}), retrying: {e}")
                    time.sleep(0.1 * (attempt + 1))  # 指数バックオフ
                else:
                    logger.error(f"RealTimeRecorder: Failed to write buffer file after {max_retries} attempts: {e}")
            except Exception as e:
                logger.error(f"RealTimeRecorder: Unexpected error writing buffer file: {e}")
                break
    
    async def _save_buffers_async(self):
        """非同期でバッファを保存（メインループをブロックしない）"""
        try:
            # ファイル書き込みロックを取得
            async with self._file_write_lock:
                # CPU集約的な処理（Base64エンコード）を別スレッドで実行
                loop = asyncio.get_event_loop()
                buffer_data = await loop.run_in_executor(None, self._prepare_buffer_data)
                
                # I/O処理も別スレッドで実行
                await loop.run_in_executor(None, self._write_buffer_file, buffer_data)
            
        except Exception as e:
            logger.error(f"RealTimeRecorder: Failed to save buffers async: {e}")
    
    def load_buffers_safe(self):
        """音声バッファを安全に復元（サイズチェック付き）"""
        try:
            if not self.buffer_file.exists():
                logger.info("RealTimeRecorder: No buffer file found, starting fresh")
                return
            
            # ファイルサイズチェック（1GB制限）
            file_size = self.buffer_file.stat().st_size
            MAX_BUFFER_FILE_SIZE = 1024 * 1024 * 1024  # 1GB
            
            if file_size > MAX_BUFFER_FILE_SIZE:
                logger.error(f"RealTimeRecorder: Buffer file too large ({file_size/1024/1024:.1f}MB > 1GB), removing corrupted file")
                self.buffer_file.unlink()
                return
            
            logger.info(f"RealTimeRecorder: Buffer file size: {file_size/1024:.1f} KB")
            
            with open(self.buffer_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            self.guild_user_buffers = {}
            total_restored = 0
            
            for guild_str, users in data.items():
                guild_id = int(guild_str)
                self.guild_user_buffers[guild_id] = {}
                
                for user_str, buffers in users.items():
                    user_id = int(user_str)
                    self.guild_user_buffers[guild_id][user_id] = []
                    
                    # 最大3件まで復元（メモリ使用量制限）
                    for buffer_data in buffers[-3:]:
                        try:
                            # サイズチェック（50MB制限）
                            buffer_size = buffer_data.get('size', 0)
                            if buffer_size > 50 * 1024 * 1024:  # 50MB
                                logger.warning(f"RealTimeRecorder: Skipping large buffer for user {user_id}: {buffer_size/1024/1024:.1f}MB")
                                continue
                            
                            # Base64デコード
                            audio_data = base64.b64decode(buffer_data['data'])
                            buffer = io.BytesIO(audio_data)
                            timestamp = buffer_data['timestamp']
                            
                            self.guild_user_buffers[guild_id][user_id].append((buffer, timestamp))
                            total_restored += 1
                            
                        except Exception as e:
                            logger.warning(f"RealTimeRecorder: Failed to restore buffer for user {user_id}: {e}")
                            continue
                    
                    # 空のユーザーは削除
                    if not self.guild_user_buffers[guild_id][user_id]:
                        del self.guild_user_buffers[guild_id][user_id]
                
                # 空のギルドは削除
                if not self.guild_user_buffers[guild_id]:
                    del self.guild_user_buffers[guild_id]
            
            logger.info(f"RealTimeRecorder: Restored {total_restored} audio buffers from disk")
            logger.info(f"RealTimeRecorder: Buffer file size: {file_size/1024:.1f} KB")
            
            # 古いバッファをクリーンアップ
            current_time = time.time()
            for guild_id in list(self.guild_user_buffers.keys()):
                for user_id in list(self.guild_user_buffers[guild_id].keys()):
                    self.guild_user_buffers[guild_id][user_id] = [
                        (buffer, timestamp) for buffer, timestamp in self.guild_user_buffers[guild_id][user_id]
                        if current_time - timestamp <= self.BUFFER_EXPIRATION
                    ]
                    if not self.guild_user_buffers[guild_id][user_id]:
                        del self.guild_user_buffers[guild_id][user_id]
                if not self.guild_user_buffers[guild_id]:
                    del self.guild_user_buffers[guild_id]
            
        except Exception as e:
            logger.error(f"RealTimeRecorder: Failed to load buffers, starting fresh: {e}")
            self.guild_user_buffers = {}
            # 破損したファイルを削除
            try:
                if self.buffer_file.exists():
                    self.buffer_file.unlink()
                    logger.info("RealTimeRecorder: Removed corrupted buffer file")
            except:
                pass
    
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
            # 最終的なバッファ保存（非同期タスクとして実行）
            self.save_buffers()
            # 少し待機して保存タスクが開始されることを確認
            asyncio.create_task(asyncio.sleep(0.1))
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