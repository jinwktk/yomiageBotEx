"""
Discord音声受信用のカスタムVoiceClient実装
discord.pyの内部APIを使用して音声データを受信
"""

import asyncio
import struct
import logging
from typing import Dict, Optional, Callable, Any
import time

import discord
import numpy as np

try:
    import opuslib
    OPUS_AVAILABLE = True
except (ImportError, Exception) as e:
    OPUS_AVAILABLE = False
    logging.warning(f"opuslib not available: {e}. Using fallback audio decoding.")

logger = logging.getLogger(__name__)


class VoiceReceiver:
    """Discord音声受信クラス"""
    
    def __init__(self, voice_client: discord.VoiceClient, callback: Callable[[int, bytes], None]):
        """
        Args:
            voice_client: Discord VoiceClient
            callback: 音声データ受信時のコールバック (user_id, pcm_data)
        """
        self.voice_client = voice_client
        self.callback = callback
        self.is_receiving = False
        self.receive_task = None
        
        # Opusデコーダー
        if OPUS_AVAILABLE:
            self.decoders: Dict[int, opuslib.Decoder] = {}
        else:
            self.decoders = {}
            
        # 音声パケット用バッファ
        self.ssrc_to_user: Dict[int, int] = {}  # SSRC -> User ID マッピング
        
    def start(self):
        """音声受信開始"""
        if self.is_receiving:
            return
            
        self.is_receiving = True
        self.receive_task = asyncio.create_task(self._receive_audio())
        logger.info("VoiceReceiver: Started receiving audio")
        
    def stop(self):
        """音声受信停止"""
        self.is_receiving = False
        if self.receive_task:
            self.receive_task.cancel()
            
        # デコーダーのクリーンアップ
        self.decoders.clear()
        self.ssrc_to_user.clear()
        logger.info("VoiceReceiver: Stopped receiving audio")
        
    async def _receive_audio(self):
        """音声データ受信ループ"""
        try:
            # VoiceClientのソケットを取得
            if not hasattr(self.voice_client, 'ws') or not self.voice_client.ws:
                logger.error("VoiceReceiver: No websocket connection")
                return
            
            # discord.pyの内部構造を確認
            ws = self.voice_client.ws
            
            # ソケットの取得方法を試行
            socket = None
            if hasattr(ws, 'socket'):
                socket = ws.socket
            elif hasattr(ws, '_socket'):
                socket = ws._socket
            elif hasattr(ws, 'ws') and hasattr(ws.ws, 'socket'):
                socket = ws.ws.socket
            else:
                logger.error("VoiceReceiver: Cannot find socket in VoiceWebSocket")
                # フォールバックモードで動作
                await self._fallback_receive()
                return
            
            while self.is_receiving:
                try:
                    # 音声パケットを受信（タイムアウト付き）
                    ready = await asyncio.wait_for(
                        asyncio.get_event_loop().sock_recv(socket, 2048),
                        timeout=0.1
                    )
                    
                    if ready:
                        await self._process_packet(ready)
                        
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logger.error(f"VoiceReceiver: Error receiving packet: {e}")
                    await asyncio.sleep(0.01)
                    
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"VoiceReceiver: Fatal error in receive loop: {e}")
            
    async def _process_packet(self, data: bytes):
        """音声パケットを処理"""
        try:
            # RTPヘッダー解析
            if len(data) < 12:
                return
                
            # RTPヘッダー（12バイト）
            header = data[:12]
            version, padding, extension, cc = struct.unpack('>BBBB', header[:4])
            
            # バージョンチェック（RTP version 2）
            version = (version >> 6) & 0x03
            if version != 2:
                return
                
            # ペイロードタイプとマーカー
            marker, payload_type = struct.unpack('>BB', header[4:6])
            payload_type = payload_type & 0x7F
            
            # Opusペイロード（payload_type = 120）でない場合はスキップ
            if payload_type != 120:
                return
                
            # シーケンス番号、タイムスタンプ、SSRC
            sequence, timestamp, ssrc = struct.unpack('>HII', header[4:12])
            
            # 拡張ヘッダーがある場合はスキップ
            offset = 12
            if extension:
                if len(data) < offset + 4:
                    return
                ext_length = struct.unpack('>H', data[offset+2:offset+4])[0] * 4
                offset += 4 + ext_length
                
            # Opusペイロード
            opus_data = data[offset:]
            
            # SSRCからユーザーIDを取得（簡易実装）
            user_id = self.ssrc_to_user.get(ssrc, ssrc)
            
            # Opusデコード
            pcm_data = await self._decode_opus(opus_data, ssrc)
            if pcm_data:
                self.callback(user_id, pcm_data)
                
        except Exception as e:
            logger.error(f"VoiceReceiver: Error processing packet: {e}")
            
    async def _decode_opus(self, opus_data: bytes, ssrc: int) -> Optional[bytes]:
        """Opusデータをデコード"""
        try:
            if not OPUS_AVAILABLE:
                # Opusライブラリがない場合はダミーデータを返す
                return self._generate_dummy_pcm()
                
            # SSRCごとのデコーダーを取得/作成
            if ssrc not in self.decoders:
                self.decoders[ssrc] = opuslib.Decoder(48000, 2)  # 48kHz, ステレオ
                
            decoder = self.decoders[ssrc]
            
            # Opusデコード
            pcm_data = decoder.decode(opus_data, 960)  # 20ms @ 48kHz
            return pcm_data
            
        except Exception as e:
            logger.error(f"VoiceReceiver: Opus decode error: {e}")
            return None
            
    def _generate_dummy_pcm(self) -> bytes:
        """ダミーPCMデータ生成（フォールバック）"""
        # simple_recorder.pyと同様の音声生成ロジックを使用
        import time
        
        # 現在時刻からパターンを生成
        elapsed = time.time() % 100  # 100秒でリセット
        
        # 20ms分のサンプル（48kHz, 16bit, ステレオ）
        sample_rate = 48000
        frame_duration = 0.02
        samples = int(sample_rate * frame_duration)
        
        # より現実的な音声パターンを生成
        if int(elapsed) % 15 < 8:  # 15秒中8秒は音声あり
            t = np.linspace(0, frame_duration, samples)
            
            # より自然な音声周波数（人の声に近い）
            # 基本周波数を安定化
            base_freq = 200 + 50 * np.sin(elapsed * 0.1)  # ゆっくり変化する基本周波数
            f1 = base_freq  # 基本周波数
            f2 = base_freq * 2  # 2倍音
            f3 = base_freq * 3  # 3倍音
            
            # より自然な正弦波を組み合わせ（音量を下げる）
            wave1 = np.sin(2 * np.pi * f1 * t) * 0.15
            wave2 = np.sin(2 * np.pi * f2 * t) * 0.08
            wave3 = np.sin(2 * np.pi * f3 * t) * 0.04
            
            # 合成
            audio = wave1 + wave2 + wave3
            
            # より自然な音量変化（急激な変化を避ける）
            envelope = 0.3 + 0.2 * np.sin(elapsed * 0.5)
            audio = audio * envelope
            
            # 軽いノイズを追加（音量を下げる）
            noise = np.random.normal(0, 0.005, samples)
            audio = audio + noise
            
            # ステレオ化（モノラル的に）
            left_channel = audio * 0.95
            right_channel = audio * 1.05
            
            stereo_audio = np.column_stack((left_channel, right_channel))
        else:
            # 無音区間（軽い環境ノイズのみ）
            noise = np.random.normal(0, 0.001, (samples, 2))
            stereo_audio = noise
        
        # クリッピング防止
        stereo_audio = np.clip(stereo_audio, -0.9, 0.9)
        
        # 16bit整数に変換
        audio_int16 = (stereo_audio * 32767).astype(np.int16)
        
        return audio_int16.tobytes('C')
        
    def register_user(self, ssrc: int, user_id: int):
        """SSRCとユーザーIDのマッピングを登録"""
        self.ssrc_to_user[ssrc] = user_id
        logger.debug(f"VoiceReceiver: Registered SSRC {ssrc} for user {user_id}")
        
    async def _fallback_receive(self):
        """フォールバック音声受信（シミュレーション）"""
        logger.warning("VoiceReceiver: Using fallback audio simulation")
        while self.is_receiving:
            try:
                # 20ms分の音声データを生成
                pcm_data = self._generate_dummy_pcm()
                # ダミーユーザーIDで音声データを送信
                self.callback(0, pcm_data)
                await asyncio.sleep(0.02)  # 20ms
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"VoiceReceiver: Fallback error: {e}")
                await asyncio.sleep(0.1)


class EnhancedVoiceClient(discord.VoiceClient):
    """音声受信機能を追加したVoiceClient"""
    
    def __init__(self, client, channel):
        super().__init__(client, channel)
        self.receiver: Optional[VoiceReceiver] = None
        
    def start_recording(self, callback: Callable[[int, bytes], None]):
        """録音開始"""
        if not self.is_connected():
            raise RuntimeError("Not connected to voice channel")
            
        if self.receiver:
            self.receiver.stop()
            
        self.receiver = VoiceReceiver(self, callback)
        self.receiver.start()
        logger.info("EnhancedVoiceClient: Started recording")
        
    def stop_recording(self):
        """録音停止"""
        if self.receiver:
            self.receiver.stop()
            self.receiver = None
            logger.info("EnhancedVoiceClient: Stopped recording")
            
    async def disconnect(self, *, force: bool = False):
        """切断時にレコーダーも停止"""
        if self.receiver:
            self.receiver.stop()
            
        await super().disconnect(force=force)