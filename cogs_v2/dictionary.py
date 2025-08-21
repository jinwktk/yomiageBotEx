"""
DictionaryCog v2 - シンプルな辞書機能
- 単語置換機能
- 辞書管理コマンド
"""

import json
import logging
from pathlib import Path
from typing import Dict

import discord
from discord.ext import commands

logger = logging.getLogger(__name__)

class DictionaryCogV2(commands.Cog):
    """辞書機能Cog"""
    
    def __init__(self, bot):
        self.bot = bot
        self.config = bot.config.get('dictionary', {})
        
        # 辞書機能が有効かチェック
        self.enabled = self.config.get('enabled', True)
        
        # 辞書データ
        self.dictionary: Dict[str, str] = {}  # 単語: 読み方
        
        # 辞書ファイルパス
        self.dict_file = Path("dictionary_v2.json")
        
        # 辞書読み込み
        if self.enabled:
            self.load_dictionary()
        
        logger.info(f"DictionaryCog v2 initialized - Enabled: {self.enabled}, Words: {len(self.dictionary)}")
    
    def load_dictionary(self):
        """辞書ファイル読み込み"""
        try:
            if self.dict_file.exists():
                with open(self.dict_file, 'r', encoding='utf-8') as f:
                    self.dictionary = json.load(f)
                logger.info(f"Loaded {len(self.dictionary)} words from dictionary")
            else:
                self.dictionary = {}
                logger.info("Dictionary file not found, starting with empty dictionary")
        except Exception as e:
            logger.error(f"Failed to load dictionary: {e}", exc_info=True)
            self.dictionary = {}
    
    def save_dictionary(self):
        """辞書ファイル保存"""
        try:
            with open(self.dict_file, 'w', encoding='utf-8') as f:
                json.dump(self.dictionary, f, ensure_ascii=False, indent=2)
            logger.debug(f"Saved {len(self.dictionary)} words to dictionary")
        except Exception as e:
            logger.error(f"Failed to save dictionary: {e}", exc_info=True)
    
    @discord.slash_command(name="dict_add", description="辞書に単語を追加")
    async def dict_add_command(self, ctx: discord.ApplicationContext,
                              word: discord.Option(str, "単語", required=True),
                              reading: discord.Option(str, "読み方", required=True)):
        """辞書追加コマンド"""
        await ctx.defer(ephemeral=True)
        
        try:
            if not self.enabled:
                await ctx.followup.send("❌ 辞書機能が無効になっています", ephemeral=True)
                return
            
            # 最大単語数チェック
            max_words = self.config.get('max_words', 1000)
            if len(self.dictionary) >= max_words:
                await ctx.followup.send(f"❌ 辞書の最大単語数（{max_words}）に達しています", ephemeral=True)
                return
            
            # 単語追加
            self.dictionary[word] = reading
            self.save_dictionary()
            
            await ctx.followup.send(f"✅ 辞書に追加しました: {word} → {reading}", ephemeral=True)
            logger.info(f"Dictionary added: {word} → {reading}")
            
        except Exception as e:
            logger.error(f"Dict add command error: {e}", exc_info=True)
            await ctx.followup.send("❌ エラーが発生しました", ephemeral=True)
    
    @discord.slash_command(name="dict_remove", description="辞書から単語を削除")
    async def dict_remove_command(self, ctx: discord.ApplicationContext,
                                 word: discord.Option(str, "削除する単語", required=True)):
        """辞書削除コマンド"""
        await ctx.defer(ephemeral=True)
        
        try:
            if not self.enabled:
                await ctx.followup.send("❌ 辞書機能が無効になっています", ephemeral=True)
                return
            
            if word not in self.dictionary:
                await ctx.followup.send(f"❌ 単語「{word}」は辞書に登録されていません", ephemeral=True)
                return
            
            # 単語削除
            reading = self.dictionary.pop(word)
            self.save_dictionary()
            
            await ctx.followup.send(f"✅ 辞書から削除しました: {word} → {reading}", ephemeral=True)
            logger.info(f"Dictionary removed: {word} → {reading}")
            
        except Exception as e:
            logger.error(f"Dict remove command error: {e}", exc_info=True)
            await ctx.followup.send("❌ エラーが発生しました", ephemeral=True)
    
    def apply_dictionary(self, text: str) -> str:
        """テキストに辞書を適用"""
        if not self.enabled or not self.dictionary:
            return text
        
        try:
            # 辞書の各単語について置換
            for word, reading in self.dictionary.items():
                text = text.replace(word, reading)
            
            return text
            
        except Exception as e:
            logger.error(f"Dictionary apply error: {e}", exc_info=True)
            return text

def setup(bot):
    bot.add_cog(DictionaryCogV2(bot))