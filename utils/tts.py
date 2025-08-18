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
    """TTS音声のキャッシュ管理（高性能版）"""
    
    def __init__(self, cache_dir: Path, max_size: int = 50, cache_hours: int = 48):
        self.cache_dir = cache_dir
        self.max_size = max_size
        self.cache_hours = cache_hours
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_info_file = self.cache_dir / "cache_info.json"
        self.cache_info = self.load_cache_info()
        
        # インメモリキャッシュ（小さなファイル用）
        self.memory_cache = {}
        self.memory_cache_limit = 10 * 1024 * 1024  # 10MB
        self.memory_cache_size = 0
    
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
        """キャッシュから音声データを取得（高速化版）"""
        cache_key = self.get_cache_key(text, model_id)
        
        # インメモリキャッシュから先にチェック
        if cache_key in self.memory_cache:
            logger.debug(f"Memory cache hit: {text[:20]}...")
            return self.memory_cache[cache_key]
        
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
            
            # 小さなファイルはインメモリキャッシュに追加
            if len(data) < 1024 * 1024 and self.memory_cache_size + len(data) < self.memory_cache_limit:  # 1MB未満
                self.memory_cache[cache_key] = data
                self.memory_cache_size += len(data)
            
            # アクセス時刻を更新
            self.cache_info[cache_key]["accessed_at"] = datetime.now().isoformat()
            self.save_cache_info()
            
            logger.debug(f"File cache hit: {text[:20]}...")
            return data
            
        except Exception as e:
            logger.error(f"Failed to read cache: {e}")
            return None
    
    async def set(self, text: str, model_id: str, audio_data: bytes):
        """音声データをキャッシュに保存（高速化版）"""
        cache_key = self.get_cache_key(text, model_id)
        cache_path = self.get_cache_path(cache_key)
        
        # キャッシュサイズ制限チェック
        await self.cleanup_if_needed()
        
        try:
            # 並列でファイル保存とメモリキャッシュ更新
            import asyncio
            
            async def save_to_file():
                async with aiofiles.open(cache_path, "wb") as f:
                    await f.write(audio_data)
            
            async def update_memory_cache():
                # 小さなファイルはインメモリキャッシュに追加
                if len(audio_data) < 1024 * 1024 and self.memory_cache_size + len(audio_data) < self.memory_cache_limit:  # 1MB未満
                    self.memory_cache[cache_key] = audio_data
                    self.memory_cache_size += len(audio_data)
            
            # 並列実行
            await asyncio.gather(save_to_file(), update_memory_cache())
            
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
        """キャッシュエントリを削除（高速化版）"""
        cache_path = self.get_cache_path(cache_key)
        try:
            if cache_path.exists():
                cache_path.unlink()
            
            # メモリキャッシュからも削除
            if cache_key in self.memory_cache:
                cache_size = len(self.memory_cache[cache_key])
                del self.memory_cache[cache_key]
                self.memory_cache_size -= cache_size
            
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
        # TTS設定をdata/tts_config.jsonから読み込み
        self.tts_config = self.load_tts_config()
        self.api_url = self.tts_config.get("api_url", "http://192.168.0.99:5000")
        self.timeout = self.tts_config.get("timeout", 60)
        self.cache = TTSCache(
            cache_dir=Path("cache/tts"),
            max_size=self.tts_config.get("cache_size", 20),  # キャッシュサイズ増加（5→20）
            cache_hours=self.tts_config.get("cache_hours", 24)
        )
        self.session: Optional[aiohttp.ClientSession] = None
        self._session_initialized = False
        # 設定ファイルの最終更新時刻を記録（ホットリロード用）
        self._config_last_modified = self._get_config_mtime()
    
    def _get_config_mtime(self) -> float:
        """設定ファイルの最終更新時刻を取得"""
        try:
            config_path = Path("data/tts_config.json")
            if config_path.exists():
                return config_path.stat().st_mtime
        except Exception:
            pass
        return 0.0
    
    def reload_config_if_changed(self):
        """設定ファイルが変更されていたら再読み込み"""
        try:
            current_mtime = self._get_config_mtime()
            if current_mtime > self._config_last_modified:
                logger.info("TTS config file changed, reloading...")
                old_config = self.tts_config.copy()
                self.tts_config = self.load_tts_config()
                self._config_last_modified = current_mtime
                
                # 重要な設定変更をログ出力
                old_greeting = old_config.get("greeting", {}).get("enabled", False)
                new_greeting = self.tts_config.get("greeting", {}).get("enabled", False)
                if old_greeting != new_greeting:
                    logger.info(f"TTS greeting setting changed: {old_greeting} → {new_greeting}")
                
                logger.info("TTS config reloaded successfully")
        except Exception as e:
            logger.error(f"Failed to reload TTS config: {e}")
        
    def load_tts_config(self) -> Dict[str, Any]:
        """TTS設定をdata/tts_config.jsonから読み込み"""
        config_path = Path("data/tts_config.json")
        default_config = {
            "api_url": "http://192.168.0.99:5000",
            "timeout": 30,
            "cache_size": 20,
            "cache_hours": 24,
            "max_text_length": 100,
            "model_id": 5,
            "speaker_id": 0,
            "style": "01",
            "greeting": {
                "enabled": True,
                "skip_on_startup": True,
                "join_message": "さん、こんちゃ！",
                "leave_message": "さん、またね！"
            }
        }
        
        try:
            if config_path.exists():
                logger.info(f"Loading TTS config from: {config_path}")
                with open(config_path, "r", encoding="utf-8") as f:
                    loaded_config = json.load(f)
                logger.info(f"Loaded TTS config: {loaded_config}")
                return loaded_config
            else:
                # デフォルト設定でファイルを作成
                logger.info(f"TTS config not found, creating default: {config_path}")
                config_path.parent.mkdir(parents=True, exist_ok=True)
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(default_config, f, indent=2, ensure_ascii=False)
                logger.info(f"Created default TTS config: {config_path}")
                return default_config
        except Exception as e:
            logger.error(f"Failed to load TTS config: {e}, using defaults")
            return default_config

    def save_tts_config(self):
        """TTS設定をdata/tts_config.jsonに保存"""
        config_path = Path("data/tts_config.json")
        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(self.tts_config, f, indent=2, ensure_ascii=False)
            logger.info(f"Saved TTS config: {config_path}")
        except Exception as e:
            logger.error(f"Failed to save TTS config: {e}")

        # 利用可能なモデル情報（キャッシュ）
        self.available_models: Optional[Dict[str, Any]] = None
        self.models_cache_time: Optional[datetime] = None
    
    def reload_config(self):
        """設定を再読み込み（data/tts_config.jsonから）"""
        try:
            # TTS設定をファイルから再読み込み
            self.tts_config = self.load_tts_config()
            self.api_url = self.tts_config.get("api_url", "http://192.168.0.99:5000")
            self.timeout = self.tts_config.get("timeout", 60)
            logger.info("TTSManager: Configuration reloaded")
        except Exception as e:
            logger.error(f"Failed to reload TTS config: {e}")
            
    def reload_config_old(self):
        """設定を再読み込み（旧config.yaml用）"""
        try:
            import yaml
            from pathlib import Path
            
            config_file = Path("config.yaml")
            if config_file.exists():
                with open(config_file, "r", encoding="utf-8") as f:
                    new_config = yaml.safe_load(f)
                
                # 設定を更新
                self.config.update(new_config)
                # 旧config.yamlからの読み込み（廃止予定）
                self.api_url = self.config.get("tts", {}).get("api_url", "http://192.168.0.99:5000")
                self.timeout = self.config.get("tts", {}).get("timeout", 60)
                
                logger.info("TTSManager: Configuration reloaded")
            else:
                logger.warning("TTSManager: config.yaml not found for reload")
                
        except Exception as e:
            logger.error(f"TTSManager: Failed to reload config: {e}")
    
    async def __aenter__(self):
        """非同期コンテキストマネージャーの開始"""
        await self.init_session()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """非同期コンテキストマネージャーの終了"""
        await self.close_session()
    
    async def init_session(self):
        """HTTP セッションを初期化"""
        if self.session is None and not self._session_initialized:
            try:
                # 高速化：コネクション数増加、Keep-Alive有効
                connection_pool_size = self.tts_config.get("connection_pool_size", 30)
                connection_pool_per_host = self.tts_config.get("connection_pool_per_host", 15)
                keepalive_timeout = self.tts_config.get("keepalive_timeout", 120)
                
                connector = aiohttp.TCPConnector(
                    limit=connection_pool_size,           # 最大コネクション数（設定可能）
                    limit_per_host=connection_pool_per_host,  # ホスト別制限（設定可能）
                    keepalive_timeout=keepalive_timeout,  # Keep-Alive有効（設定可能）
                    enable_cleanup_closed=True,  # 閉じたコネクションの自動クリーンアップ
                    force_close=False,  # 接続の再利用を促進
                    ttl_dns_cache=300,  # DNSキャッシュ（5分）
                    use_dns_cache=True  # DNSキャッシュを有効化
                )
                # TTSリクエスト用のタイムアウト設定（高速化）
                timeout = aiohttp.ClientTimeout(
                    total=self.timeout,
                    connect=3,   # 接続タイムアウト短縮（10→3秒）
                    sock_read=self.timeout  # 読み取りタイムアウト
                )
                self.session = aiohttp.ClientSession(
                    connector=connector,
                    timeout=timeout
                )
                self._session_initialized = True
                logger.debug("HTTP session initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize HTTP session: {e}")
                self._session_initialized = False
    
    async def close_session(self):
        """HTTP セッションを閉じる"""
        if self.session:
            try:
                await self.session.close()
                logger.debug("HTTP session closed successfully")
            except Exception as e:
                logger.warning(f"Error closing HTTP session: {e}")
            finally:
                self.session = None
                self._session_initialized = False
    
    async def is_api_available(self) -> bool:
        """TTSAPIサーバーが利用可能かチェック（高速化）"""
        try:
            # 高速なヘルスチェック用の短いタイムアウト
            connector = aiohttp.TCPConnector(limit=1)
            timeout = aiohttp.ClientTimeout(total=5, connect=2)  # さらに短縮（10→5秒、5→2秒）
            
            async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                async with session.get(f"{self.api_url}/status") as response:
                    return response.status == 200
        except Exception as e:
            logger.debug(f"TTS API not available: {e}")
            return False
    
    async def generate_speech(
        self, 
        text: str, 
        model_id: int = 0,
        speaker_id: int = 0,
        style: str = "Neutral"
    ) -> Optional[bytes]:
        """テキストから音声を生成"""
        if len(text.strip()) == 0:
            return None
        
        # 文字数制限
        max_length = self.tts_config.get("max_text_length", 100)
        if len(text) > max_length:
            text = text[:max_length] + "..."
            logger.warning(f"Text truncated to {max_length} characters")
        
        # キャッシュから取得を試行
        cached_audio = await self.cache.get(text, str(model_id))
        if cached_audio:
            return cached_audio
        
        # APIサーバーが利用できない場合はスキップ
        if not await self.is_api_available():
            logger.warning(f"TTS API not available at {self.api_url}, skipping audio")
            return None
        
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
            
            # asyncio.wait_forでタイムアウト制御を強化
            async def make_request():
                async with self.session.get(
                    f"{self.api_url}/voice",
                    params=params
                ) as response:
                    if response.status == 200:
                        audio_data = await response.read()
                        return audio_data
                    else:
                        error_text = await response.text()
                        logger.error(f"TTS API error: {response.status} - {error_text}")
                        return None
            
            # タイムアウト付きでリクエスト実行
            audio_data = await asyncio.wait_for(make_request(), timeout=self.timeout)
            
            if audio_data:
                # キャッシュに保存
                await self.cache.set(text, str(model_id), audio_data)
                logger.debug(f"Generated speech: {text[:30]}...")
                return audio_data
            else:
                logger.warning("TTS API returned error, skipping audio")
                return None
                    
        except asyncio.TimeoutError:
            logger.warning(f"TTS API timeout after {self.timeout}s, skipping audio")
            return None
        except Exception as e:
            logger.warning(f"TTS API error: {e}, skipping audio")
            return None
    
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
    
    async def get_available_models(self, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
        """利用可能なモデル一覧を取得"""
        # キャッシュの有効期限チェック（5分）
        if (not force_refresh and 
            self.available_models is not None and 
            self.models_cache_time is not None and
            datetime.now() - self.models_cache_time < timedelta(minutes=5)):
            return self.available_models
        
        try:
            await self.init_session()
            
            # Style-Bert-VITS2のモデル一覧API（/models/refresh POST）
            async with self.session.post(f"{self.api_url}/models/refresh") as response:
                if response.status == 200:
                    models_data = await response.json()
                    self.available_models = models_data
                    self.models_cache_time = datetime.now()
                    logger.info(f"Retrieved {len(models_data)} available models")
                    return models_data
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to get models: {response.status} - {error_text}")
                    
                    # フォールバック: GETでも試行
                    try:
                        async with self.session.get(f"{self.api_url}/models") as fallback_response:
                            if fallback_response.status == 200:
                                models_data = await fallback_response.json()
                                self.available_models = models_data
                                self.models_cache_time = datetime.now()
                                logger.info(f"Retrieved {len(models_data)} available models (fallback)")
                                return models_data
                    except Exception as fallback_error:
                        logger.error(f"Fallback GET /models also failed: {fallback_error}")
                    
                    return None
                    
        except Exception as e:
            logger.error(f"Failed to get available models: {e}")
            return None
    
    async def get_model_speakers(self, model_id: int) -> Optional[Dict[str, Any]]:
        """指定モデルの話者一覧を取得"""
        try:
            await self.init_session()
            
            # Style-Bert-VITS2の話者一覧API
            async with self.session.get(f"{self.api_url}/models/{model_id}/speakers") as response:
                if response.status == 200:
                    speakers_data = await response.json()
                    logger.debug(f"Retrieved speakers for model {model_id}")
                    return speakers_data
                else:
                    logger.error(f"Failed to get speakers for model {model_id}: {response.status}")
                    return None
                    
        except Exception as e:
            logger.error(f"Failed to get speakers for model {model_id}: {e}")
            return None
    
    def format_models_for_display(self, models: Dict[str, Any]) -> str:
        """モデル一覧を表示用にフォーマット"""
        if not models:
            return "利用可能なモデルがありません"
        
        lines = ["🎤 **利用可能なモデル一覧**\n"]
        
        for model_id, model_info in models.items():
            # id2spkから話者名を取得
            speaker_names = list(model_info.get("id2spk", {}).values())
            speaker_name = speaker_names[0] if speaker_names else f"Model {model_id}"
            
            # style2idからスタイル数を取得
            style_count = len(model_info.get("style2id", {}))
            
            lines.append(f"**{model_id}**: {speaker_name} ({style_count}スタイル)")
        
        return "\n".join(lines)
    
    def format_speakers_for_display(self, model_id: int, model_info: Dict[str, Any]) -> str:
        """話者一覧を表示用にフォーマット"""
        if not model_info:
            return f"モデル {model_id} の情報が取得できません"
        
        # id2spkから話者名を取得
        speaker_names = list(model_info.get("id2spk", {}).values())
        speaker_name = speaker_names[0] if speaker_names else f"Model {model_id}"
        
        # style2idから利用可能スタイルを取得
        styles = list(model_info.get("style2id", {}).keys())
        
        lines = [f"🗣️ **モデル {model_id}: {speaker_name}**\n"]
        lines.append("**話者ID**: 0 (固定)")
        lines.append(f"**利用可能スタイル**: {', '.join(styles) if styles else 'Neutral'}")
        
        return "\n".join(lines)
    
    async def cleanup(self):
        """リソースのクリーンアップ"""
        await self.close_session()