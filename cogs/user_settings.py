"""
ユーザー設定機能Cog
- 個人設定の管理
- TTS設定、読み上げ設定等
"""

import asyncio
import logging
import random
from typing import Dict, Any

import discord
from discord.ext import commands

from utils.user_settings import UserSettingsManager


class UserSettingsCog(commands.Cog):
    """ユーザー設定機能を提供するCog"""
    
    def __init__(self, bot: commands.Bot, config: Dict[str, Any]):
        self.bot = bot
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.user_settings = UserSettingsManager(config)
        
        # 初期化時の設定値をログ出力
        self.logger.info(f"UserSettings: Initialized for {self.user_settings.get_user_count()} users")
    
    async def rate_limit_delay(self):
        """レート制限対策の遅延"""
        delay = random.uniform(*self.config["bot"]["rate_limit_delay"])
        await asyncio.sleep(delay)
    
    @discord.slash_command(name="my_settings", description="現在の個人設定を表示します")
    async def my_settings_command(self, ctx: discord.ApplicationContext):
        """現在の個人設定を表示"""
        await self.rate_limit_delay()
        
        try:
            settings_summary = self.user_settings.get_settings_summary(ctx.user.id)
            
            embed = discord.Embed(
                title="⚙️ あなたの個人設定",
                description=settings_summary,
                color=discord.Color.blue()
            )
            embed.set_footer(text="設定を変更するには /set_tts, /set_reading コマンドを使用してください")
            
            await ctx.respond(embed=embed, ephemeral=True)
            
        except Exception as e:
            self.logger.error(f"Failed to show user settings: {e}")
            await ctx.respond(
                "❌ 設定の表示中にエラーが発生しました。",
                ephemeral=True
            )
    
    @discord.slash_command(name="set_tts", description="TTS設定を変更します")
    async def set_tts_command(
        self, 
        ctx: discord.ApplicationContext,
        model_id: discord.Option(int, "モデルID", min_value=0, required=False) = None,
        speaker_id: discord.Option(int, "話者ID", min_value=0, required=False) = None,
        style: discord.Option(str, "スタイル", required=False) = None,
        speed: discord.Option(float, "速度", min_value=0.5, max_value=2.0, required=False) = None,
        volume: discord.Option(float, "音量", min_value=0.1, max_value=2.0, required=False) = None
    ):
        """TTS設定を変更"""
        await self.rate_limit_delay()
        
        try:
            updated_settings = []
            
            # 各パラメータを更新
            if model_id is not None:
                self.user_settings.set_user_setting(ctx.user.id, "tts", "model_id", model_id)
                updated_settings.append(f"モデルID: {model_id}")
            
            if speaker_id is not None:
                self.user_settings.set_user_setting(ctx.user.id, "tts", "speaker_id", speaker_id)
                updated_settings.append(f"話者ID: {speaker_id}")
            
            if style is not None:
                self.user_settings.set_user_setting(ctx.user.id, "tts", "style", style)
                updated_settings.append(f"スタイル: {style}")
            
            if speed is not None:
                self.user_settings.set_user_setting(ctx.user.id, "tts", "speed", speed)
                updated_settings.append(f"速度: {speed}")
            
            if volume is not None:
                self.user_settings.set_user_setting(ctx.user.id, "tts", "volume", volume)
                updated_settings.append(f"音量: {volume}")
            
            if updated_settings:
                settings_text = "\n".join([f"• {setting}" for setting in updated_settings])
                await ctx.respond(
                    f"✅ TTS設定を更新しました:\n{settings_text}",
                    ephemeral=True
                )
                self.logger.info(f"Updated TTS settings for user {ctx.user}: {updated_settings}")
            else:
                await ctx.respond(
                    "❌ 更新する設定項目を指定してください。",
                    ephemeral=True
                )
            
        except Exception as e:
            self.logger.error(f"Failed to update TTS settings: {e}")
            await ctx.respond(
                "❌ TTS設定の更新中にエラーが発生しました。",
                ephemeral=True
            )
    
    @discord.slash_command(name="set_reading", description="読み上げ設定を変更します")
    async def set_reading_command(
        self, 
        ctx: discord.ApplicationContext,
        enabled: discord.Option(bool, "読み上げを有効にするか", required=False) = None,
        max_length: discord.Option(int, "最大文字数", min_value=10, max_value=500, required=False) = None,
        ignore_mentions: discord.Option(bool, "メンションを無視するか", required=False) = None,
        ignore_links: discord.Option(bool, "リンクを無視するか", required=False) = None
    ):
        """読み上げ設定を変更"""
        await self.rate_limit_delay()
        
        try:
            updated_settings = []
            
            # 各パラメータを更新
            if enabled is not None:
                self.user_settings.set_user_setting(ctx.user.id, "reading", "enabled", enabled)
                updated_settings.append(f"読み上げ: {'有効' if enabled else '無効'}")
            
            if max_length is not None:
                self.user_settings.set_user_setting(ctx.user.id, "reading", "max_length", max_length)
                updated_settings.append(f"最大文字数: {max_length}")
            
            if ignore_mentions is not None:
                self.user_settings.set_user_setting(ctx.user.id, "reading", "ignore_mentions", ignore_mentions)
                updated_settings.append(f"メンション無視: {'有効' if ignore_mentions else '無効'}")
            
            if ignore_links is not None:
                self.user_settings.set_user_setting(ctx.user.id, "reading", "ignore_links", ignore_links)
                updated_settings.append(f"リンク無視: {'有効' if ignore_links else '無効'}")
            
            if updated_settings:
                settings_text = "\n".join([f"• {setting}" for setting in updated_settings])
                await ctx.respond(
                    f"✅ 読み上げ設定を更新しました:\n{settings_text}",
                    ephemeral=True
                )
                self.logger.info(f"Updated reading settings for user {ctx.user}: {updated_settings}")
            else:
                await ctx.respond(
                    "❌ 更新する設定項目を指定してください。",
                    ephemeral=True
                )
            
        except Exception as e:
            self.logger.error(f"Failed to update reading settings: {e}")
            await ctx.respond(
                "❌ 読み上げ設定の更新中にエラーが発生しました。",
                ephemeral=True
            )
    
    @discord.slash_command(name="set_greeting", description="挨拶設定を変更します")
    async def set_greeting_command(
        self, 
        ctx: discord.ApplicationContext,
        enabled: discord.Option(bool, "挨拶を有効にするか", required=False) = None,
        custom_join: discord.Option(str, "カスタム参加挨拶", max_length=50, required=False) = None,
        custom_leave: discord.Option(str, "カスタム退出挨拶", max_length=50, required=False) = None
    ):
        """挨拶設定を変更"""
        await self.rate_limit_delay()
        
        try:
            updated_settings = []
            
            # 各パラメータを更新
            if enabled is not None:
                self.user_settings.set_user_setting(ctx.user.id, "greeting", "enabled", enabled)
                updated_settings.append(f"挨拶: {'有効' if enabled else '無効'}")
            
            if custom_join is not None:
                if custom_join.strip():
                    self.user_settings.set_user_setting(ctx.user.id, "greeting", "custom_join", custom_join)
                    updated_settings.append(f"参加挨拶: {custom_join}")
                else:
                    self.user_settings.set_user_setting(ctx.user.id, "greeting", "custom_join", None)
                    updated_settings.append("参加挨拶: デフォルトに戻しました")
            
            if custom_leave is not None:
                if custom_leave.strip():
                    self.user_settings.set_user_setting(ctx.user.id, "greeting", "custom_leave", custom_leave)
                    updated_settings.append(f"退出挨拶: {custom_leave}")
                else:
                    self.user_settings.set_user_setting(ctx.user.id, "greeting", "custom_leave", None)
                    updated_settings.append("退出挨拶: デフォルトに戻しました")
            
            if updated_settings:
                settings_text = "\n".join([f"• {setting}" for setting in updated_settings])
                await ctx.respond(
                    f"✅ 挨拶設定を更新しました:\n{settings_text}",
                    ephemeral=True
                )
                self.logger.info(f"Updated greeting settings for user {ctx.user}: {updated_settings}")
            else:
                await ctx.respond(
                    "❌ 更新する設定項目を指定してください。",
                    ephemeral=True
                )
            
        except Exception as e:
            self.logger.error(f"Failed to update greeting settings: {e}")
            await ctx.respond(
                "❌ 挨拶設定の更新中にエラーが発生しました。",
                ephemeral=True
            )
    
    @discord.slash_command(name="reset_settings", description="個人設定をリセットします")
    async def reset_settings_command(
        self, 
        ctx: discord.ApplicationContext,
        category: discord.Option(str, "リセットするカテゴリ", choices=["all", "tts", "reading", "greeting"], default="all")
    ):
        """個人設定をリセット"""
        await self.rate_limit_delay()
        
        try:
            if category == "all":
                success = self.user_settings.reset_user_settings(ctx.user.id)
                category_text = "全ての設定"
            else:
                success = self.user_settings.reset_user_settings(ctx.user.id, category)
                category_text = f"{category}設定"
            
            if success:
                await ctx.respond(
                    f"✅ {category_text}をデフォルトにリセットしました。",
                    ephemeral=True
                )
                self.logger.info(f"Reset {category} settings for user {ctx.user}")
            else:
                await ctx.respond(
                    "❌ 設定のリセットに失敗しました。",
                    ephemeral=True
                )
            
        except Exception as e:
            self.logger.error(f"Failed to reset settings: {e}")
            await ctx.respond(
                "❌ 設定のリセット中にエラーが発生しました。",
                ephemeral=True
            )
    
    @discord.slash_command(name="export_settings", description="個人設定をテキストファイルでエクスポートします")
    async def export_settings_command(self, ctx: discord.ApplicationContext):
        """個人設定をエクスポート"""
        await self.rate_limit_delay()
        
        try:
            export_text = self.user_settings.export_user_settings(ctx.user.id)
            
            # テキストファイルとして送信
            import io
            from datetime import datetime
            
            file_content = export_text.encode('utf-8')
            file_buffer = io.BytesIO(file_content)
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"user_settings_{ctx.user.id}_{timestamp}.txt"
            
            await ctx.respond(
                "📤 個人設定をエクスポートしました",
                file=discord.File(file_buffer, filename=filename),
                ephemeral=True
            )
            
            self.logger.info(f"Exported settings for user {ctx.user}")
            
        except Exception as e:
            self.logger.error(f"Failed to export settings: {e}")
            await ctx.respond(
                "❌ 設定のエクスポート中にエラーが発生しました。",
                ephemeral=True
            )
    
    def get_user_tts_settings(self, user_id: int) -> Dict[str, Any]:
        """外部からユーザーのTTS設定を取得"""
        return self.user_settings.get_tts_settings(user_id)
    
    def get_user_reading_settings(self, user_id: int) -> Dict[str, Any]:
        """外部からユーザーの読み上げ設定を取得"""
        return self.user_settings.get_reading_settings(user_id)
    
    def get_user_greeting_settings(self, user_id: int) -> Dict[str, Any]:
        """外部からユーザーの挨拶設定を取得"""
        return self.user_settings.get_greeting_settings(user_id)


def setup(bot):
    """Cogのセットアップ"""
    bot.add_cog(UserSettingsCog(bot, bot.config))