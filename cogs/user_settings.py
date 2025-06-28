"""
ユーザー設定機能Cog
- 個人設定の管理
- TTS設定、読み上げ設定等
"""

import asyncio
import logging
import random
from typing import Dict, Any, List, Optional

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
            embed.set_footer(text="設定を変更するには /set_reading, /set_global_tts コマンドを使用してください")
            
            await ctx.respond(embed=embed, ephemeral=True)
            
        except Exception as e:
            self.logger.error(f"Failed to show user settings: {e}")
            await ctx.respond(
                "❌ 設定の表示中にエラーが発生しました。",
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
    
    @discord.slash_command(name="set_global_tts", description="サーバー全体のTTS設定を変更します（管理者限定）")
    async def set_global_tts_command(
        self, 
        ctx: discord.ApplicationContext,
        model_id: discord.Option(int, "モデルID (0-5)", min_value=0, max_value=5, required=False) = None,
        speaker_id: discord.Option(int, "話者ID (0)", min_value=0, max_value=0, required=False) = None,
        style: discord.Option(str, "スタイル", 
                             choices=["Neutral", "Happy", "Sad", "Angry", "01", "02", "03", "04"], 
                             required=False) = None
    ):
        """グローバルTTS設定を変更（管理者限定）"""
        await self.rate_limit_delay()
        
        # 管理者権限チェック
        if not ctx.author.guild_permissions.administrator:
            await ctx.respond("❌ この機能は管理者限定です。", ephemeral=True)
            return
        
        try:
            updated_settings = []
            
            # config.yamlの更新とファイル書き込み
            if model_id is not None:
                await self._update_global_config("message_reading", "model_id", model_id)
                await self._update_global_config("tts", "greeting", "model_id", model_id)
                updated_settings.append(f"モデルID: {model_id}")
            
            if speaker_id is not None:
                await self._update_global_config("message_reading", "speaker_id", speaker_id)
                await self._update_global_config("tts", "greeting", "speaker_id", speaker_id)
                updated_settings.append(f"話者ID: {speaker_id}")
            
            if style is not None:
                await self._update_global_config("message_reading", "style", style)
                await self._update_global_config("tts", "greeting", "style", style)
                updated_settings.append(f"スタイル: {style}")
            
            if updated_settings:
                settings_text = "\n".join([f"• {setting}" for setting in updated_settings])
                await ctx.respond(
                    f"✅ **サーバー全体**のTTS設定を更新しました:\n{settings_text}\n\n"
                    f"ℹ️ 変更は即座に全ユーザーに反映されます",
                    ephemeral=True
                )
                self.logger.info(f"Updated global TTS settings by {ctx.author}: {updated_settings}")
                
                # TTSManagerに設定変更を通知
                tts_cog = self.bot.get_cog("TTSCog")
                if tts_cog and hasattr(tts_cog, 'tts_manager'):
                    tts_cog.tts_manager.reload_config()
                    
                message_reader_cog = self.bot.get_cog("MessageReaderCog")
                if message_reader_cog:
                    message_reader_cog.config = self.config
            else:
                await ctx.respond(
                    "❌ 更新する設定項目を指定してください。",
                    ephemeral=True
                )
            
        except Exception as e:
            self.logger.error(f"Failed to update global TTS settings: {e}")
            await ctx.respond(
                "❌ グローバルTTS設定の更新中にエラーが発生しました。",
                ephemeral=True
            )
    
    async def _update_global_config(self, *keys_and_value):
        """config.yamlを動的に更新"""
        try:
            import yaml
            from pathlib import Path
            
            config_file = Path("config.yaml")
            if not config_file.exists():
                self.logger.error("config.yaml not found")
                return
                
            # 現在のconfig.yamlを読み込み
            with open(config_file, "r", encoding="utf-8") as f:
                config_data = yaml.safe_load(f)
            
            # ネストされた辞書を更新
            current = config_data
            keys = keys_and_value[:-1]
            value = keys_and_value[-1]
            
            for key in keys[:-1]:
                if key not in current:
                    current[key] = {}
                current = current[key]
                
            current[keys[-1]] = value
            
            # config.yamlに書き戻し
            with open(config_file, "w", encoding="utf-8") as f:
                yaml.dump(config_data, f, default_flow_style=False, allow_unicode=True, indent=2)
            
            # メモリ上のconfigも更新
            current = self.config
            for key in keys[:-1]:
                if key not in current:
                    current[key] = {}
                current = current[key]
            current[keys[-1]] = value
                
        except Exception as e:
            self.logger.error(f"Failed to update config: {e}")
    
    def get_user_reading_settings(self, user_id: int) -> Dict[str, Any]:
        """外部からユーザーの読み上げ設定を取得"""
        return self.user_settings.get_reading_settings(user_id)
    






def setup(bot):
    """Cogのセットアップ"""
    bot.add_cog(UserSettingsCog(bot, bot.config))