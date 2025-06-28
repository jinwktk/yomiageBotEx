"""
辞書登録機能
読み上げ用の単語・読み方の辞書管理
"""

import json
import logging
import re
import asyncio
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class DictionaryManager:
    """辞書管理クラス（軽量化重視）"""
    
    def __init__(self, config: dict):
        self.config = config
        self.dict_file = Path("data/dictionary.json")
        self.dict_file.parent.mkdir(parents=True, exist_ok=True)
        
        # ギルドごとの辞書
        self.guild_dictionaries: Dict[int, Dict[str, str]] = {}
        
        # グローバル辞書
        self.global_dictionary: Dict[str, str] = {}
        
        # 辞書の読み込み
        self._load_dictionaries()
        
    def _load_dictionaries(self):
        """辞書ファイルを読み込み"""
        try:
            if self.dict_file.exists():
                with open(self.dict_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.global_dictionary = data.get("global", {})
                    
                    # ギルド辞書をint型のキーに変換
                    guild_dicts = data.get("guilds", {})
                    self.guild_dictionaries = {
                        int(guild_id): words for guild_id, words in guild_dicts.items()
                    }
                    
                logger.info(f"Loaded {len(self.global_dictionary)} global words and {len(self.guild_dictionaries)} guild dictionaries")
            else:
                # デフォルト辞書を作成
                self._create_default_dictionary()
                
        except Exception as e:
            logger.error(f"Failed to load dictionaries: {e}")
            self._create_default_dictionary()
    
    def _create_default_dictionary(self):
        """デフォルト辞書を作成"""
        self.global_dictionary = {
            "w": "ダブリュー",
            "www": "わらわら",
            "草": "くさ",
            "Bot": "ボット",
            "bot": "ボット",
            "API": "エーピーアイ",
            "URL": "ユーアールエル",
            "HTTP": "エイチティーティーピー",
            "HTTPS": "エイチティーティーピーエス",
            "Discord": "ディスコード",
            "Python": "パイソン",
            "JavaScript": "ジャバスクリプト",
            "TypeScript": "タイプスクリプト",
            "GitHub": "ギットハブ",
            "AI": "エーアイ",
            "TTS": "ティーティーエス",
            "VC": "ボイスチャンネル",
            "DM": "ダイレクトメッセージ"
        }
        self.guild_dictionaries = {}
        self._save_dictionaries()
    
    def _save_dictionaries(self):
        """辞書ファイルを保存"""
        try:
            # ギルドIDを文字列型に変換して保存
            guild_dicts = {
                str(guild_id): words for guild_id, words in self.guild_dictionaries.items()
            }
            
            data = {
                "global": self.global_dictionary,
                "guilds": guild_dicts
            }
            
            with open(self.dict_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                
            logger.debug("Dictionaries saved successfully")
            
        except Exception as e:
            logger.error(f"Failed to save dictionaries: {e}")
    
    def get_guild_dictionary(self, guild_id: int) -> Dict[str, str]:
        """ギルド辞書を取得"""
        if guild_id not in self.guild_dictionaries:
            self.guild_dictionaries[guild_id] = {}
        return self.guild_dictionaries[guild_id]
    
    def add_word(self, guild_id: Optional[int], word: str, reading: str) -> bool:
        """単語を辞書に追加"""
        try:
            word = word.strip()
            reading = reading.strip()
            
            if not word or not reading:
                return False
            
            if guild_id is None:
                # グローバル辞書に追加
                self.global_dictionary[word] = reading
                logger.info(f"Added global word: {word} -> {reading}")
            else:
                # ギルド辞書に追加
                guild_dict = self.get_guild_dictionary(guild_id)
                guild_dict[word] = reading
                logger.info(f"Added guild word for {guild_id}: {word} -> {reading}")
            
            self._save_dictionaries()
            return True
            
        except Exception as e:
            logger.error(f"Failed to add word: {e}")
            return False
    
    def remove_word(self, guild_id: Optional[int], word: str) -> bool:
        """単語を辞書から削除"""
        try:
            word = word.strip()
            
            if guild_id is None:
                # グローバル辞書から削除
                if word in self.global_dictionary:
                    del self.global_dictionary[word]
                    logger.info(f"Removed global word: {word}")
                    self._save_dictionaries()
                    return True
            else:
                # ギルド辞書から削除
                guild_dict = self.get_guild_dictionary(guild_id)
                if word in guild_dict:
                    del guild_dict[word]
                    logger.info(f"Removed guild word for {guild_id}: {word}")
                    self._save_dictionaries()
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to remove word: {e}")
            return False
    
    def search_words(self, guild_id: Optional[int], query: str) -> List[Tuple[str, str, str]]:
        """単語を検索"""
        results = []
        query = query.lower()
        
        try:
            # グローバル辞書を検索
            for word, reading in self.global_dictionary.items():
                if query in word.lower() or query in reading.lower():
                    results.append((word, reading, "グローバル"))
            
            # ギルド辞書を検索
            if guild_id is not None:
                guild_dict = self.get_guild_dictionary(guild_id)
                for word, reading in guild_dict.items():
                    if query in word.lower() or query in reading.lower():
                        results.append((word, reading, "ギルド"))
            
            # 結果をソート（完全一致優先、その後単語の長さ順）
            def sort_key(item):
                word, reading, scope = item
                exact_match = word.lower() == query or reading.lower() == query
                return (not exact_match, len(word))
            
            results.sort(key=sort_key)
            return results[:20]  # 最大20件
            
        except Exception as e:
            logger.error(f"Failed to search words: {e}")
            return []
    
    def apply_dictionary(self, text: str, guild_id: Optional[int]) -> str:
        """テキストに辞書を適用"""
        try:
            if not text:
                return text
            
            result = text
            
            # ギルド辞書を優先して適用
            if guild_id is not None:
                guild_dict = self.get_guild_dictionary(guild_id)
                for word, reading in guild_dict.items():
                    # 単語境界を考慮した置換（より正確な置換）
                    pattern = re.compile(re.escape(word), re.IGNORECASE)
                    result = pattern.sub(reading, result)
            
            # グローバル辞書を適用
            for word, reading in self.global_dictionary.items():
                pattern = re.compile(re.escape(word), re.IGNORECASE)
                result = pattern.sub(reading, result)
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to apply dictionary: {e}")
            return text
    
    def get_word_count(self, guild_id: Optional[int]) -> Tuple[int, int]:
        """辞書の単語数を取得"""
        try:
            global_count = len(self.global_dictionary)
            guild_count = 0
            
            if guild_id is not None:
                guild_dict = self.get_guild_dictionary(guild_id)
                guild_count = len(guild_dict)
            
            return global_count, guild_count
            
        except Exception as e:
            logger.error(f"Failed to get word count: {e}")
            return 0, 0
    
    def export_dictionary(self, guild_id: Optional[int]) -> str:
        """辞書をテキスト形式でエクスポート"""
        try:
            lines = []
            
            # グローバル辞書
            if self.global_dictionary:
                lines.append("# グローバル辞書")
                for word, reading in sorted(self.global_dictionary.items()):
                    lines.append(f"{word}\t{reading}")
                lines.append("")
            
            # ギルド辞書
            if guild_id is not None:
                guild_dict = self.get_guild_dictionary(guild_id)
                if guild_dict:
                    lines.append(f"# ギルド辞書 (ID: {guild_id})")
                    for word, reading in sorted(guild_dict.items()):
                        lines.append(f"{word}\t{reading}")
            
            return "\n".join(lines)
            
        except Exception as e:
            logger.error(f"Failed to export dictionary: {e}")
            return "辞書のエクスポートに失敗しました"
    
    def import_dictionary(self, guild_id: Optional[int], text: str) -> Tuple[int, int]:
        """テキストから辞書をインポート"""
        try:
            lines = text.strip().split('\n')
            added_count = 0
            error_count = 0
            
            for line in lines:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                
                # タブ区切りまたはスペース区切りで分割
                parts = re.split(r'\t+|\s{2,}', line, 1)
                if len(parts) != 2:
                    error_count += 1
                    continue
                
                word, reading = parts
                if self.add_word(guild_id, word, reading):
                    added_count += 1
                else:
                    error_count += 1
            
            return added_count, error_count
            
        except Exception as e:
            logger.error(f"Failed to import dictionary: {e}")
            return 0, 1