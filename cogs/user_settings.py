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
    async def set_global_tts_command(self, ctx: discord.ApplicationContext):
        """グローバルTTS設定を変更（プルダウン選択式・管理者限定）"""
        await self.rate_limit_delay()
        
        # 管理者権限チェック
        if not ctx.author.guild_permissions.administrator:
            await ctx.respond("❌ この機能は管理者限定です。", ephemeral=True)
            return
        
        try:
            # 現在の設定を取得
            tts_config = self.config.get("message_reading", {})
            greeting_config = self.config.get("tts", {}).get("greeting", {})
            
            # プルダウン選択用のビューを作成
            view = GlobalTTSSettingsView(self, tts_config, greeting_config)
            
            # 現在の設定を表示
            embed = discord.Embed(
                title="⚙️ サーバー全体のTTS設定",
                description=f"**現在の設定:**\n"
                           f"🎤 **メッセージ読み上げ**\n"
                           f"モデルID: {tts_config.get('model_id', 5)} | 話者ID: {tts_config.get('speaker_id', 0)} | スタイル: {tts_config.get('style', '01')}\n\n"
                           f"👋 **挨拶**\n"
                           f"モデルID: {greeting_config.get('model_id', 5)} | 話者ID: {greeting_config.get('speaker_id', 0)} | スタイル: {greeting_config.get('style', '01')}",
                color=discord.Color.gold()
            )
            embed.set_footer(text="下のプルダウンメニューから設定を変更してください（全ユーザーに即座に反映されます）")
            
            await ctx.respond(embed=embed, view=view, ephemeral=True)
            
        except Exception as e:
            self.logger.error(f"Failed to show global TTS settings: {e}")
            await ctx.respond(
                "❌ グローバルTTS設定の表示中にエラーが発生しました。",
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
    






class GlobalTTSSettingsView(discord.ui.View):
    """グローバルTTS設定のプルダウン選択UI"""
    
    def __init__(self, cog: UserSettingsCog, tts_config: Dict[str, Any], greeting_config: Dict[str, Any]):
        super().__init__(timeout=300)  # 5分でタイムアウト
        self.cog = cog
        self.tts_config = tts_config
        self.greeting_config = greeting_config
        
        # 現在の設定値
        self.current_tts_model = tts_config.get("model_id", 5)
        self.current_tts_speaker = tts_config.get("speaker_id", 0)
        self.current_tts_style = tts_config.get("style", "01")
        self.current_greeting_model = greeting_config.get("model_id", 5)
        self.current_greeting_speaker = greeting_config.get("speaker_id", 0)
        self.current_greeting_style = greeting_config.get("style", "01")
    
    @discord.ui.select(
        placeholder="メッセージ読み上げのモデルIDを選択",
        min_values=1,
        max_values=1,
        options=[
            discord.SelectOption(label="モデル1", value="1", description="モデル1の説明"),
            discord.SelectOption(label="モデル5 (デフォルト)", value="5", description="モデル5の説明"),
            discord.SelectOption(label="モデル10", value="10", description="モデル10の説明"),
        ]
    )
    async def tts_model_select(self, select: discord.ui.Select, interaction: discord.Interaction):
        """メッセージ読み上げのモデル選択"""
        try:
            new_model_id = int(select.values[0])
            await self.cog._update_global_config("message_reading", "model_id", new_model_id)
            
            # TTSManagerの設定を更新
            if hasattr(self.cog.bot, 'get_cog'):
                tts_cog = self.cog.bot.get_cog('TTSCog')
                message_reader_cog = self.cog.bot.get_cog('MessageReaderCog')
                if tts_cog and hasattr(tts_cog, 'tts_manager'):
                    tts_cog.tts_manager.reload_config()
                if message_reader_cog and hasattr(message_reader_cog, 'tts_manager'):
                    message_reader_cog.tts_manager.reload_config()
            
            self.current_tts_model = new_model_id
            await interaction.response.send_message(
                f"✅ メッセージ読み上げのモデルIDを {new_model_id} に変更しました。",
                ephemeral=True
            )
            self.cog.logger.info(f"Global TTS model updated to {new_model_id}")
            
        except Exception as e:
            self.cog.logger.error(f"Failed to update TTS model: {e}")
            await interaction.response.send_message(
                "❌ モデルIDの変更に失敗しました。",
                ephemeral=True
            )
    
    @discord.ui.select(
        placeholder="メッセージ読み上げの話者IDを選択",
        min_values=1,
        max_values=1,
        options=[
            discord.SelectOption(label="話者0 (デフォルト)", value="0", description="デフォルト話者"),
            discord.SelectOption(label="話者1", value="1", description="話者1の説明"),
            discord.SelectOption(label="話者2", value="2", description="話者2の説明"),
        ]
    )
    async def tts_speaker_select(self, select: discord.ui.Select, interaction: discord.Interaction):
        """メッセージ読み上げの話者選択"""
        try:
            new_speaker_id = int(select.values[0])
            await self.cog._update_global_config("message_reading", "speaker_id", new_speaker_id)
            
            # TTSManagerの設定を更新
            if hasattr(self.cog.bot, 'get_cog'):
                tts_cog = self.cog.bot.get_cog('TTSCog')
                message_reader_cog = self.cog.bot.get_cog('MessageReaderCog')
                if tts_cog and hasattr(tts_cog, 'tts_manager'):
                    tts_cog.tts_manager.reload_config()
                if message_reader_cog and hasattr(message_reader_cog, 'tts_manager'):
                    message_reader_cog.tts_manager.reload_config()
            
            self.current_tts_speaker = new_speaker_id
            await interaction.response.send_message(
                f"✅ メッセージ読み上げの話者IDを {new_speaker_id} に変更しました。",
                ephemeral=True
            )
            self.cog.logger.info(f"Global TTS speaker updated to {new_speaker_id}")
            
        except Exception as e:
            self.cog.logger.error(f"Failed to update TTS speaker: {e}")
            await interaction.response.send_message(
                "❌ 話者IDの変更に失敗しました。",
                ephemeral=True
            )
    
    @discord.ui.select(
        placeholder="メッセージ読み上げのスタイルを選択",
        min_values=1,
        max_values=1,
        options=[
            discord.SelectOption(label="01 (デフォルト)", value="01", description="標準スタイル"),
            discord.SelectOption(label="02", value="02", description="スタイル02"),
            discord.SelectOption(label="03", value="03", description="スタイル03"),
            discord.SelectOption(label="Neutral", value="Neutral", description="ニュートラル"),
        ]
    )
    async def tts_style_select(self, select: discord.ui.Select, interaction: discord.Interaction):
        """メッセージ読み上げのスタイル選択"""
        try:
            new_style = select.values[0]
            await self.cog._update_global_config("message_reading", "style", new_style)
            
            # TTSManagerの設定を更新
            if hasattr(self.cog.bot, 'get_cog'):
                tts_cog = self.cog.bot.get_cog('TTSCog')
                message_reader_cog = self.cog.bot.get_cog('MessageReaderCog')
                if tts_cog and hasattr(tts_cog, 'tts_manager'):
                    tts_cog.tts_manager.reload_config()
                if message_reader_cog and hasattr(message_reader_cog, 'tts_manager'):
                    message_reader_cog.tts_manager.reload_config()
            
            self.current_tts_style = new_style
            await interaction.response.send_message(
                f"✅ メッセージ読み上げのスタイルを {new_style} に変更しました。",
                ephemeral=True
            )
            self.cog.logger.info(f"Global TTS style updated to {new_style}")
            
        except Exception as e:
            self.cog.logger.error(f"Failed to update TTS style: {e}")
            await interaction.response.send_message(
                "❌ スタイルの変更に失敗しました。",
                ephemeral=True
            )
    
    @discord.ui.select(
        placeholder="挨拶のモデルIDを選択",
        min_values=1,
        max_values=1,
        options=[
            discord.SelectOption(label="モデル1", value="1", description="モデル1の説明"),
            discord.SelectOption(label="モデル5 (デフォルト)", value="5", description="モデル5の説明"),
            discord.SelectOption(label="モデル10", value="10", description="モデル10の説明"),
        ]
    )
    async def greeting_model_select(self, select: discord.ui.Select, interaction: discord.Interaction):
        """挨拶のモデル選択"""
        try:
            new_model_id = int(select.values[0])
            await self.cog._update_global_config("tts", "greeting", "model_id", new_model_id)
            
            # TTSManagerの設定を更新
            if hasattr(self.cog.bot, 'get_cog'):
                tts_cog = self.cog.bot.get_cog('TTSCog')
                if tts_cog and hasattr(tts_cog, 'tts_manager'):
                    tts_cog.tts_manager.reload_config()
            
            self.current_greeting_model = new_model_id
            await interaction.response.send_message(
                f"✅ 挨拶のモデルIDを {new_model_id} に変更しました。",
                ephemeral=True
            )
            self.cog.logger.info(f"Global greeting model updated to {new_model_id}")
            
        except Exception as e:
            self.cog.logger.error(f"Failed to update greeting model: {e}")
            await interaction.response.send_message(
                "❌ 挨拶モデルIDの変更に失敗しました。",
                ephemeral=True
            )
    
    @discord.ui.select(
        placeholder="挨拶のスタイルを選択",
        min_values=1,
        max_values=1,
        options=[
            discord.SelectOption(label="01 (デフォルト)", value="01", description="標準スタイル"),
            discord.SelectOption(label="02", value="02", description="スタイル02"),
            discord.SelectOption(label="03", value="03", description="スタイル03"),
            discord.SelectOption(label="Neutral", value="Neutral", description="ニュートラル"),
        ]
    )
    async def greeting_style_select(self, select: discord.ui.Select, interaction: discord.Interaction):
        """挨拶のスタイル選択"""
        try:
            new_style = select.values[0]
            await self.cog._update_global_config("tts", "greeting", "style", new_style)
            
            # TTSManagerの設定を更新
            if hasattr(self.cog.bot, 'get_cog'):
                tts_cog = self.cog.bot.get_cog('TTSCog')
                if tts_cog and hasattr(tts_cog, 'tts_manager'):
                    tts_cog.tts_manager.reload_config()
            
            self.current_greeting_style = new_style
            await interaction.response.send_message(
                f"✅ 挨拶のスタイルを {new_style} に変更しました。",
                ephemeral=True
            )
            self.cog.logger.info(f"Global greeting style updated to {new_style}")
            
        except Exception as e:
            self.cog.logger.error(f"Failed to update greeting style: {e}")
            await interaction.response.send_message(
                "❌ 挨拶スタイルの変更に失敗しました。",
                ephemeral=True
            )
    
    async def on_timeout(self):
        """タイムアウト時の処理"""
        # ビューを無効化
        for item in self.children:
            item.disabled = True


def setup(bot):
    """Cogのセットアップ"""
    bot.add_cog(UserSettingsCog(bot, bot.config))