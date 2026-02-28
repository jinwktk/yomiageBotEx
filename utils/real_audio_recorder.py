"""
リアルな音声録音システム（py-cord + WaveSink統合版）
bot_simple.pyの動作する録音機能をutils/に移植
"""

import asyncio
import logging
import time
import io
import wave
import json
import base64
import struct
import hashlib
from pathlib import Path
from typing import Dict, Callable, Optional, Any, Tuple

try:
    import discord
    from discord.sinks import WaveSink
    PYCORD_AVAILABLE = True
except ImportError:
    PYCORD_AVAILABLE = False
    logging.warning("py-cord not available. Real audio recording will not work.")

try:
    from utils.recording_callback_manager import recording_callback_manager
except Exception:  # pragma: no cover - optional integration
    recording_callback_manager = None

logger = logging.getLogger(__name__)


class RealTimeAudioRecorder:
    """リアルタイム音声録音管理クラス（bot_simple.py統合版）"""
    
    def __init__(self, recording_manager):
        self.recording_manager = recording_manager
        self.relay_callbacks = {}  # Guild ID -> callback function for audio relay
        self.connections: Dict[int, discord.VoiceClient] = {}
        # Guild別のユーザー音声バッファ: {guild_id: {user_id: [(buffer, timestamp), ...]}}
        self.guild_user_buffers: Dict[int, Dict[int, list]] = {}
        # Guild別の連続音声バッファ: {guild_id: {user_id: [(audio_chunk, start_time, end_time), ...]}}
        self.continuous_buffers: Dict[int, Dict[int, list]] = {}
        self._last_chunk_meta: Dict[int, Dict[int, Tuple[bytes, float, float]]] = {}
        self._last_callback_chunk_meta: Dict[int, Dict[int, Tuple[bytes, float]]] = {}
        self.active_recordings: Dict[int, asyncio.Task] = {}
        # 録音状態管理（Guild別）
        self.recording_status: Dict[int, bool] = {}
        # 空コールバック監視（Guild別）
        self.empty_callback_counts: Dict[int, int] = {}
        self._last_recovery_attempt_at: Dict[int, float] = {}
        self.EMPTY_CALLBACK_RECOVERY_THRESHOLD = 6
        self.EMPTY_CALLBACK_RECOVERY_COOLDOWN = 20.0
        self.HARD_RECOVERY_AFTER_SOFT_RESTARTS = 3
        self._soft_recovery_restart_counts: Dict[int, int] = {}
        self.RECOVERY_REQUIRES_RECENT_AUDIO_SECONDS = 180.0
        self.NO_RECENT_AUDIO_RECOVERY_RETRY_SECONDS = 300.0
        self._last_stale_recovery_attempt_at: Dict[int, float] = {}
        self._last_non_empty_audio_at: Dict[int, float] = {}
        # 録音開始時刻記録（Guild別）
        self.recording_start_times: Dict[int, float] = {}
        self.BUFFER_EXPIRATION = 300  # 5分
        self.CONTINUOUS_BUFFER_DURATION = 300  # 5分間の連続バッファ
        self.is_available = PYCORD_AVAILABLE

        self.DEFAULT_SAMPLE_RATE = 48000
        self.DEFAULT_CHANNELS = 2
        self.DEFAULT_SAMPLE_WIDTH = 2

        # 永続化設定
        self.buffer_file = Path("data/audio_buffers.json")
        self.buffer_file.parent.mkdir(parents=True, exist_ok=True)
        
        # ファイル書き込みロック
        self._file_write_lock = asyncio.Lock()
        
        # 起動時にバッファを復元（サイズチェック付き）
        self.load_buffers_safe()

    async def _stop_recording_non_blocking(self, voice_client):
        """stop_recordingの同期ブロッキングをイベントループ外で実行"""
        if not voice_client:
            return
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, voice_client.stop_recording)

    async def _start_recording_non_blocking(self, voice_client, sink, callback):
        """start_recordingの同期ブロッキングをイベントループ外で実行"""
        if not voice_client:
            return
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, voice_client.start_recording, sink, callback)

    def _create_wave_sink(self):
        """録音再開に使うWaveSinkを生成"""
        return WaveSink()

    def apply_recording_config(self, recording_config: Dict[str, Any]) -> None:
        """recording設定を反映"""
        if not isinstance(recording_config, dict):
            return

        def _coerce_seconds(value: Any, default_seconds: float) -> float:
            try:
                seconds = float(value)
                if seconds <= 0:
                    return default_seconds
                return seconds
            except (TypeError, ValueError):
                return default_seconds

        self.BUFFER_EXPIRATION = _coerce_seconds(
            recording_config.get("buffer_expiration_seconds", self.BUFFER_EXPIRATION),
            self.BUFFER_EXPIRATION,
        )
        self.CONTINUOUS_BUFFER_DURATION = _coerce_seconds(
            recording_config.get("continuous_buffer_duration_seconds", self.CONTINUOUS_BUFFER_DURATION),
            self.CONTINUOUS_BUFFER_DURATION,
        )
        self.NO_RECENT_AUDIO_RECOVERY_RETRY_SECONDS = _coerce_seconds(
            recording_config.get(
                "no_recent_audio_recovery_retry_seconds",
                self.NO_RECENT_AUDIO_RECOVERY_RETRY_SECONDS,
            ),
            self.NO_RECENT_AUDIO_RECOVERY_RETRY_SECONDS,
        )
        logger.info(
            "RealTimeRecorder: Applied config buffer_expiration=%ss continuous_buffer_duration=%ss no_recent_audio_recovery_retry=%ss",
            int(self.BUFFER_EXPIRATION),
            int(self.CONTINUOUS_BUFFER_DURATION),
            int(self.NO_RECENT_AUDIO_RECOVERY_RETRY_SECONDS),
        )

    def _has_non_bot_members(self, voice_client) -> bool:
        """VCにBot以外のメンバーがいるか判定"""
        channel = getattr(voice_client, "channel", None)
        members = getattr(channel, "members", []) if channel else []
        return any(not getattr(member, "bot", False) for member in members)

    def get_voice_diagnostics(self, guild_id: int, target_user_id: Optional[int] = None) -> Dict[str, Any]:
        """録音受信まわりの診断情報を取得"""
        now = time.time()
        vc = self.connections.get(guild_id)
        last_non_empty = self._last_non_empty_audio_at.get(guild_id)
        snapshot: Dict[str, Any] = {
            "guild_id": guild_id,
            "voice_client_present": vc is not None,
            "recording_status_flag": bool(self.recording_status.get(guild_id, False)),
            "empty_callback_count": self.empty_callback_counts.get(guild_id, 0),
            "last_non_empty_audio_seconds_ago": (now - last_non_empty) if last_non_empty else None,
            "target_user_id": target_user_id,
            "target_user": None,
        }
        if vc is None:
            return snapshot

        channel = getattr(vc, "channel", None)
        ws = getattr(vc, "ws", None)
        ssrc_map = getattr(ws, "ssrc_map", None)

        snapshot.update(
            {
                "voice_client_connected": bool(getattr(vc, "is_connected", lambda: False)()),
                "voice_client_recording": bool(getattr(vc, "recording", False)),
                "voice_mode": getattr(vc, "mode", None),
                "channel_id": getattr(channel, "id", None),
                "channel_name": getattr(channel, "name", None),
                "member_count": len(getattr(channel, "members", []) or []),
                "ssrc_map_size": len(ssrc_map) if isinstance(ssrc_map, dict) else None,
            }
        )
        if isinstance(ssrc_map, dict):
            mapped_user_ids = set()
            for item in ssrc_map.values():
                if isinstance(item, int):
                    mapped_user_ids.add(item)
                    continue
                if isinstance(item, dict):
                    maybe_user_id = item.get("user_id") or item.get("id")
                    if isinstance(maybe_user_id, int):
                        mapped_user_ids.add(maybe_user_id)
                    continue
                for attr in ("user_id", "id"):
                    maybe_user_id = getattr(item, attr, None)
                    if isinstance(maybe_user_id, int):
                        mapped_user_ids.add(maybe_user_id)
                        break
            snapshot["ssrc_user_ids"] = sorted(mapped_user_ids)
            snapshot["target_user_in_ssrc_map"] = (
                target_user_id in mapped_user_ids if target_user_id is not None else None
            )

        members_summary = []
        for member in getattr(channel, "members", []) or []:
            voice_state = getattr(member, "voice", None)
            member_item = {
                "id": getattr(member, "id", None),
                "display_name": getattr(member, "display_name", getattr(member, "name", None)),
                "bot": bool(getattr(member, "bot", False)),
                "voice": {
                    "self_mute": bool(getattr(voice_state, "self_mute", False)) if voice_state else None,
                    "self_deaf": bool(getattr(voice_state, "self_deaf", False)) if voice_state else None,
                    "mute": bool(getattr(voice_state, "mute", False)) if voice_state else None,
                    "deaf": bool(getattr(voice_state, "deaf", False)) if voice_state else None,
                    "suppress": bool(getattr(voice_state, "suppress", False)) if voice_state else None,
                    "channel_id": getattr(getattr(voice_state, "channel", None), "id", None),
                },
            }
            members_summary.append(member_item)
            if target_user_id is not None and member_item["id"] == target_user_id:
                snapshot["target_user"] = member_item

        snapshot["members"] = members_summary
        return snapshot

    def _log_voice_diagnostics(
        self,
        *,
        reason: str,
        guild_id: int,
        target_user_id: Optional[int] = None,
        level: int = logging.WARNING,
    ) -> None:
        """診断情報をログ出力"""
        try:
            snapshot = self.get_voice_diagnostics(guild_id, target_user_id=target_user_id)
            logger.log(
                level,
                "RealTimeRecorder: Voice diagnostics (%s): %s",
                reason,
                json.dumps(snapshot, ensure_ascii=False, default=str),
            )
        except Exception as e:
            logger.warning(
                "RealTimeRecorder: Failed to build voice diagnostics for guild %s (%s): %s",
                guild_id,
                reason,
                e,
            )

    async def _attempt_recover_stuck_recording(self, guild_id: int):
        """空コールバック連続時に録音セッションを再起動"""
        voice_client = self.connections.get(guild_id)
        if not voice_client or not voice_client.is_connected():
            return
        if not self.recording_status.get(guild_id, False):
            return
        if not self._has_non_bot_members(voice_client):
            return

        now = time.time()
        last_attempt = self._last_recovery_attempt_at.get(guild_id, 0.0)
        if now - last_attempt < self.EMPTY_CALLBACK_RECOVERY_COOLDOWN:
            return
        self._last_recovery_attempt_at[guild_id] = now

        last_audio_at = self._last_non_empty_audio_at.get(guild_id)
        if not last_audio_at:
            logger.info(
                "RealTimeRecorder: Skip auto-recovery for guild %s (no non-empty audio observed yet).",
                guild_id,
            )
            return
        stale_seconds = now - last_audio_at
        if stale_seconds > self.RECOVERY_REQUIRES_RECENT_AUDIO_SECONDS:
            last_stale_attempt = self._last_stale_recovery_attempt_at.get(guild_id, 0.0)
            if (now - last_stale_attempt) < self.NO_RECENT_AUDIO_RECOVERY_RETRY_SECONDS:
                logger.info(
                    "RealTimeRecorder: Skip auto-recovery for guild %s (last non-empty audio %.1fs ago, retry interval %.1fs)",
                    guild_id,
                    stale_seconds,
                    self.NO_RECENT_AUDIO_RECOVERY_RETRY_SECONDS,
                )
                return
            self._last_stale_recovery_attempt_at[guild_id] = now
            logger.warning(
                "RealTimeRecorder: Proceeding with periodic recovery for guild %s despite stale audio (%.1fs ago).",
                guild_id,
                stale_seconds,
            )
        self._log_voice_diagnostics(reason="pre_recovery", guild_id=guild_id)

        logger.warning(
            "RealTimeRecorder: Empty callbacks reached threshold for guild %s. Restarting recording session.",
            guild_id,
        )

        async def _try_stop_for_recovery():
            try:
                await self._stop_recording_non_blocking(voice_client)
                return
            except Exception as stop_error:
                # 競合で既に停止済みのケースは許容して再開処理を続ける
                if "Not currently recording audio" in str(stop_error):
                    logger.info(
                        "RealTimeRecorder: Recovery stop skipped for guild %s (already stopped).",
                        guild_id,
                    )
                    return
                raise

        try:
            new_sink = self._create_wave_sink()

            async def callback(sink_obj):
                await self._finished_callback(sink_obj, guild_id)

            await _try_stop_for_recovery()
            await asyncio.sleep(0.1)
            try:
                await self._start_recording_non_blocking(voice_client, new_sink, callback)
            except Exception as start_error:
                if "Already recording." in str(start_error):
                    logger.warning(
                        "RealTimeRecorder: Recovery start collided for guild %s. Retrying once.",
                        guild_id,
                    )
                    await _try_stop_for_recovery()
                    await asyncio.sleep(0.2)
                    await self._start_recording_non_blocking(voice_client, new_sink, callback)
                else:
                    raise
            self.connections[guild_id] = voice_client
            self.recording_status[guild_id] = True
            self.empty_callback_counts[guild_id] = 0
            self._soft_recovery_restart_counts[guild_id] = 0
            self._last_stale_recovery_attempt_at.pop(guild_id, None)
            logger.info("RealTimeRecorder: Recovery restart completed for guild %s", guild_id)
            self._log_voice_diagnostics(reason="post_recovery_success", guild_id=guild_id, level=logging.INFO)
        except Exception as e:
            logger.error("RealTimeRecorder: Recovery restart failed for guild %s: %s", guild_id, e)
            self._log_voice_diagnostics(reason="post_recovery_failure", guild_id=guild_id)
            failure_count = self._soft_recovery_restart_counts.get(guild_id, 0) + 1
            self._soft_recovery_restart_counts[guild_id] = failure_count
            logger.warning(
                "RealTimeRecorder: Soft recovery failed %s/%s for guild %s.",
                failure_count,
                self.HARD_RECOVERY_AFTER_SOFT_RESTARTS,
                guild_id,
            )
            if failure_count >= self.HARD_RECOVERY_AFTER_SOFT_RESTARTS:
                recovered = await self._attempt_hard_reconnect(guild_id, voice_client)
                if recovered:
                    self._soft_recovery_restart_counts[guild_id] = 0

    async def _attempt_hard_reconnect(self, guild_id: int, voice_client) -> bool:
        """軽い再開で復旧しない場合、VCを張り直して録音を再開"""
        channel = getattr(voice_client, "channel", None)
        if not channel:
            return False

        logger.warning(
            "RealTimeRecorder: Escalating to hard reconnect for guild %s on channel %s",
            guild_id,
            getattr(channel, "name", "unknown"),
        )

        try:
            try:
                await voice_client.disconnect()
            except Exception as disconnect_error:
                logger.warning(
                    "RealTimeRecorder: Hard reconnect disconnect failed for guild %s: %s",
                    guild_id,
                    disconnect_error,
                )

            guild = getattr(channel, "guild", None)
            if guild is not None and getattr(guild, "_voice_client", None) is voice_client:
                guild._voice_client = None

            await asyncio.sleep(0.5)
            new_voice_client = await channel.connect(cls=type(voice_client), reconnect=True)

            new_sink = self._create_wave_sink()

            async def callback(sink_obj):
                await self._finished_callback(sink_obj, guild_id)

            await self._start_recording_non_blocking(new_voice_client, new_sink, callback)
            self.connections[guild_id] = new_voice_client
            self.recording_status[guild_id] = True
            self.empty_callback_counts[guild_id] = 0
            logger.info("RealTimeRecorder: Hard reconnect completed for guild %s", guild_id)
            return True
        except Exception as e:
            logger.error("RealTimeRecorder: Hard reconnect failed for guild %s: %s", guild_id, e)
            return False

    def _ensure_wav_format(self, pcm_data: bytes) -> bytes:
        """PCMデータを必ずWAVフォーマットに変換"""
        if not pcm_data:
            return pcm_data

        if pcm_data[:4] == b"RIFF" and pcm_data[8:12] == b"WAVE":
            return pcm_data

        buffer = io.BytesIO()
        header = self._pcm_to_wav_header(len(pcm_data))
        buffer.write(header)
        buffer.write(pcm_data)
        return buffer.getvalue()

    def _pcm_to_wav_header(self, pcm_size: int) -> bytes:
        """PCMデータ長からWAVヘッダーを生成"""
        chunk_size = 36 + pcm_size
        byte_rate = self.DEFAULT_SAMPLE_RATE * self.DEFAULT_CHANNELS * self.DEFAULT_SAMPLE_WIDTH
        block_align = self.DEFAULT_CHANNELS * self.DEFAULT_SAMPLE_WIDTH
        bits_per_sample = self.DEFAULT_SAMPLE_WIDTH * 8

        return struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF",
            chunk_size,
            b"WAVE",
            b"fmt ",
            16,  # PCM fmt chunk size
            1,  # PCM format
            self.DEFAULT_CHANNELS,
            self.DEFAULT_SAMPLE_RATE,
            byte_rate,
            block_align,
            bits_per_sample,
            b"data",
            pcm_size,
        )
    
    def register_relay_callback(self, guild_id: int, callback_func: Callable):
        """音声リレー用コールバック関数の登録"""
        self.relay_callbacks[guild_id] = callback_func
        logger.info(f"RealTimeRecorder: Registered relay callback for guild {guild_id}")
    
    def unregister_relay_callback(self, guild_id: int):
        """音声リレー用コールバック関数の登録解除"""
        if guild_id in self.relay_callbacks:
            del self.relay_callbacks[guild_id]
            logger.info(f"RealTimeRecorder: Unregistered relay callback for guild {guild_id}")
        
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
                await self._stop_recording_non_blocking(voice_client)
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
            
            # 録音開始時刻を記録
            recording_start_time = time.time()
            self.recording_start_times[guild_id] = recording_start_time
            
            await self._start_recording_non_blocking(voice_client, sink, callback)
            # 録音状態を設定
            self.recording_status[guild_id] = True
            self.empty_callback_counts[guild_id] = 0
            
            # 定期的なチェックポイント作成タスクを開始
            checkpoint_task = asyncio.create_task(self._periodic_checkpoint_task(guild_id, voice_client))
            self.active_recordings[guild_id] = checkpoint_task
            logger.info(f"RealTimeRecorder: Started recording for guild {guild_id} with channel {voice_client.channel.name}")
            logger.info(f"RealTimeRecorder: Recording start time: {recording_start_time}")
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
                    await self._stop_recording_non_blocking(vc)
                del self.connections[guild_id]
                
                # チェックポイントタスクをキャンセル
                if guild_id in self.active_recordings:
                    self.active_recordings[guild_id].cancel()
                    del self.active_recordings[guild_id]
                
                # 録音状態をクリア
                self.recording_status[guild_id] = False
                logger.info(f"RealTimeRecorder: Stopped recording for guild {guild_id}")
        except Exception as e:
            logger.error(f"RealTimeRecorder: Failed to stop recording: {e}")
    
    async def _periodic_checkpoint_task(self, guild_id: int, voice_client):
        """定期的にチェックポイントを作成してリアルタイム音声データを取得"""
        logger.info(f"RealTimeRecorder: Starting periodic checkpoint task for guild {guild_id}")
        checkpoint_interval = 5.0  # 5秒ごとにチェックポイント作成（リプレイ機能改善のため10秒→5秒に短縮）
        
        try:
            while self.recording_status.get(guild_id, False):
                await asyncio.sleep(checkpoint_interval)
                
                # 録音がまだ有効か確認
                if not self.recording_status.get(guild_id, False):
                    break
                    
                # チェックポイント作成（一時停止→再開）
                if voice_client and voice_client.is_connected() and getattr(voice_client, 'recording', False):
                    try:
                        logger.debug(f"RealTimeRecorder: Creating checkpoint for guild {guild_id}")
                        # 現在の録音を一時停止してデータを取得
                        old_sink = getattr(voice_client, 'sink', None)
                        if old_sink and hasattr(old_sink, 'audio_data') and old_sink.audio_data:
                            # 既存のデータを処理
                            await self._process_checkpoint_data(guild_id, old_sink.audio_data)
                        
                        # 新しいSinkで録音を再開
                        new_sink = WaveSink()
                        async def new_callback(sink_obj):
                            await self._finished_callback(sink_obj, guild_id)
                        
                        # 録音を再開
                        await self._stop_recording_non_blocking(voice_client)
                        await asyncio.sleep(0.1)  # 少し待機
                        await self._start_recording_non_blocking(voice_client, new_sink, new_callback)

                        # コールバックでrecording_statusがFalseになるため、再開後に更新
                        self.recording_status[guild_id] = True
                        self.connections[guild_id] = voice_client
                        
                    except Exception as e:
                        logger.warning(f"RealTimeRecorder: Checkpoint creation failed: {e}")
                
        except asyncio.CancelledError:
            logger.info(f"RealTimeRecorder: Checkpoint task cancelled for guild {guild_id}")
        except Exception as e:
            logger.error(f"RealTimeRecorder: Error in checkpoint task: {e}")
    
    async def _process_checkpoint_data(self, guild_id: int, audio_data: dict):
        """チェックポイントで取得した音声データを処理"""
        try:
            current_time = time.time()
            logger.debug(f"RealTimeRecorder: Processing checkpoint data for guild {guild_id}")
            
            for user_id, audio in audio_data.items():
                if audio.file:
                    audio.file.seek(0)
                    raw_data = audio.file.read()
                    wav_data = self._ensure_wav_format(raw_data)
                    
                    if len(wav_data) > 44:  # WAVヘッダー + 音声データが存在
                        # continuous_buffersに追加
                        added = self._add_to_continuous_buffer(guild_id, user_id, wav_data, current_time)
                        if added:
                            await self._forward_to_recording_callback_manager(
                                guild_id=guild_id,
                                user_id=user_id,
                                audio_data=wav_data,
                            )
                    
                        # 従来のバッファにも追加
                        buffer = io.BytesIO(wav_data)
                        if guild_id not in self.guild_user_buffers:
                            self.guild_user_buffers[guild_id] = {}
                        if user_id not in self.guild_user_buffers[guild_id]:
                            self.guild_user_buffers[guild_id][user_id] = []
                        self.guild_user_buffers[guild_id][user_id].append((buffer, current_time))
                        logger.info(f"RealTimeRecorder: Added audio buffer for guild {guild_id}, user {user_id} ({len(wav_data)} bytes)")
                        
                        logger.debug(f"RealTimeRecorder: Added checkpoint data for user {user_id} in guild {guild_id}")
                        
        except Exception as e:
            logger.error(f"RealTimeRecorder: Error processing checkpoint data: {e}")
    
    async def _finished_callback(self, sink: WaveSink, guild_id: int):
        """録音完了時のコールバック（bot_simple.pyから移植）"""
        try:
            logger.info(f"RealTimeRecorder: Finished callback called for guild {guild_id}")
            logger.debug(f"RealTimeRecorder: Callback details - {len(sink.audio_data)} users")
            
            # WaveSinkの詳細情報をデバッグ出力
            logger.info(f"RealTimeRecorder: WaveSink debug info:")
            logger.info(f"  - sink.audio_data type: {type(sink.audio_data)}")
            logger.info(f"  - sink.audio_data keys: {list(sink.audio_data.keys())}")
            
            # ユーザー数のみログ（詳細は省略）
            logger.debug(f"  - Processing audio for {len(sink.audio_data)} users")
            
            audio_count = 0
            for user_id, audio in sink.audio_data.items():
                logger.info(f"RealTimeRecorder: Processing audio for user {user_id}")
                logger.info(f"  - audio object type: {type(audio)}")
                logger.info(f"  - audio.file exists: {audio.file is not None}")
                
                if audio.file:
                    # ファイル詳細情報を取得
                    file_pos_before = audio.file.tell()
                    audio.file.seek(0, 2)  # ファイル末尾に移動
                    file_size = audio.file.tell()
                    audio.file.seek(0)  # 先頭に戻す
                    raw_audio_data = audio.file.read()
                    audio_data = self._ensure_wav_format(raw_audio_data)
                    
                    logger.info(f"  - File position before: {file_pos_before}")
                    logger.info(f"  - File size: {file_size} bytes")
                    logger.info(f"  - Read data size: {len(audio_data)} bytes")
                    
                    # WAVファイル構造を詳しく分析
                    if len(audio_data) >= 44:
                        import wave
                        try:
                            with wave.open(io.BytesIO(audio_data), 'rb') as wav_file:
                                logger.info(f"  - WAV channels: {wav_file.getnchannels()}")
                                logger.info(f"  - WAV sample width: {wav_file.getsampwidth()}")
                                logger.info(f"  - WAV framerate: {wav_file.getframerate()}")
                                logger.info(f"  - WAV frames: {wav_file.getnframes()}")
                                
                                # 実際のPCMデータを読み取り
                                pcm_data = wav_file.readframes(wav_file.getnframes())
                                logger.info(f"  - PCM data size: {len(pcm_data)} bytes")
                                
                                # PCMデータの最初の数バイトをサンプル表示
                                if len(pcm_data) > 0:
                                    sample_bytes = pcm_data[:min(16, len(pcm_data))]
                                    logger.info(f"  - PCM sample (first {len(sample_bytes)} bytes): {sample_bytes.hex()}")
                                else:
                                    logger.warning(f"  - PCM data is empty!")
                                    
                        except Exception as wav_e:
                            logger.error(f"  - WAV analysis error: {wav_e}")
                    
                    # 音声データサイズ制限（100MB上限）
                    MAX_AUDIO_SIZE = 100 * 1024 * 1024  # 100MB
                    
                    if len(audio_data) > MAX_AUDIO_SIZE:
                        logger.warning(f"RealTimeRecorder: Audio data too large for user {user_id}: {len(audio_data)/1024/1024:.1f}MB > 100MB limit")
                        # 先頭100MBのみ保持（WAVヘッダーを保持）
                        audio_data = audio_data[:MAX_AUDIO_SIZE]
                        logger.info(f"RealTimeRecorder: Truncated audio to {len(audio_data)/1024/1024:.1f}MB")
                    
                    logger.debug(f"RealTimeRecorder: Audio data size for user {user_id}: {len(audio_data)/1024/1024:.1f}MB")
                    
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
                            logger.debug(f"RealTimeRecorder: Removed old buffer for user {user_id}")
                        
                        current_time = time.time()
                        self.guild_user_buffers[guild_id][user_id].append((user_audio_buffer, current_time))
                        
                        # 連続バッファにも追加（時間情報付き）
                        added = self._add_to_continuous_buffer(guild_id, user_id, audio_data, current_time)
                        if added:
                            await self._forward_to_recording_callback_manager(
                                guild_id=guild_id,
                                user_id=user_id,
                                audio_data=audio_data,
                            )
                        
                        # continuous_bufferにデータを追加（RecordingManagerへの参照は削除）
                        
                        logger.debug(f"RealTimeRecorder: Added audio buffer for guild {guild_id}, user {user_id}")
                        audio_count += 1
                    else:
                        logger.warning(f"RealTimeRecorder: Audio data too small for user {user_id}: {len(audio_data)} bytes")
                        logger.warning(f"  - This means WaveSink only provided WAV header without PCM data")
                else:
                    logger.warning(f"RealTimeRecorder: No audio.file for user {user_id}")
            
            logger.info(f"RealTimeRecorder: Processed {audio_count} audio files in callback")
            if audio_count == 0:
                empty_count = self.empty_callback_counts.get(guild_id, 0) + 1
                self.empty_callback_counts[guild_id] = empty_count
                logger.warning(
                    "RealTimeRecorder: WaveSink callback returned no audio data for guild %s. Recording may be silent or stuck.",
                    guild_id,
                )
                if (
                    empty_count == 1
                    or empty_count == self.EMPTY_CALLBACK_RECOVERY_THRESHOLD
                    or (empty_count % max(self.EMPTY_CALLBACK_RECOVERY_THRESHOLD, 1) == 0)
                ):
                    self._log_voice_diagnostics(reason=f"empty_callback_{empty_count}", guild_id=guild_id)
                if empty_count >= self.EMPTY_CALLBACK_RECOVERY_THRESHOLD:
                    await self._attempt_recover_stuck_recording(guild_id)
            else:
                self.empty_callback_counts[guild_id] = 0
                self._soft_recovery_restart_counts[guild_id] = 0
                self._last_non_empty_audio_at[guild_id] = time.time()
                self._last_stale_recovery_attempt_at.pop(guild_id, None)
            
            # リレーコールバック呼び出し（音声リレー機能）
            if guild_id in self.relay_callbacks and audio_count > 0:
                try:
                    logger.info(f"RealTimeRecorder: Calling relay callback for guild {guild_id}")
                    await self.relay_callbacks[guild_id](sink)
                except Exception as e:
                    logger.error(f"RealTimeRecorder: Error in relay callback for guild {guild_id}: {e}")
            
            # バッファを永続化（頻度を下げて最小限のみ保存）
            if audio_count > 0:
                # 20回に1回のみ保存（さらに頻度を下げる）
                if not hasattr(self, '_finished_save_counter'):
                    self._finished_save_counter = 0
                self._finished_save_counter += 1
                if self._finished_save_counter >= 20:
                    self._finished_save_counter = 0
                    self.save_buffers()

            # stop/start の競合で状態を誤って落とさないよう、実接続状態に同期
            vc = self.connections.get(guild_id)
            self.recording_status[guild_id] = bool(vc and getattr(vc, "recording", False))
                        
        except Exception as e:
            logger.error(f"RealTimeRecorder: Error in finished_callback: {e}", exc_info=True)
            vc = self.connections.get(guild_id)
            self.recording_status[guild_id] = bool(vc and getattr(vc, "recording", False))


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
        
        # バッファ保存頻度を下げる（10回に1回のみ保存）
        if not hasattr(self, '_save_counter'):
            self._save_counter = 0
            self._save_counter += 1
        if self._save_counter >= 10:
            self._save_counter = 0
            self.save_buffers()

    def get_buffer_health_summary(self, guild_id: int, user_id: Optional[int] = None, max_entries: int = 5) -> Dict[str, Any]:
        """連続バッファの健全性を簡易集計"""
        now = time.time()
        self._prune_continuous_buffers(guild_id, current_time=now)
        buffers = self.continuous_buffers.get(guild_id, {})
        target_user_ids = [user_id] if user_id else list(buffers.keys())
        entries = []

        for uid in target_user_ids:
            chunks = buffers.get(uid)
            if not chunks:
                continue
            last_chunk = max(chunks, key=lambda c: c[2])
            seconds_since_last = max(0.0, now - last_chunk[2])
            entries.append(
                {
                    "user_id": uid,
                    "chunk_count": len(chunks),
                    "last_start": last_chunk[1],
                    "last_end": last_chunk[2],
                    "seconds_since_last": seconds_since_last,
                }
            )

        entries.sort(key=lambda item: item["seconds_since_last"])
        if len(entries) > max_entries:
            entries = entries[:max_entries]

        return {
            "guild_id": guild_id,
            "tracked_users": len(buffers),
            "entries": entries,
            "has_data": bool(entries),
        }

    def _prune_continuous_buffers(self, guild_id: int, current_time: Optional[float] = None) -> None:
        """連続バッファから期限切れチャンクを全ユーザー分掃除"""
        guild_buffers = self.continuous_buffers.get(guild_id)
        if not guild_buffers:
            return

        now = current_time if current_time is not None else time.time()
        cutoff = now - self.CONTINUOUS_BUFFER_DURATION

        removed_count = 0
        removed_users = 0
        for uid in list(guild_buffers.keys()):
            chunks = guild_buffers.get(uid, [])
            filtered_chunks = [chunk for chunk in chunks if chunk[2] >= cutoff]
            removed_count += max(0, len(chunks) - len(filtered_chunks))
            if filtered_chunks:
                guild_buffers[uid] = filtered_chunks
            else:
                del guild_buffers[uid]
                removed_users += 1

        if not guild_buffers:
            del self.continuous_buffers[guild_id]

        if removed_count > 0:
            logger.debug(
                "RealTimeRecorder: Pruned %s expired continuous chunks (%s users) for guild %s",
                removed_count,
                removed_users,
                guild_id,
            )
    
    def _add_to_continuous_buffer(self, guild_id: int, user_id: int, audio_data: bytes, timestamp: float) -> bool:
        """連続音声バッファに音声データを追加"""
        if guild_id not in self.continuous_buffers:
            self.continuous_buffers[guild_id] = {}
        if user_id not in self.continuous_buffers[guild_id]:
            self.continuous_buffers[guild_id][user_id] = []
        
        # WAVヘッダーから実際の長さを算出（失敗時は推定値を使用）
        actual_duration = 0.0
        try:
            with wave.open(io.BytesIO(audio_data), "rb") as wav_file:
                frames = wav_file.getnframes()
                framerate = wav_file.getframerate() or self.DEFAULT_SAMPLE_RATE
                if frames and framerate:
                    actual_duration = frames / framerate
        except Exception as e:
            logger.debug(f"RealTimeRecorder: Failed to read WAV duration: {e}")

        if actual_duration <= 0:
            # WAV解析に失敗した場合は簡易推定（サンプリングレート48kHz/16bitステレオ前提）
            wav_data_size = max(len(audio_data) - 44, 0)
            actual_duration = wav_data_size / (self.DEFAULT_SAMPLE_RATE * self.DEFAULT_CHANNELS * self.DEFAULT_SAMPLE_WIDTH)

        end_time = timestamp
        start_time = max(0.0, end_time - actual_duration)

        # 直近のチャンクとほぼ同一であればスキップ（チェックポイントとコールバックの重複対策）
        chunk_signature = hashlib.blake2b(audio_data, digest_size=16).digest()
        last_meta = self._last_chunk_meta.get(guild_id, {}).get(user_id)
        if last_meta:
            last_signature, last_start, last_end = last_meta
            if (
                chunk_signature == last_signature
                and abs(last_start - start_time) <= 0.2
                and abs(last_end - end_time) <= 0.2
            ):
                logger.debug(
                    "RealTimeRecorder: Skipped duplicate chunk for guild %s user %s (start %.3f end %.3f)",
                    guild_id,
                    user_id,
                    start_time,
                    end_time,
                )
                return False

        self.continuous_buffers[guild_id][user_id].append((audio_data, start_time, end_time))
        
        # 5分より古いデータを削除
        current_time = time.time()
        filtered_chunks = [
            (chunk, s_time, e_time)
            for chunk, s_time, e_time in self.continuous_buffers[guild_id][user_id]
            if current_time - e_time <= self.CONTINUOUS_BUFFER_DURATION
        ]
        self.continuous_buffers[guild_id][user_id] = filtered_chunks

        if filtered_chunks:
            last_chunk, last_start, last_end = filtered_chunks[-1]
            last_signature = hashlib.blake2b(last_chunk, digest_size=16).digest()
            if guild_id not in self._last_chunk_meta:
                self._last_chunk_meta[guild_id] = {}
            self._last_chunk_meta[guild_id][user_id] = (last_signature, last_start, last_end)
        else:
            if guild_id in self._last_chunk_meta and user_id in self._last_chunk_meta[guild_id]:
                del self._last_chunk_meta[guild_id][user_id]
                if not self._last_chunk_meta[guild_id]:
                    del self._last_chunk_meta[guild_id]
        
        actual_duration = end_time - start_time
        logger.info(f"RealTimeRecorder: Added audio chunk for guild {guild_id}, user {user_id}")
        logger.info(f"  - Duration: {actual_duration:.1f}s")
        logger.info(f"  - Time range: {current_time - end_time:.1f}s ago to {current_time - start_time:.1f}s ago")
        logger.info(f"  - Start: {start_time:.1f}, End: {end_time:.1f}, Now: {current_time:.1f}")
        return True

    async def _forward_to_recording_callback_manager(self, guild_id: int, user_id: int, audio_data: bytes):
        """ReplayBufferManager 用に RecordingCallbackManager へ音声を転送"""
        manager = recording_callback_manager
        if not manager or not getattr(manager, "is_initialized", False):
            return

        now = time.time()
        signature = hashlib.blake2b(audio_data, digest_size=16).digest()
        guild_meta = self._last_callback_chunk_meta.setdefault(guild_id, {})
        last_meta = guild_meta.get(user_id)
        if last_meta:
            last_signature, last_timestamp = last_meta
            if signature == last_signature and abs(now - last_timestamp) <= 0.2:
                logger.debug(
                    "RealTimeRecorder: Skipped duplicate callback chunk for guild %s user %s",
                    guild_id,
                    user_id,
                )
                return

        guild_meta[user_id] = (signature, now)
        try:
            await manager.process_audio_data(guild_id=guild_id, user_id=user_id, audio_data=audio_data)
        except Exception as e:
            logger.warning(
                "RealTimeRecorder: Failed to forward audio chunk to RecordingCallbackManager (guild=%s user=%s): %s",
                guild_id,
                user_id,
                e,
            )
    
    def get_audio_for_time_range(self, guild_id: int, duration_seconds: float, user_id: Optional[int] = None) -> Dict[int, bytes]:
        """指定した時間範囲の音声データを取得（現在時刻から過去N秒分）"""
        current_time = time.time()
        self._prune_continuous_buffers(guild_id, current_time=current_time)
        start_time = current_time - duration_seconds
        
        logger.info(f"RealTimeRecorder: Extracting audio for guild {guild_id}")
        logger.info(f"  - Requested duration: {duration_seconds}s")
        logger.info(f"  - Time range: {start_time:.1f} to {current_time:.1f}")
        logger.info(f"  - From {duration_seconds:.1f}s ago to now")
        
        result = {}
        
        if guild_id not in self.continuous_buffers:
            logger.warning(f"RealTimeRecorder: No continuous buffers for guild {guild_id}")
            return result
        
        guild_buffers = self.continuous_buffers[guild_id]
        logger.info(f"  - Available users: {list(guild_buffers.keys())}")
        
        if user_id:
            # 特定ユーザーのみ
            if user_id in guild_buffers:
                audio_data = self._extract_audio_range(guild_buffers[user_id], start_time, current_time)
                if audio_data:
                    result[user_id] = audio_data
                logger.info(f"  - User {user_id}: {len(audio_data) if audio_data else 0} bytes")
            else:
                logger.warning(f"  - User {user_id} not found in buffers")
        else:
            # 全ユーザー
            for uid, chunks in guild_buffers.items():
                audio_data = self._extract_audio_range(chunks, start_time, current_time)
                if audio_data:
                    result[uid] = audio_data
                    logger.info(f"  - User {uid}: {len(audio_data)} bytes")
                else:
                    logger.info(f"  - User {uid}: no data in time range")

        if not result and guild_buffers:
            health = self.get_buffer_health_summary(guild_id, user_id)
            if health["entries"]:
                stalest = max(health["entries"], key=lambda item: item["seconds_since_last"])
                logger.warning(
                    "RealTimeRecorder: No matching chunks in requested window. Last chunk for user %s ended %.1fs ago",
                    stalest["user_id"],
                    stalest["seconds_since_last"],
                )
            else:
                logger.warning("RealTimeRecorder: No matching chunks and no entries for requested user %s", user_id)
            self._log_voice_diagnostics(
                reason="replay_no_matching_chunks",
                guild_id=guild_id,
                target_user_id=user_id,
            )
        
        logger.info(f"RealTimeRecorder: Extracted {duration_seconds}s audio for guild {guild_id}, {len(result)} users with data")
        return result
    
    def _extract_audio_range(self, chunks: list, start_time: float, end_time: float) -> bytes:
        """指定した時間範囲の音声チャンクを結合"""
        logger.debug(f"RealTimeRecorder: _extract_audio_range called")
        logger.debug(f"  - Target time range: {start_time:.1f} to {end_time:.1f}")
        logger.debug(f"  - Available chunks: {len(chunks)}")
        
        matching_chunks = []
        
        for i, (audio_data, chunk_start, chunk_end) in enumerate(chunks):
            logger.debug(f"  - Chunk {i}: {chunk_start:.1f} to {chunk_end:.1f}")
            # 時間範囲と重複するチャンクを選択
            if chunk_end >= start_time and chunk_start <= end_time:
                matching_chunks.append((audio_data, chunk_start, chunk_end))
                logger.debug(f"    -> MATCHED (overlaps with target range)")
            else:
                logger.debug(f"    -> SKIPPED (no overlap)")
        
        logger.debug(f"  - Matching chunks: {len(matching_chunks)}")
        
        if not matching_chunks:
            logger.warning(f"RealTimeRecorder: No matching chunks found for time range {start_time:.1f} to {end_time:.1f}")
            return b""
        
        # 時系列順にソート
        matching_chunks.sort(key=lambda x: x[1])
        
        # WAVファイルを正しく結合
        if not matching_chunks:
            logger.warning("RealTimeRecorder: No chunks to combine")
            return b''
        
        # 最初のチャンクからWAVヘッダー情報を取得
        first_audio_data = matching_chunks[0][0]
        if len(first_audio_data) < 44:
            logger.error(f"RealTimeRecorder: First chunk too small for WAV header: {len(first_audio_data)} bytes")
            return b''
            
        # WAVヘッダーを解析
        try:
            import wave
            with wave.open(io.BytesIO(first_audio_data), 'rb') as first_wave:
                framerate = first_wave.getframerate()
                sampwidth = first_wave.getsampwidth()
                nchannels = first_wave.getnchannels()
                logger.debug(f"RealTimeRecorder: WAV params - {nchannels}ch, {sampwidth}bytes, {framerate}Hz")
        except Exception as e:
            logger.error(f"RealTimeRecorder: Failed to parse WAV header: {e}")
            return b''
        
        # 全チャンクの音声データ部分を結合
        combined_pcm_data = io.BytesIO()
        total_frames = 0
        
        for i, (audio_data, chunk_start, chunk_end) in enumerate(matching_chunks):
            try:
                with wave.open(io.BytesIO(audio_data), 'rb') as chunk_wave:
                    pcm_data = chunk_wave.readframes(chunk_wave.getnframes())
                    combined_pcm_data.write(pcm_data)
                    total_frames += chunk_wave.getnframes()
                    logger.debug(f"  - Chunk {i}: {len(pcm_data)} PCM bytes, {chunk_wave.getnframes()} frames")
            except Exception as e:
                logger.warning(f"  - Chunk {i}: Failed to extract PCM data: {e}")
                continue
        
        # 新しいWAVファイルを作成
        combined_audio = io.BytesIO()
        try:
            with wave.open(combined_audio, 'wb') as output_wave:
                output_wave.setnchannels(nchannels)
                output_wave.setsampwidth(sampwidth)
                output_wave.setframerate(framerate)
                pcm_data = combined_pcm_data.getvalue()
                output_wave.writeframes(pcm_data)
                
            result = combined_audio.getvalue()
            logger.info(f"RealTimeRecorder: Combined {len(matching_chunks)} chunks into {len(result)} bytes")
            logger.info(f"  - Total frames: {total_frames}, PCM data: {len(pcm_data)} bytes")
            return result
            
        except Exception as e:
            logger.error(f"RealTimeRecorder: Failed to create combined WAV: {e}")
            return b''
    
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
                    await self._stop_recording_non_blocking(vc)
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
                # 最新2件のみ保存（ファイルサイズ削減）
                recent_buffers = sorted(buffers, key=lambda x: x[1])[-2:]
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
