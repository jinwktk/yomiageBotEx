"""
辞書機能Cog
- 単語の登録・削除・検索
- 辞書のインポート・エクスポート
"""

import asyncio
import logging
import random
from typing import Dict, Any

import discord
from discord.ext import commands
from discord import app_commands

from utils.dictionary import DictionaryManager


class DictionaryCog(commands.Cog):
    """辞書機能を提供するCog"""
    
    def __init__(self, bot: commands.Bot, config: Dict[str, Any]):
        self.bot = bot
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.dictionary_manager = DictionaryManager(config)
        
        # 初期化時の設定値をログ出力
        self.logger.info(f"Dictionary: Initialized dictionary manager")
    
    async def rate_limit_delay(self):
        """レート制限対策の遅延"""
        delay = random.uniform(*self.config["bot"]["rate_limit_delay"])
        await asyncio.sleep(delay)
    
    @app_commands.command(name="dict_add", description="辞書に単語を追加します")
    @app_commands.describe(
        word="登録する単語",
        reading="読み方（ひらがな・カタカナ）",
        scope="辞書の範囲"
    )
    @app_commands.choices(scope=[
        app_commands.Choice(name="ギルド", value="ギルド"),
        app_commands.Choice(name="グローバル", value="グローバル")
    ])
    async def dict_add_command(
        self, 
        interaction: discord.Interaction,
        word: str,
        reading: str,
        scope: str = "ギルド"
    ):
        """単語を辞書に追加"""
        await self.rate_limit_delay()
        
        # 権限チェック（グローバル辞書は特定ユーザーのみ）
        admin_user_id = self.config.get("bot", {}).get("admin_user_id", 372768430149074954)
        if scope == "グローバル" and interaction.user.id != admin_user_id:
            await interaction.response.send_message(
                "❌ グローバル辞書への追加は管理者のみ実行できます。",
                ephemeral=True
            )
            return
        
        try:
            guild_id = interaction.guild.id if scope == "ギルド" else None
            
            if self.dictionary_manager.add_word(guild_id, word, reading):
                scope_text = "ギルド辞書" if scope == "ギルド" else "グローバル辞書"
                await interaction.response.send_message(
                    f"✅ {scope_text}に追加しました：**{word}** → **{reading}**",
                    ephemeral=True
                )
                self.logger.info(f"Dictionary: Added word '{word}' -> '{reading}' to {scope} by {interaction.user}")
            else:
                await interaction.response.send_message(
                    "❌ 単語の追加に失敗しました。",
                    ephemeral=True
                )
        except Exception as e:
            self.logger.error(f"Failed to add dictionary word: {e}")
            await interaction.response.send_message(
                "❌ 単語の追加中にエラーが発生しました。",
                ephemeral=True
            )
    
    @app_commands.command(name="dict_remove", description="辞書から単語を削除します")
    @app_commands.describe(
        word="削除する単語",
        scope="辞書の範囲"
    )
    @app_commands.choices(scope=[
        app_commands.Choice(name="ギルド", value="ギルド"),
        app_commands.Choice(name="グローバル", value="グローバル")
    ])
    async def dict_remove_command(
        self, 
        interaction: discord.Interaction,
        word: str,
        scope: str = "ギルド"
    ):
        """単語を辞書から削除"""
        await self.rate_limit_delay()
        
        # 権限チェック（グローバル辞書は特定ユーザーのみ）
        admin_user_id = self.config.get("bot", {}).get("admin_user_id", 372768430149074954)
        if scope == "グローバル" and interaction.user.id != admin_user_id:
            await interaction.response.send_message(
                "❌ グローバル辞書からの削除は管理者のみ実行できます。",
                ephemeral=True
            )
            return
        
        try:
            guild_id = interaction.guild.id if scope == "ギルド" else None
            
            if self.dictionary_manager.remove_word(guild_id, word):
                scope_text = "ギルド辞書" if scope == "ギルド" else "グローバル辞書"
                await interaction.response.send_message(
                    f"✅ {scope_text}から削除しました：**{word}**",
                    ephemeral=True
                )
                self.logger.info(f"Dictionary: Removed word '{word}' from {scope} by {interaction.user}")
            else:
                await interaction.response.send_message(
                    f"❌ 単語 **{word}** が見つかりませんでした。",
                    ephemeral=True
                )
        except Exception as e:
            self.logger.error(f"Failed to remove dictionary word: {e}")
            await interaction.response.send_message(
                "❌ 単語の削除中にエラーが発生しました。",
                ephemeral=True
            )
    
    


async def setup(bot):
    """Cogのセットアップ"""
    await bot.add_cog(DictionaryCog(bot, bot.config))