"""
TTS Client v2 - StyleBertVITS2 API連携
シンプルなTTS音声合成クライアント
"""

import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Optional

import aiohttp
import discord

logger = logging.getLogger(__name__)

class TTSClientV2:
    """StyleBertVITS2 APIクライアント"""
    
    def __init__(self, config: dict):
        self.config = config
        self.session: Optional[aiohttp.ClientSession] = None
        
        # 設定値
        self.api_url = config.get('api_url', 'http://localhost:5000')
        self.default_model = config.get('default_model', 'jvnv-F1-jp')
        self.default_speaker = config.get('default_speaker', 0)
        self.timeout = config.get('timeout', 30)
        self.max_length = config.get('max_length', 100)
        
        logger.info(f"TTS Client initialized - API: {self.api_url}")
    
    async def __aenter__(self):
        """非同期コンテキストマネージャー開始"""
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """非同期コンテキストマネージャー終了"""
        await self.close()
    
    async def start(self):
        """HTTPセッション開始"""
        if not self.session:
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            self.session = aiohttp.ClientSession(timeout=timeout)
            logger.debug("TTS HTTP session started")
    
    async def close(self):
        """HTTPセッション終了"""
        if self.session:
            await self.session.close()
            self.session = None
            logger.debug("TTS HTTP session closed")
    
    async def is_api_available(self) -> bool:
        """TTS APIの可用性チェック"""
        try:
            if not self.session:
                await self.start()
            
            async with self.session.get(f"{self.api_url}/status") as response:
                return response.status == 200
                
        except Exception as e:
            logger.debug(f"TTS API not available: {e}")
            return False
    
    async def synthesize_speech(self, text: str, model: Optional[str] = None, speaker: Optional[int] = None) -> Optional[discord.FFmpegPCMAudio]:
        """音声合成してDiscord再生用オーディオソースを返す"""
        try:
            # テキスト長チェック
            if len(text) > self.max_length:
                text = text[:self.max_length]
                logger.warning(f"Text truncated to {self.max_length} characters")
            
            # API可用性チェック
            if not await self.is_api_available():
                logger.warning("TTS API not available")
                return None
            
            # パラメータ設定
            params = {
                'text': text,
                'model_name': model or self.default_model,
                'speaker_id': speaker or self.default_speaker,
                'style': 'Neutral',
                'style_weight': 1.0,
                'auto_split': True,
                'split_interval': 0.5,
                'emotion': 'Neutral',
                'emotion_weight': 1.0
            }
            
            logger.debug(f"TTS request: {text[:50]}...")
            
            # API呼び出し
            async with self.session.get(f"{self.api_url}/voice", params=params) as response:
                if response.status != 200:
                    logger.error(f"TTS API error: {response.status}")
                    return None
                
                # 音声データ取得
                audio_data = await response.read()
                
                if not audio_data:
                    logger.warning("Empty audio data received")
                    return None
                
                # 一時ファイルに保存
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
                temp_file.write(audio_data)
                temp_file.close()
                
                # Discord再生用オーディオソース作成
                audio_source = discord.FFmpegPCMAudio(
                    temp_file.name,
                    options='-loglevel panic'
                )
                
                logger.debug(f"TTS audio generated: {len(audio_data)} bytes")
                return audio_source
                
        except asyncio.TimeoutError:
            logger.error("TTS API timeout")
            return None
        except Exception as e:
            logger.error(f"TTS synthesis error: {e}", exc_info=True)
            return None
    
    def preprocess_text(self, text: str) -> str:
        """テキスト前処理"""
        # 基本的なクリーニング
        text = text.strip()
        
        # URL除去
        import re
        text = re.sub(r'https?://[^\s]+', 'URL', text)
        
        # メンション変換
        text = re.sub(r'<@!?(\d+)>', 'メンション', text)
        text = re.sub(r'<#(\d+)>', 'チャンネル', text)
        text = re.sub(r'<:(\w+):\d+>', r'\1', text)  # 絵文字名のみ
        
        # 空文字チェック
        if not text.strip():
            return ""
        
        return text