"""
TTS（Text-to-Speech）ユーティリティ
Style-Bert-VITS2を使用した軽量化TTS機能
"""

import asyncio
import aiohttp
import aiofiles
import logging
import io
import hashlib
from pathlib import Path
from typing import Dict, Any, Optional, Union
from datetime import datetime, timedelta
import json

logger = logging.getLogger(__name__)


class TTSCache:
    """TTS音声のキャッシュ管理"""
    
    def __init__(self, cache_dir: Path, max_size: int = 5, cache_hours: int = 24):
        self.cache_dir = cache_dir
        self.max_size = max_size
        self.cache_hours = cache_hours
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_info_file = self.cache_dir / "cache_info.json"
        self.cache_info = self.load_cache_info()
    
    def load_cache_info(self) -> Dict[str, Any]:
        """キャッシュ情報を読み込み"""
        try:
            if self.cache_info_file.exists():
                with open(self.cache_info_file, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load cache info: {e}")
        return {}
    
    def save_cache_info(self):
        """キャッシュ情報を保存"""
        try:
            with open(self.cache_info_file, "w", encoding="utf-8") as f:
                json.dump(self.cache_info, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save cache info: {e}")
    
    def get_cache_key(self, text: str, model_id: str = "default") -> str:
        """テキストとモデルIDからキャッシュキーを生成"""
        content = f"{text}_{model_id}"
        return hashlib.md5(content.encode()).hexdigest()
    
    def get_cache_path(self, cache_key: str) -> Path:
        """キャッシュファイルのパスを取得"""
        return self.cache_dir / f"{cache_key}.wav"
    
    async def get(self, text: str, model_id: str = "default") -> Optional[bytes]:
        """キャッシュから音声データを取得"""
        cache_key = self.get_cache_key(text, model_id)
        cache_path = self.get_cache_path(cache_key)
        
        if not cache_path.exists():
            return None
        
        # キャッシュの有効期限チェック
        if cache_key in self.cache_info:
            cached_time = datetime.fromisoformat(self.cache_info[cache_key]["cached_at"])
            if datetime.now() - cached_time > timedelta(hours=self.cache_hours):
                await self.remove(cache_key)
                return None
        
        try:
            async with aiofiles.open(cache_path, "rb") as f:
                data = await f.read()
            
            # アクセス時刻を更新
            self.cache_info[cache_key]["accessed_at"] = datetime.now().isoformat()
            self.save_cache_info()
            
            logger.debug(f"Cache hit: {text[:20]}...")
            return data
            
        except Exception as e:
            logger.error(f"Failed to read cache: {e}")
            return None
    
    async def set(self, text: str, model_id: str, audio_data: bytes):
        """音声データをキャッシュに保存"""
        cache_key = self.get_cache_key(text, model_id)
        cache_path = self.get_cache_path(cache_key)
        
        # キャッシュサイズ制限チェック
        await self.cleanup_if_needed()
        
        try:
            async with aiofiles.open(cache_path, "wb") as f:
                await f.write(audio_data)
            
            # キャッシュ情報を更新
            self.cache_info[cache_key] = {
                "text": text,
                "model_id": model_id,
                "cached_at": datetime.now().isoformat(),
                "accessed_at": datetime.now().isoformat(),
                "size": len(audio_data)
            }
            self.save_cache_info()
            
            logger.debug(f"Cached: {text[:20]}...")
            
        except Exception as e:
            logger.error(f"Failed to save cache: {e}")
    
    async def remove(self, cache_key: str):
        """キャッシュエントリを削除"""
        cache_path = self.get_cache_path(cache_key)
        try:
            if cache_path.exists():
                cache_path.unlink()
            if cache_key in self.cache_info:
                del self.cache_info[cache_key]
            self.save_cache_info()
        except Exception as e:
            logger.error(f"Failed to remove cache: {e}")
    
    async def cleanup_if_needed(self):
        """必要に応じてキャッシュをクリーンアップ"""
        if len(self.cache_info) < self.max_size:
            return
        
        # アクセス時刻順にソート（古いものから削除）
        sorted_items = sorted(
            self.cache_info.items(),
            key=lambda x: x[1]["accessed_at"]
        )
        
        # 最大サイズを超えた分を削除
        while len(sorted_items) >= self.max_size:
            cache_key, _ = sorted_items.pop(0)
            await self.remove(cache_key)


class TTSManager:
    """TTS機能の管理クラス"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.api_url = config.get("tts", {}).get("api_url", "http://127.0.0.1:5000")
        self.timeout = config.get("tts", {}).get("timeout", 10)
        self.cache = TTSCache(
            cache_dir=Path("cache/tts"),
            max_size=config.get("tts", {}).get("cache_size", 5),
            cache_hours=config.get("tts", {}).get("cache_hours", 24)
        )
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def init_session(self):
        """HTTP セッションを初期化"""
        if self.session is None:
            connector = aiohttp.TCPConnector(limit=10, limit_per_host=5)
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            self.session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout
            )
    
    async def close_session(self):
        """HTTP セッションを閉じる"""
        if self.session:
            await self.session.close()
            self.session = None
    
    async def is_api_available(self) -> bool:
        """TTSAPIサーバーが利用可能かチェック"""
        try:
            await self.init_session()
            # Style-Bert-VITS2は/statusエンドポイントを使用
            async with self.session.get(f"{self.api_url}/status") as response:
                return response.status == 200
        except Exception as e:
            logger.warning(f"TTS API not available: {e}")
            return False
    
    async def generate_speech(
        self, 
        text: str, 
        model_id: str = "default",
        speaker_id: int = 0,
        style: str = "Neutral"
    ) -> Optional[bytes]:
        """テキストから音声を生成"""
        if len(text.strip()) == 0:
            return None
        
        # 文字数制限
        max_length = self.config.get("tts", {}).get("max_text_length", 100)
        if len(text) > max_length:
            text = text[:max_length] + "..."
            logger.warning(f"Text truncated to {max_length} characters")
        
        # キャッシュから取得を試行
        cached_audio = await self.cache.get(text, model_id)
        if cached_audio:
            return cached_audio
        
        # APIサーバーが利用できない場合はフォールバック
        if not await self.is_api_available():
            logger.warning("TTS API not available, using fallback")
            return await self.generate_fallback_speech(text)
        
        try:
            await self.init_session()
            
            # Style-Bert-VITS2 API呼び出し
            params = {
                "text": text,
                "model_id": model_id,
                "speaker_id": speaker_id,
                "style": style,
                "language": "JP"
            }
            
            logger.info(f"TTS API request: {self.api_url}/voice with params: {params}")
            
            # Style-Bert-VITS2はGETメソッドでクエリパラメータを送信
            async with self.session.get(
                f"{self.api_url}/voice",
                params=params
            ) as response:
                logger.info(f"TTS API response status: {response.status}")
                if response.status == 200:
                    audio_data = await response.read()
                    
                    # キャッシュに保存
                    await self.cache.set(text, model_id, audio_data)
                    
                    logger.info(f"Generated speech: {text[:30]}...")
                    return audio_data
                else:
                    error_text = await response.text()
                    logger.error(f"TTS API error: {response.status} - {error_text}")
                    return await self.generate_fallback_speech(text)
                    
        except Exception as e:
            logger.error(f"Failed to generate speech: {e}")
            return await self.generate_fallback_speech(text)
    
    async def generate_fallback_speech(self, text: str) -> Optional[bytes]:
        """フォールバック用のシンプルな音声生成（ビープ音など）"""
        try:
            # 簡単なビープ音を生成（実際には無音または短いトーン）
            import numpy as np
            import wave
            
            # 440Hz の短いトーン（1秒）
            sample_rate = 22050
            duration = min(len(text) * 0.1, 2.0)  # テキスト長に応じて調整、最大2秒
            
            t = np.linspace(0, duration, int(sample_rate * duration))
            frequency = 440  # A4音階
            audio = np.sin(2 * np.pi * frequency * t) * 0.3  # 音量を抑制
            
            # WAVフォーマットでバイト配列に変換
            audio_int = (audio * 32767).astype(np.int16)
            
            buffer = io.BytesIO()
            with wave.open(buffer, 'wb') as wav_file:
                wav_file.setnchannels(1)  # モノラル
                wav_file.setsampwidth(2)  # 16-bit
                wav_file.setframerate(sample_rate)
                wav_file.writeframes(audio_int.tobytes())
            
            logger.info(f"Generated fallback audio for: {text[:30]}...")
            return buffer.getvalue()
            
        except Exception as e:
            logger.error(f"Failed to generate fallback speech: {e}")
            return None
    
    async def cleanup(self):
        """リソースのクリーンアップ"""
        await self.close_session()