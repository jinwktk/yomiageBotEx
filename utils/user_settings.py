"""
ユーザー別設定管理
読み上げ設定、音声設定等のユーザー固有設定
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class UserSettingsManager:
    """ユーザー別設定管理クラス（軽量化重視）"""
    
    def __init__(self, config: dict):
        self.config = config
        self.settings_file = Path("data/user_settings.json")
        self.settings_file.parent.mkdir(parents=True, exist_ok=True)
        
        # ユーザー設定（user_id -> settings）
        self.user_settings: Dict[int, Dict[str, Any]] = {}
        
        # デフォルト設定
        self.default_settings = {
            "reading": {
                "enabled": True,
                "max_length": 100,
                "ignore_mentions": False,
                "ignore_links": True
            }
        }
        
        # 設定の読み込み
        self._load_settings()
        
    def _load_settings(self):
        """設定ファイルを読み込み"""
        try:
            if self.settings_file.exists():
                with open(self.settings_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    
                    # キーをint型に変換
                    self.user_settings = {
                        int(user_id): settings for user_id, settings in data.items()
                    }
                    
                logger.info(f"Loaded settings for {len(self.user_settings)} users")
            else:
                logger.info("No user settings file found, using defaults")
                
        except Exception as e:
            logger.error(f"Failed to load user settings: {e}")
            self.user_settings = {}
    
    def _save_settings(self):
        """設定ファイルを保存"""
        try:
            # キーを文字列型に変換して保存
            data = {
                str(user_id): settings for user_id, settings in self.user_settings.items()
            }
            
            with open(self.settings_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                
            logger.debug("User settings saved successfully")
            
        except Exception as e:
            logger.error(f"Failed to save user settings: {e}")
    
    def get_user_settings(self, user_id: int) -> Dict[str, Any]:
        """ユーザー設定を取得（デフォルト値でマージ）"""
        if user_id not in self.user_settings:
            self.user_settings[user_id] = {}
        
        # デフォルト設定とマージ
        user_config = self._deep_merge(self.default_settings.copy(), self.user_settings[user_id])
        return user_config
    
    def _deep_merge(self, base: dict, override: dict) -> dict:
        """辞書の深いマージ"""
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                base[key] = self._deep_merge(base[key], value)
            else:
                base[key] = value
        return base
    
    def set_user_setting(self, user_id: int, category: str, key: str, value: Any) -> bool:
        """ユーザー設定を更新"""
        try:
            if user_id not in self.user_settings:
                self.user_settings[user_id] = {}
            
            if category not in self.user_settings[user_id]:
                self.user_settings[user_id][category] = {}
            
            self.user_settings[user_id][category][key] = value
            self._save_settings()
            
            logger.info(f"Updated user {user_id} setting: {category}.{key} = {value}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to set user setting: {e}")
            return False
    
    def get_user_setting(self, user_id: int, category: str, key: str) -> Any:
        """特定のユーザー設定値を取得"""
        try:
            settings = self.get_user_settings(user_id)
            return settings.get(category, {}).get(key)
        except Exception as e:
            logger.error(f"Failed to get user setting: {e}")
            return None
    
    def reset_user_settings(self, user_id: int, category: Optional[str] = None) -> bool:
        """ユーザー設定をリセット"""
        try:
            if user_id not in self.user_settings:
                return True
            
            if category:
                # 特定カテゴリのみリセット
                if category in self.user_settings[user_id]:
                    del self.user_settings[user_id][category]
                    logger.info(f"Reset user {user_id} settings for category: {category}")
            else:
                # 全設定をリセット
                del self.user_settings[user_id]
                logger.info(f"Reset all settings for user {user_id}")
            
            self._save_settings()
            return True
            
        except Exception as e:
            logger.error(f"Failed to reset user settings: {e}")
            return False
    
    
    def get_reading_settings(self, user_id: int) -> Dict[str, Any]:
        """読み上げ設定を取得"""
        settings = self.get_user_settings(user_id)
        return settings.get("reading", {})
    
    
    def is_reading_enabled(self, user_id: int) -> bool:
        """ユーザーの読み上げが有効かチェック"""
        reading_settings = self.get_reading_settings(user_id)
        return reading_settings.get("enabled", True)
    
    def get_user_count(self) -> int:
        """設定を持つユーザー数を取得"""
        return len(self.user_settings)
    
    def export_user_settings(self, user_id: int) -> str:
        """ユーザー設定をテキスト形式でエクスポート"""
        try:
            settings = self.get_user_settings(user_id)
            
            lines = [f"# ユーザー設定 (ID: {user_id})", ""]
            
            for category, category_settings in settings.items():
                lines.append(f"## {category}")
                for key, value in category_settings.items():
                    lines.append(f"{key}: {value}")
                lines.append("")
            
            return "\n".join(lines)
            
        except Exception as e:
            logger.error(f"Failed to export user settings: {e}")
            return "設定のエクスポートに失敗しました"
    
    def get_settings_summary(self, user_id: int) -> str:
        """ユーザー設定の要約を取得"""
        try:
            settings = self.get_user_settings(user_id)
            
            reading = settings.get("reading", {})
            
            # グローバルTTS設定を取得
            tts_config = self.config.get("message_reading", {})
            greeting_config = self.config.get("tts", {}).get("greeting", {})
            
            lines = [
                f"📢 **読み上げ設定（個人）**",
                f"有効: {'✅' if reading.get('enabled', True) else '❌'} | 最大文字数: {reading.get('max_length', 100)}",
                f"メンション無視: {'✅' if reading.get('ignore_mentions', False) else '❌'} | リンク無視: {'✅' if reading.get('ignore_links', True) else '❌'}",
                "",
                f"🎤 **TTS設定（サーバー共通）**",
                f"モデルID: {tts_config.get('model_id', 5)} | 話者ID: {tts_config.get('speaker_id', 0)}",
                f"スタイル: {tts_config.get('style', '01')}",
                "",
                f"👋 **挨拶設定（サーバー共通）**",
                f"モデルID: {greeting_config.get('model_id', 5)} | 話者ID: {greeting_config.get('speaker_id', 0)}",
                f"スタイル: {greeting_config.get('style', '01')}"
            ]
            
            return "\n".join(lines)
            
        except Exception as e:
            logger.error(f"Failed to get settings summary: {e}")
            return "設定の取得に失敗しました"