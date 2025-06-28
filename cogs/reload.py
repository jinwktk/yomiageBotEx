#!/usr/bin/env python3
"""
リロード機能Cog - Cogの手動リロードとホットリロード補助機能
"""

import logging
import discord
from discord.ext import commands

logger = logging.getLogger(__name__)

class ReloadCog(commands.Cog):
    """リロード機能を提供するCog"""
    
    def __init__(self, bot):
        self.bot = bot
        logger.info("ReloadCog initialized")
    
    @discord.slash_command(
        name="reload_cog",
        description="指定したCogを再読み込みします（管理者限定）",
    )
    async def reload_cog(
        self,
        ctx: discord.ApplicationContext,
        cog_name: discord.Option(
            str,
            description="再読み込みするCog名（例：voice, tts, recording）",
            required=True
        )
    ):
        """指定したCogを再読み込み"""
        await ctx.defer(ephemeral=True)
        
        # 管理者権限チェック
        if not ctx.author.guild_permissions.administrator:
            await ctx.followup.send(
                "❌ このコマンドは管理者のみ使用できます。",
                ephemeral=True
            )
            return
        
        try:
            # Cog名の正規化
            full_cog_name = f"cogs.{cog_name}" if not cog_name.startswith("cogs.") else cog_name
            
            # 既存のCogがロードされているか確認
            if full_cog_name not in [ext for ext in self.bot.extensions]:
                await ctx.followup.send(
                    f"❌ Cog `{cog_name}` は現在ロードされていません。\n"
                    f"利用可能なCog: {', '.join([ext.split('.')[-1] for ext in self.bot.extensions if ext.startswith('cogs.')])}", 
                    ephemeral=True
                )
                return
            
            # Cogを再読み込み
            logger.info(f"Reloading cog: {full_cog_name}")
            self.bot.reload_extension(full_cog_name)
            
            await ctx.followup.send(
                f"✅ Cog `{cog_name}` を正常に再読み込みしました。",
                ephemeral=True
            )
            logger.info(f"Successfully reloaded cog: {full_cog_name}")
            
        except Exception as e:
            error_msg = f"❌ Cog `{cog_name}` の再読み込みに失敗しました: {str(e)}"
            await ctx.followup.send(error_msg, ephemeral=True)
            logger.error(f"Failed to reload cog {cog_name}: {e}", exc_info=True)
    
    @discord.slash_command(
        name="reload_all",
        description="すべてのCogを再読み込みします（管理者限定）",
    )
    async def reload_all(self, ctx: discord.ApplicationContext):
        """すべてのCogを再読み込み"""
        await ctx.defer(ephemeral=True)
        
        # 管理者権限チェック
        if not ctx.author.guild_permissions.administrator:
            await ctx.followup.send(
                "❌ このコマンドは管理者のみ使用できます。",
                ephemeral=True
            )
            return
        
        try:
            # 現在ロードされているすべてのCogを取得
            cog_extensions = [ext for ext in self.bot.extensions if ext.startswith('cogs.')]
            
            if not cog_extensions:
                await ctx.followup.send(
                    "❌ 再読み込み可能なCogが見つかりません。",
                    ephemeral=True
                )
                return
            
            success_count = 0
            failed_cogs = []
            
            # 各Cogを再読み込み
            for extension in cog_extensions:
                try:
                    logger.info(f"Reloading cog: {extension}")
                    self.bot.reload_extension(extension)
                    success_count += 1
                except Exception as e:
                    failed_cogs.append(f"{extension}: {str(e)}")
                    logger.error(f"Failed to reload {extension}: {e}")
            
            # 結果を報告
            result_msg = f"✅ {success_count}/{len(cog_extensions)} のCogを正常に再読み込みしました。"
            
            if failed_cogs:
                result_msg += f"\n\n❌ 失敗したCog:\n" + "\n".join([f"- {failure}" for failure in failed_cogs])
            
            await ctx.followup.send(result_msg, ephemeral=True)
            logger.info(f"Reload all completed: {success_count} success, {len(failed_cogs)} failed")
            
        except Exception as e:
            error_msg = f"❌ Cogの一括再読み込み中にエラーが発生しました: {str(e)}"
            await ctx.followup.send(error_msg, ephemeral=True)
            logger.error(f"Failed to reload all cogs: {e}", exc_info=True)
    
    @discord.slash_command(
        name="list_cogs",
        description="現在ロードされているCogの一覧を表示します",
    )
    async def list_cogs(self, ctx: discord.ApplicationContext):
        """ロードされているCogの一覧を表示"""
        await ctx.defer(ephemeral=True)
        
        try:
            # 現在ロードされているCogを取得
            cog_extensions = [ext for ext in self.bot.extensions if ext.startswith('cogs.')]
            
            if not cog_extensions:
                await ctx.followup.send(
                    "❌ ロードされているCogが見つかりません。",
                    ephemeral=True
                )
                return
            
            # Cog一覧を作成
            cog_list = []
            for extension in sorted(cog_extensions):
                cog_name = extension.split('.')[-1]
                cog_obj = self.bot.get_cog(f"{cog_name.title()}Cog")
                
                if cog_obj:
                    command_count = len(cog_obj.get_commands())
                    cog_list.append(f"✅ **{cog_name}** ({command_count} commands)")
                else:
                    cog_list.append(f"⚠️ **{cog_name}** (Cog object not found)")
            
            embed = discord.Embed(
                title="🔧 ロード済みCog一覧",
                description="\n".join(cog_list),
                color=0x00ff00
            )
            embed.set_footer(text=f"合計: {len(cog_extensions)} Cogs")
            
            await ctx.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            error_msg = f"❌ Cog一覧の取得中にエラーが発生しました: {str(e)}"
            await ctx.followup.send(error_msg, ephemeral=True)
            logger.error(f"Failed to list cogs: {e}", exc_info=True)

def setup(bot):
    """Cogの設定"""
    bot.add_cog(ReloadCog(bot))