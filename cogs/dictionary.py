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
    
    @discord.slash_command(name="dict_add", description="辞書に単語を追加します")
    async def dict_add_command(
        self, 
        ctx: discord.ApplicationContext,
        word: discord.Option(str, "登録する単語", max_length=50),
        reading: discord.Option(str, "読み方（ひらがな・カタカナ）", max_length=100),
        scope: discord.Option(str, "辞書の範囲", choices=["ギルド", "グローバル"], default="ギルド")
    ):
        """単語を辞書に追加"""
        await self.rate_limit_delay()
        
        # 権限チェック（グローバル辞書は管理者のみ）
        if scope == "グローバル" and not ctx.user.guild_permissions.administrator:
            await ctx.respond(
                "❌ グローバル辞書への追加は管理者のみ実行できます。",
                ephemeral=True
            )
            return
        
        try:
            guild_id = ctx.guild.id if scope == "ギルド" else None
            
            if self.dictionary_manager.add_word(guild_id, word, reading):
                scope_text = "ギルド辞書" if scope == "ギルド" else "グローバル辞書"
                await ctx.respond(
                    f"✅ {scope_text}に追加しました：**{word}** → **{reading}**",
                    ephemeral=True
                )
                self.logger.info(f"Dictionary: Added word '{word}' -> '{reading}' to {scope} by {ctx.user}")
            else:
                await ctx.respond(
                    "❌ 単語の追加に失敗しました。",
                    ephemeral=True
                )
        except Exception as e:
            self.logger.error(f"Failed to add dictionary word: {e}")
            await ctx.respond(
                "❌ 単語の追加中にエラーが発生しました。",
                ephemeral=True
            )
    
    @discord.slash_command(name="dict_remove", description="辞書から単語を削除します")
    async def dict_remove_command(
        self, 
        ctx: discord.ApplicationContext,
        word: discord.Option(str, "削除する単語", max_length=50),
        scope: discord.Option(str, "辞書の範囲", choices=["ギルド", "グローバル"], default="ギルド")
    ):
        """単語を辞書から削除"""
        await self.rate_limit_delay()
        
        # 権限チェック（グローバル辞書は管理者のみ）
        if scope == "グローバル" and not ctx.user.guild_permissions.administrator:
            await ctx.respond(
                "❌ グローバル辞書からの削除は管理者のみ実行できます。",
                ephemeral=True
            )
            return
        
        try:
            guild_id = ctx.guild.id if scope == "ギルド" else None
            
            if self.dictionary_manager.remove_word(guild_id, word):
                scope_text = "ギルド辞書" if scope == "ギルド" else "グローバル辞書"
                await ctx.respond(
                    f"✅ {scope_text}から削除しました：**{word}**",
                    ephemeral=True
                )
                self.logger.info(f"Dictionary: Removed word '{word}' from {scope} by {ctx.user}")
            else:
                await ctx.respond(
                    f"❌ 単語 **{word}** が見つかりませんでした。",
                    ephemeral=True
                )
        except Exception as e:
            self.logger.error(f"Failed to remove dictionary word: {e}")
            await ctx.respond(
                "❌ 単語の削除中にエラーが発生しました。",
                ephemeral=True
            )
    
    @discord.slash_command(name="dict_search", description="辞書で単語を検索します")
    async def dict_search_command(
        self, 
        ctx: discord.ApplicationContext,
        query: discord.Option(str, "検索キーワード", max_length=50)
    ):
        """辞書で単語を検索"""
        await self.rate_limit_delay()
        
        try:
            results = self.dictionary_manager.search_words(ctx.guild.id, query)
            
            if not results:
                await ctx.respond(
                    f"❌ **{query}** に一致する単語が見つかりませんでした。",
                    ephemeral=True
                )
                return
            
            # 検索結果をEmbedで表示
            embed = discord.Embed(
                title=f"🔍 辞書検索結果: {query}",
                color=discord.Color.blue()
            )
            
            for i, (word, reading, scope) in enumerate(results[:10], 1):  # 最大10件
                embed.add_field(
                    name=f"{i}. {word} ({scope})",
                    value=f"読み: **{reading}**",
                    inline=False
                )
            
            if len(results) > 10:
                embed.set_footer(text=f"他に{len(results) - 10}件の結果があります")
            
            await ctx.respond(embed=embed, ephemeral=True)
            
        except Exception as e:
            self.logger.error(f"Failed to search dictionary: {e}")
            await ctx.respond(
                "❌ 検索中にエラーが発生しました。",
                ephemeral=True
            )
    
    @discord.slash_command(name="dict_list", description="辞書の統計情報を表示します")
    async def dict_list_command(self, ctx: discord.ApplicationContext):
        """辞書の統計情報を表示"""
        await self.rate_limit_delay()
        
        try:
            global_count, guild_count = self.dictionary_manager.get_word_count(ctx.guild.id)
            
            embed = discord.Embed(
                title="📚 辞書統計",
                color=discord.Color.green()
            )
            
            embed.add_field(
                name="グローバル辞書",
                value=f"**{global_count}** 件",
                inline=True
            )
            
            embed.add_field(
                name="ギルド辞書",
                value=f"**{guild_count}** 件",
                inline=True
            )
            
            embed.add_field(
                name="合計",
                value=f"**{global_count + guild_count}** 件",
                inline=True
            )
            
            embed.set_footer(text="辞書は読み上げ時に自動適用されます")
            
            await ctx.respond(embed=embed, ephemeral=True)
            
        except Exception as e:
            self.logger.error(f"Failed to get dictionary stats: {e}")
            await ctx.respond(
                "❌ 統計情報の取得中にエラーが発生しました。",
                ephemeral=True
            )
    
    @discord.slash_command(name="dict_export", description="辞書をテキストファイルでエクスポートします")
    async def dict_export_command(
        self, 
        ctx: discord.ApplicationContext,
        scope: discord.Option(str, "エクスポート範囲", choices=["ギルド", "グローバル", "全て"], default="全て")
    ):
        """辞書をエクスポート"""
        await self.rate_limit_delay()
        
        try:
            if scope == "グローバル":
                guild_id = None
            elif scope == "ギルド":
                guild_id = ctx.guild.id
            else:  # 全て
                guild_id = ctx.guild.id
            
            export_text = self.dictionary_manager.export_dictionary(guild_id)
            
            if not export_text:
                await ctx.respond(
                    "❌ エクスポートする辞書データがありません。",
                    ephemeral=True
                )
                return
            
            # テキストファイルとして送信
            import io
            from datetime import datetime
            
            file_content = export_text.encode('utf-8')
            file_buffer = io.BytesIO(file_content)
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"dictionary_{scope}_{timestamp}.txt"
            
            await ctx.respond(
                f"📤 辞書をエクスポートしました（{scope}）",
                file=discord.File(file_buffer, filename=filename),
                ephemeral=True
            )
            
            self.logger.info(f"Dictionary: Exported {scope} dictionary by {ctx.user}")
            
        except Exception as e:
            self.logger.error(f"Failed to export dictionary: {e}")
            await ctx.respond(
                "❌ エクスポート中にエラーが発生しました。",
                ephemeral=True
            )
    
    @discord.slash_command(name="dict_import", description="テキストファイルから辞書をインポートします")
    async def dict_import_command(
        self, 
        ctx: discord.ApplicationContext,
        file: discord.Option(discord.Attachment, "インポートするテキストファイル"),
        scope: discord.Option(str, "インポート先", choices=["ギルド", "グローバル"], default="ギルド")
    ):
        """辞書をインポート"""
        await self.rate_limit_delay()
        
        # 権限チェック（グローバル辞書は管理者のみ）
        if scope == "グローバル" and not ctx.user.guild_permissions.administrator:
            await ctx.respond(
                "❌ グローバル辞書へのインポートは管理者のみ実行できます。",
                ephemeral=True
            )
            return
        
        # ファイルサイズチェック（1MB以下）
        if file.size > 1024 * 1024:
            await ctx.respond(
                "❌ ファイルサイズが大きすぎます（1MB以下にしてください）。",
                ephemeral=True
            )
            return
        
        # ファイル形式チェック
        if not file.filename.endswith('.txt'):
            await ctx.respond(
                "❌ テキストファイル（.txt）をアップロードしてください。",
                ephemeral=True
            )
            return
        
        try:
            # ファイル内容を読み込み
            file_content = await file.read()
            text = file_content.decode('utf-8')
            
            guild_id = ctx.guild.id if scope == "ギルド" else None
            added_count, error_count = self.dictionary_manager.import_dictionary(guild_id, text)
            
            if added_count > 0:
                scope_text = "ギルド辞書" if scope == "ギルド" else "グローバル辞書"
                message = f"✅ {scope_text}に **{added_count}** 件の単語をインポートしました。"
                if error_count > 0:
                    message += f"\n⚠️ **{error_count}** 件のエラーがありました。"
                
                await ctx.respond(message, ephemeral=True)
                self.logger.info(f"Dictionary: Imported {added_count} words to {scope} by {ctx.user}")
            else:
                await ctx.respond(
                    "❌ インポート可能な単語が見つかりませんでした。",
                    ephemeral=True
                )
                
        except UnicodeDecodeError:
            await ctx.respond(
                "❌ ファイルの文字エンコーディングが正しくありません（UTF-8を使用してください）。",
                ephemeral=True
            )
        except Exception as e:
            self.logger.error(f"Failed to import dictionary: {e}")
            await ctx.respond(
                "❌ インポート中にエラーが発生しました。",
                ephemeral=True
            )


def setup(bot):
    """Cogのセットアップ"""
    bot.add_cog(DictionaryCog(bot, bot.config))