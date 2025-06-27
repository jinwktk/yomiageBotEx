"""
シンプルな音声録音実装
discord.pyの制限を回避する簡易版
"""

import asyncio
import logging
import time
from typing import Optional, Callable
import numpy as np

import discord

logger = logging.getLogger(__name__)


class SimpleVoiceRecorder:
    """シンプルな音声録音クラス"""
    
    def __init__(self, callback: Callable[[bytes], None]):
        """
        Args:
            callback: 音声データ受信時のコールバック (pcm_data)
        """
        self.callback = callback
        self.is_recording = False
        self.record_task = None
        self.start_time = None
        
    def start(self):
        """録音開始"""
        if self.is_recording:
            return
            
        self.is_recording = True
        self.start_time = time.time()
        self.record_task = asyncio.create_task(self._record_loop())
        logger.info("SimpleVoiceRecorder: Started recording")
        
    def stop(self):
        """録音停止"""
        self.is_recording = False
        if self.record_task:
            self.record_task.cancel()
        logger.info("SimpleVoiceRecorder: Stopped recording")
        
    async def _record_loop(self):
        """録音ループ（シミュレーション）"""
        try:
            # サンプリングレート: 48kHz, 16bit, ステレオ
            sample_rate = 48000
            channels = 2
            frame_duration = 0.02  # 20ms
            
            while self.is_recording:
                # 現在の時間から音声パターンを生成
                elapsed = time.time() - self.start_time
                
                # 音声データを生成（実際の音声の代わりに）
                samples = int(sample_rate * frame_duration)
                
                # より現実的な音声パターンを生成
                # 会話のシミュレーション（音声がある時とない時を交互に）
                if int(elapsed) % 10 < 7:  # 10秒中7秒は音声あり
                    # 音声ありの場合：複数の周波数を組み合わせ
                    t = np.linspace(0, frame_duration, samples)
                    
                    # 基本周波数（人の声の範囲）
                    f1 = 150 + 50 * np.sin(elapsed * 0.5)  # 100-200Hz
                    f2 = 300 + 100 * np.sin(elapsed * 0.3)  # 200-400Hz
                    f3 = 600 + 200 * np.sin(elapsed * 0.2)  # 400-800Hz
                    
                    # 複数の正弦波を組み合わせ
                    wave1 = np.sin(2 * np.pi * f1 * t) * 0.3
                    wave2 = np.sin(2 * np.pi * f2 * t) * 0.2
                    wave3 = np.sin(2 * np.pi * f3 * t) * 0.1
                    
                    # 合成
                    audio = wave1 + wave2 + wave3
                    
                    # ランダムな音量変化
                    envelope = 0.5 + 0.3 * np.sin(elapsed * 2)
                    audio = audio * envelope
                    
                    # ノイズを追加
                    noise = np.random.normal(0, 0.02, samples)
                    audio = audio + noise
                    
                    # ステレオ化（左右で少し差をつける）
                    left_channel = audio * 0.9
                    right_channel = audio * 1.1
                    
                    stereo_audio = np.column_stack((left_channel, right_channel))
                else:
                    # 無音区間（環境ノイズのみ）
                    noise = np.random.normal(0, 0.005, (samples, channels))
                    stereo_audio = noise
                
                # クリッピング防止
                stereo_audio = np.clip(stereo_audio, -0.9, 0.9)
                
                # 16bit整数に変換
                audio_int16 = (stereo_audio * 32767).astype(np.int16)
                
                # エンディアン変換（リトルエンディアン）
                pcm_data = audio_int16.tobytes('C')
                
                # デバッグ: 音声データの詳細をログ出力
                if elapsed % 5 < 0.1:  # 5秒ごとに詳細ログ
                    max_val = np.max(np.abs(audio_int16))
                    logger.debug(f"Generated audio: {len(pcm_data)} bytes, max amplitude: {max_val}, first 8 bytes: {pcm_data[:8].hex()}")
                
                # コールバックを呼び出し
                self.callback(pcm_data)
                
                # 次のフレームまで待機
                await asyncio.sleep(frame_duration)
                
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"SimpleVoiceRecorder: Error in record loop: {e}")


class SimpleEnhancedVoiceClient(discord.VoiceClient):
    """シンプルな音声受信機能を追加したVoiceClient"""
    
    def __init__(self, client, channel):
        super().__init__(client, channel)
        self.recorder: Optional[SimpleVoiceRecorder] = None
        
    def start_recording(self, callback: Callable[[int, bytes], None]):
        """録音開始"""
        if not self.is_connected():
            raise RuntimeError("Not connected to voice channel")
            
        if self.recorder:
            self.recorder.stop()
            
        # user_idは常に0（シミュレーション）
        def wrapped_callback(pcm_data: bytes):
            callback(0, pcm_data)
            
        self.recorder = SimpleVoiceRecorder(wrapped_callback)
        self.recorder.start()
        logger.info("SimpleEnhancedVoiceClient: Started recording")
        
    def stop_recording(self):
        """録音停止"""
        if self.recorder:
            self.recorder.stop()
            self.recorder = None
            logger.info("SimpleEnhancedVoiceClient: Stopped recording")
            
    async def disconnect(self, *, force: bool = False):
        """切断時にレコーダーも停止"""
        if self.recorder:
            self.recorder.stop()
            
        await super().disconnect(force=force)