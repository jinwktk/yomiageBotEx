import discord
from discord.ext import commands


class AdminCog(commands.Cog):
    """管理者向けユーティリティコマンド"""

    def __init__(self, bot: commands.Bot, config):
        self.bot = bot
        self.config = config
        self.admin_user_id = config.get("bot", {}).get("admin_user_id")

    def _is_admin(self, user_id: int) -> bool:
        return self.admin_user_id is not None and user_id == self.admin_user_id

    @discord.slash_command(
        name="reload_cog",
        description="指定したCogをホットリロードします (管理者専用)"
    )
    async def reload_cog(
        self,
        ctx: discord.ApplicationContext,
        cog_name: discord.Option(str, "例: cogs.recording", required=True)
    ):
        if not self._is_admin(ctx.user.id):
            await ctx.respond("❌ このコマンドは管理者のみ使用できます。", ephemeral=True)
            return

        await ctx.defer(ephemeral=True)

        extension_name = cog_name.strip()
        if not extension_name.startswith("cogs."):
            extension_name = f"cogs.{extension_name}"

        try:
            if extension_name in self.bot.extensions:
                self.bot.reload_extension(extension_name)
            else:
                self.bot.load_extension(extension_name)
            await ctx.followup.send(f"✅ `{extension_name}` をリロードしました。", ephemeral=True)
        except Exception as exc:
            await ctx.followup.send(
                f"❌ `{extension_name}` のリロードに失敗しました:\n``{exc}``",
                ephemeral=True
            )


def setup(bot):
    bot.add_cog(AdminCog(bot, bot.config))
