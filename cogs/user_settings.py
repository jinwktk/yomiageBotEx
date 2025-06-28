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
from utils.tts import TTSManager


class UserSettingsCog(commands.Cog):
    """ユーザー設定機能を提供するCog"""
    
    def __init__(self, bot: commands.Bot, config: Dict[str, Any]):
        self.bot = bot
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.user_settings = UserSettingsManager(config)
        self.tts_manager = TTSManager(config)
        
        # キャッシュされたモデル・話者情報
        self.cached_models: Optional[Dict[str, Any]] = None
        self.cached_speakers: Dict[int, Dict[str, Any]] = {}
        
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
    
    async def get_model_choices(self) -> List[discord.OptionChoice]:
        """モデル選択肢を取得"""
        try:
            if self.cached_models is None:
                self.cached_models = await self.tts_manager.get_available_models()
            
            if self.cached_models:
                choices = []
                for model_id, model_info in list(self.cached_models.items())[:25]:  # Discord制限
                    name = model_info.get("name", f"Model {model_id}")
                    choices.append(discord.OptionChoice(name=f"{model_id}: {name}"[:100], value=int(model_id)))
                return choices
        except:
            pass
        
        # フォールバック：デフォルト選択肢
        return [discord.OptionChoice(name="0: デフォルト", value=0)]
    
    async def get_speaker_choices(self, model_id: int) -> List[discord.OptionChoice]:
        """話者選択肢を取得"""
        try:
            if model_id not in self.cached_speakers:
                self.cached_speakers[model_id] = await self.tts_manager.get_model_speakers(model_id)
            
            speakers = self.cached_speakers[model_id]
            if speakers:
                choices = []
                for speaker_id, speaker_info in list(speakers.items())[:25]:  # Discord制限
                    name = speaker_info.get("name", f"Speaker {speaker_id}")
                    choices.append(discord.OptionChoice(name=f"{speaker_id}: {name}"[:100], value=int(speaker_id)))
                return choices
        except:
            pass
        
        # フォールバック：デフォルト選択肢
        return [discord.OptionChoice(name="0: デフォルト", value=0)]
    
    @discord.slash_command(name="set_tts", description="TTS設定を変更します（プルダウン選択）")
    async def set_tts_command(self, ctx: discord.ApplicationContext):
        """TTS設定を変更（プルダウン選択式）"""
        await self.rate_limit_delay()
        
        try:
            # 現在の設定を取得
            current_settings = self.user_settings.get_tts_settings(ctx.user.id)
            
            # シンプルなビューを作成
            view = SimpleTTSSettingsView(self, ctx.user.id, current_settings)
            
            # モデル名を取得
            model_id = current_settings.get('model_id', 0)
            model_names = {
                0: "jvnv-F1-jp（女性1）",
                1: "jvnv-F2-jp（女性2）", 
                2: "jvnv-M1-jp（男性1）",
                3: "jvnv-M2-jp（男性2）",
                4: "小春音アミ",
                5: "あみたろ"
            }
            model_name = model_names.get(model_id, f"Model {model_id}")
            
            # 現在の設定を表示
            embed = discord.Embed(
                title="⚙️ TTS設定",
                description=f"**現在の設定:**\n"
                           f"モデル: {model_id} - {model_name}\n"
                           f"話者ID: {current_settings.get('speaker_id', 0)} (標準話者)\n"
                           f"スタイル: {current_settings.get('style', 'Neutral')}\n"
                           f"速度: {current_settings.get('speed', 1.0)}\n"
                           f"音量: {current_settings.get('volume', 1.0)}",
                color=discord.Color.blue()
            )
            embed.set_footer(text="下のプルダウンメニューから設定を変更してください")
            
            await ctx.respond(embed=embed, view=view, ephemeral=True)
            
        except Exception as e:
            self.logger.error(f"Failed to show TTS settings: {e}")
            await ctx.respond(
                "❌ TTS設定の表示中にエラーが発生しました。",
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
    
    
    
    def get_user_tts_settings(self, user_id: int) -> Dict[str, Any]:
        """外部からユーザーのTTS設定を取得"""
        return self.user_settings.get_tts_settings(user_id)
    
    def get_user_reading_settings(self, user_id: int) -> Dict[str, Any]:
        """外部からユーザーの読み上げ設定を取得"""
        return self.user_settings.get_reading_settings(user_id)
    
    def get_user_greeting_settings(self, user_id: int) -> Dict[str, Any]:
        """外部からユーザーの挨拶設定を取得"""
        return self.user_settings.get_greeting_settings(user_id)


class SimpleTTSSettingsView(discord.ui.View):
    """シンプルなTTS設定用のビュー"""
    
    def __init__(self, cog: 'UserSettingsCog', user_id: int, current_settings: Dict[str, Any]):
        super().__init__(timeout=300)
        self.cog = cog
        self.user_id = user_id
        self.current_settings = current_settings
    
    @discord.ui.select(
        placeholder="モデルを選択してください",
        min_values=1,
        max_values=1,
        options=[
            discord.SelectOption(label="0: jvnv-F1-jp（女性1）", value="0"),
            discord.SelectOption(label="1: jvnv-F2-jp（女性2）", value="1"),
            discord.SelectOption(label="2: jvnv-M1-jp（男性1）", value="2"),
            discord.SelectOption(label="3: jvnv-M2-jp（男性2）", value="3"),
            discord.SelectOption(label="4: 小春音アミ", value="4"),
            discord.SelectOption(label="5: あみたろ", value="5")
        ]
    )
    async def model_select(self, select: discord.ui.Select, interaction: discord.Interaction):
        try:
            model_id = int(select.values[0])
            self.cog.user_settings.set_user_setting(self.user_id, "tts", "model_id", model_id)
            
            await interaction.response.send_message(
                f"✅ モデルIDを {model_id} に設定しました",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                "❌ モデル設定中にエラーが発生しました",
                ephemeral=True
            )
    
    @discord.ui.select(
        placeholder="話者を選択してください（選択されたモデルに依存）",
        min_values=1,
        max_values=1,
        options=[
            discord.SelectOption(label="0: 標準話者（全モデル共通）", value="0")
        ]
    )
    async def speaker_select(self, select: discord.ui.Select, interaction: discord.Interaction):
        try:
            speaker_id = int(select.values[0])
            self.cog.user_settings.set_user_setting(self.user_id, "tts", "speaker_id", speaker_id)
            
            await interaction.response.send_message(
                f"✅ 話者IDを {speaker_id} に設定しました",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                "❌ 話者設定中にエラーが発生しました",
                ephemeral=True
            )
    
    @discord.ui.select(
        placeholder="スタイルを選択してください",
        min_values=1,
        max_values=1,
        options=[
            discord.SelectOption(label="Neutral（標準）", value="Neutral"),
            discord.SelectOption(label="Happy（嬉しい）", value="Happy"),
            discord.SelectOption(label="Sad（悲しい）", value="Sad"),
            discord.SelectOption(label="Angry（怒り）", value="Angry"),
            discord.SelectOption(label="Fear（恐怖）", value="Fear"),
            discord.SelectOption(label="Surprise（驚き）", value="Surprise"),
            discord.SelectOption(label="Disgust（嫌悪）", value="Disgust"),
            discord.SelectOption(label="るんるん（小春音アミ専用）", value="るんるん"),
            discord.SelectOption(label="ささやきA（小春音アミ専用）", value="ささやきA（無声）"),
            discord.SelectOption(label="ささやきB（小春音アミ専用）", value="ささやきB（有声）"),
            discord.SelectOption(label="ノーマル（小春音アミ専用）", value="ノーマル"),
            discord.SelectOption(label="よふかし（小春音アミ専用）", value="よふかし"),
            discord.SelectOption(label="01（あみたろ専用）", value="01"),
            discord.SelectOption(label="02（あみたろ専用）", value="02"),
            discord.SelectOption(label="03（あみたろ専用）", value="03"),
            discord.SelectOption(label="04（あみたろ専用）", value="04")
        ]
    )
    async def style_select(self, select: discord.ui.Select, interaction: discord.Interaction):
        try:
            style = select.values[0]
            self.cog.user_settings.set_user_setting(self.user_id, "tts", "style", style)
            
            await interaction.response.send_message(
                f"✅ スタイルを {style} に設定しました",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                "❌ スタイル設定中にエラーが発生しました",
                ephemeral=True
            )
    
    @discord.ui.select(
        placeholder="速度を選択してください",
        min_values=1,
        max_values=1,
        options=[
            discord.SelectOption(label="0.5: とても遅い", value="0.5"),
            discord.SelectOption(label="0.75: 遅い", value="0.75"),
            discord.SelectOption(label="1.0: 標準", value="1.0"),
            discord.SelectOption(label="1.25: 速い", value="1.25"),
            discord.SelectOption(label="1.5: とても速い", value="1.5"),
            discord.SelectOption(label="2.0: 最高速", value="2.0")
        ]
    )
    async def speed_select(self, select: discord.ui.Select, interaction: discord.Interaction):
        try:
            speed = float(select.values[0])
            self.cog.user_settings.set_user_setting(self.user_id, "tts", "speed", speed)
            
            await interaction.response.send_message(
                f"✅ 速度を {speed} に設定しました",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                "❌ 速度設定中にエラーが発生しました",
                ephemeral=True
            )




def setup(bot):
    """Cogのセットアップ"""
    bot.add_cog(UserSettingsCog(bot, bot.config))