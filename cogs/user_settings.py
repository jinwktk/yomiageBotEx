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
        
        # 特定ユーザーIDでの管理者権限チェック
        admin_user_id = self.config.get("bot", {}).get("admin_user_id", 372768430149074954)
        if ctx.author.id != admin_user_id:
            await ctx.respond("❌ この機能は管理者限定です。", ephemeral=True)
            return
        
        try:
            # 現在の設定をdata/tts_config.jsonから取得
            from pathlib import Path
            import json
            
            config_file = Path("data/tts_config.json")
            if config_file.exists():
                with open(config_file, "r", encoding="utf-8") as f:
                    tts_config = json.load(f)
            else:
                # デフォルト設定
                tts_config = {
                    "model_id": 5,
                    "speaker_id": 0,
                    "style": "01",
                    "greeting": {
                        "enabled": True,
                        "skip_on_startup": True,
                        "join_message": "さん、こんちゃ！",
                        "leave_message": "さん、またね！"
                    }
                }
            
            # TTSManagerからモデル情報を取得
            available_models = None
            try:
                # TTSCogからTTSManagerを取得
                tts_cog = self.bot.get_cog('TTSCog')
                if tts_cog and hasattr(tts_cog, 'tts_manager'):
                    available_models = await tts_cog.tts_manager.get_available_models(force_refresh=True)
                    
                if available_models:
                    self.logger.info(f"Retrieved {len(available_models)} models for TTS settings UI")
                else:
                    self.logger.warning("No models available from TTS API, using fallback options")
                    
            except Exception as model_error:
                self.logger.warning(f"Failed to get models from TTS API: {model_error}")
                available_models = None
            
            # プルダウン選択用のビューを作成
            view = GlobalTTSSettingsView(self, tts_config, available_models)
            
            # 現在の設定を表示
            embed = discord.Embed(
                title="⚙️ サーバー全体のTTS設定",
                color=discord.Color.gold()
            )
            
            # モデル情報を含めた現在の設定表示
            model_name = "不明"
            
            if available_models:
                model_id = str(tts_config.get('model_id', 5))
                
                if model_id in available_models:
                    model_info = available_models[model_id]
                    speaker_names = list(model_info.get("id2spk", {}).values())
                    model_name = speaker_names[0] if speaker_names else f"モデル{model_id}"
            
            description = f"**現在の設定:**\n" \
                         f"🎤 **TTS設定（全機能共通）**\n" \
                         f"モデル: {model_name} (ID: {tts_config.get('model_id', 5)}) | " \
                         f"スタイル: {tts_config.get('style', 'Neutral')}"
            
            if available_models:
                description += f"\n\n📋 **利用可能モデル数:** {len(available_models)}種類"
                description += f"\n🔽 **まずモデルを選択してください。選択後にスタイル選択が表示されます。**"
            else:
                description += "\n\n⚠️ **モデル情報を取得できませんでした（フォールバック選択肢を使用）**"
            
            embed.description = description
            embed.set_footer(text="下のプルダウンメニューから設定を変更してください（全ユーザーに即座に反映されます）")
            
            await ctx.respond(embed=embed, view=view, ephemeral=True)
            
        except Exception as e:
            self.logger.error(f"Failed to show global TTS settings: {e}")
            await ctx.respond(
                "❌ グローバルTTS設定の表示中にエラーが発生しました。",
                ephemeral=True
            )
    
    async def _update_global_tts_config(self, **updates):
        """data/tts_config.jsonを動的に更新"""
        try:
            from pathlib import Path
            import json
            
            config_file = Path("data/tts_config.json")
            
            # 現在のTTS設定を読み込み
            if config_file.exists():
                with open(config_file, "r", encoding="utf-8") as f:
                    tts_config = json.load(f)
            else:
                # デフォルト設定
                tts_config = {
                    "api_url": "http://192.168.0.99:5000",
                    "timeout": 30,
                    "cache_size": 5,
                    "cache_hours": 24,
                    "max_text_length": 100,
                    "model_id": 5,
                    "speaker_id": 0,
                    "style": "01",
                    "greeting": {
                        "enabled": True,
                        "skip_on_startup": True,
                        "join_message": "さん、こんちゃ！",
                        "leave_message": "さん、またね！"
                    }
                }
            
            # 設定を更新
            for key, value in updates.items():
                if key in ["model_id", "speaker_id", "style"]:
                    tts_config[key] = value
                elif key.startswith("greeting_"):
                    greeting_key = key.replace("greeting_", "")
                    if "greeting" not in tts_config:
                        tts_config["greeting"] = {}
                    tts_config["greeting"][greeting_key] = value
            
            # ファイルに保存
            config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(tts_config, f, indent=2, ensure_ascii=False)
            
            # TTSManagerにも反映（全Cogで共有されているTTSManagerを更新）
            tts_cog = self.bot.get_cog("TTSCog")
            if tts_cog and hasattr(tts_cog, 'tts_manager'):
                tts_cog.tts_manager.reload_config()
            
            # MessageReaderCogのTTSManagerも更新
            message_reader_cog = self.bot.get_cog("MessageReaderCog")
            if message_reader_cog and hasattr(message_reader_cog, 'tts_manager'):
                message_reader_cog.tts_manager.reload_config()
                
        except Exception as e:
            self.logger.error(f"Failed to update TTS config: {e}")
    
    def get_user_reading_settings(self, user_id: int) -> Dict[str, Any]:
        """外部からユーザーの読み上げ設定を取得"""
        return self.user_settings.get_reading_settings(user_id)
    






class GlobalTTSSettingsView(discord.ui.View):
    """グローバルTTS設定のプルダウン選択UI"""
    
    def __init__(self, cog: UserSettingsCog, tts_config: Dict[str, Any], available_models: Optional[Dict[str, Any]] = None):
        super().__init__(timeout=300)  # 5分でタイムアウト
        self.cog = cog
        self.tts_config = tts_config
        self.available_models = available_models or {}
        
        # 現在の設定値
        self.current_model = tts_config.get("model_id", 5)
        self.current_speaker = tts_config.get("speaker_id", 0)
        self.current_style = tts_config.get("style", "Neutral")
        
        # 動的にSelectMenuを追加
        self._add_dynamic_selects()
    
    def _add_dynamic_selects(self):
        """利用可能なモデル情報に基づいてSelectMenuを動的に追加"""
        # モデル選択肢を生成
        model_options = self._create_model_options()
        if model_options:
            self.add_item(TTSModelSelect(placeholder="TTSモデルを選択", options=model_options))
        
        # 初期状態ではスタイル選択は表示しない（モデル選択後に動的追加）
    
    def _create_model_options(self) -> List[discord.SelectOption]:
        """モデル選択肢を作成"""
        options = []
        
        if not self.available_models:
            # フォールバック用の固定選択肢
            return [
                discord.SelectOption(label="モデル5 (デフォルト)", value="5", description="デフォルトモデル"),
                discord.SelectOption(label="モデル0", value="0", description="モデル0"),
                discord.SelectOption(label="モデル1", value="1", description="モデル1"),
            ]
        
        for model_id, model_info in self.available_models.items():
            # id2spkから話者名を取得
            speaker_names = list(model_info.get("id2spk", {}).values())
            speaker_name = speaker_names[0] if speaker_names else f"モデル{model_id}"
            
            # style2idからスタイル数を取得
            style_count = len(model_info.get("style2id", {}))
            
            # デフォルトマークを追加
            is_default = int(model_id) == self.current_model
            label = f"{speaker_name} (ID: {model_id})" + (" ⭐" if is_default else "")
            description = f"{style_count}スタイル利用可能"
            
            options.append(discord.SelectOption(
                label=label,
                value=model_id,
                description=description,
                default=is_default
            ))
        
        # 25個まで制限（Discordの制限）
        return options[:25]
    
    def _create_style_options(self, model_id: int) -> List[discord.SelectOption]:
        """指定モデルのスタイル選択肢を作成"""
        options = []
        
        if not self.available_models or str(model_id) not in self.available_models:
            # フォールバック用の固定選択肢
            return [
                discord.SelectOption(label="Neutral", value="Neutral", description="標準スタイル"),
                discord.SelectOption(label="01", value="01", description="スタイル01"),
                discord.SelectOption(label="02", value="02", description="スタイル02"),
            ]
        
        model_info = self.available_models[str(model_id)]
        style2id = model_info.get("style2id", {})
        
        for style_name, style_id in style2id.items():
            # 現在の設定と比較してデフォルトマークを追加
            is_default = style_name == self.current_style
            
            label = style_name + (" ⭐" if is_default else "")
            description = f"スタイルID: {style_id}"
            
            options.append(discord.SelectOption(
                label=label,
                value=style_name,
                description=description,
                default=is_default
            ))
        
        return options[:25]  # 25個まで制限
    
    def _update_style_select(self, selected_model_id: int):
        """選択されたモデルに基づいてスタイル選択を更新"""
        # 既存のスタイル選択を削除
        self.children = [child for child in self.children if not isinstance(child, TTSStyleSelect)]
        
        # モデル選択のデフォルト値を更新
        for child in self.children:
            if isinstance(child, TTSModelSelect):
                # 既存のモデル選択肢のデフォルト状態を更新
                child.options = self._create_model_options_with_selection(selected_model_id)
        
        # 新しいスタイル選択肢を生成
        style_options = self._create_style_options(selected_model_id)
        
        if style_options:
            # 新しいスタイル選択を追加
            self.add_item(TTSStyleSelect(placeholder="スタイルを選択", options=style_options))
    
    def _create_model_options_with_selection(self, selected_model_id: int) -> List[discord.SelectOption]:
        """指定されたモデルIDを選択状態にしたモデル選択肢を作成"""
        options = []
        
        if not self.available_models:
            # フォールバック用の固定選択肢
            return [
                discord.SelectOption(label="モデル5 (デフォルト)", value="5", description="デフォルトモデル", default=(selected_model_id == 5)),
                discord.SelectOption(label="モデル0", value="0", description="モデル0", default=(selected_model_id == 0)),
                discord.SelectOption(label="モデル1", value="1", description="モデル1", default=(selected_model_id == 1)),
            ]
        
        for model_id, model_info in self.available_models.items():
            # id2spkから話者名を取得
            speaker_names = list(model_info.get("id2spk", {}).values())
            speaker_name = speaker_names[0] if speaker_names else f"モデル{model_id}"
            
            # style2idからスタイル数を取得
            style_count = len(model_info.get("style2id", {}))
            
            # デフォルトマークを追加
            is_default = int(model_id) == selected_model_id
            label = f"{speaker_name} (ID: {model_id})" + (" ⭐" if is_default else "")
            description = f"{style_count}スタイル利用可能"
            
            options.append(discord.SelectOption(
                label=label,
                value=model_id,
                description=description,
                default=is_default
            ))
        
        # 25個まで制限（Discordの制限）
        return options[:25]
    
    def _update_style_select_with_selection(self, model_id: int, selected_style: str):
        """選択されたスタイルを維持したスタイル選択を更新"""
        # 既存のスタイル選択を削除
        self.children = [child for child in self.children if not isinstance(child, TTSStyleSelect)]
        
        # モデル選択のデフォルト値を更新
        for child in self.children:
            if isinstance(child, TTSModelSelect):
                # 既存のモデル選択肢のデフォルト状態を更新
                child.options = self._create_model_options_with_selection(model_id)
        
        # 選択されたスタイルを維持したスタイル選択肢を生成
        style_options = self._create_style_options_with_selection(model_id, selected_style)
        
        if style_options:
            # 新しいスタイル選択を追加
            self.add_item(TTSStyleSelect(placeholder="スタイルを選択", options=style_options))
    
    def _create_style_options_with_selection(self, model_id: int, selected_style: str) -> List[discord.SelectOption]:
        """指定されたスタイルを選択状態にしたスタイル選択肢を作成"""
        options = []
        
        if not self.available_models or str(model_id) not in self.available_models:
            # フォールバック用の固定選択肢
            return [
                discord.SelectOption(label="Neutral", value="Neutral", description="標準スタイル", default=(selected_style == "Neutral")),
                discord.SelectOption(label="01", value="01", description="スタイル01", default=(selected_style == "01")),
                discord.SelectOption(label="02", value="02", description="スタイル02", default=(selected_style == "02")),
            ]
        
        model_info = self.available_models[str(model_id)]
        style2id = model_info.get("style2id", {})
        
        for style_name, style_id in style2id.items():
            # 現在の設定と比較してデフォルトマークを追加
            is_default = style_name == selected_style
            
            label = style_name + (" ⭐" if is_default else "")
            description = f"スタイルID: {style_id}"
            
            options.append(discord.SelectOption(
                label=label,
                value=style_name,
                description=description,
                default=is_default
            ))
        
        return options[:25]  # 25個まで制限
    
    async def on_timeout(self):
        """タイムアウト時の処理"""
        # ビューを無効化
        for item in self.children:
            item.disabled = True


class TTSModelSelect(discord.ui.Select):
    """TTSモデル選択用のSelectコンポーネント"""
    
    def __init__(self, placeholder: str, options: List[discord.SelectOption]):
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options)
    
    async def callback(self, interaction: discord.Interaction):
        try:
            new_model_id = int(self.values[0])
            view: GlobalTTSSettingsView = self.view
            
            # 設定を更新
            await view.cog._update_global_tts_config(model_id=new_model_id)
            view.current_model = new_model_id
            
            # TTSManagerの設定を更新
            if hasattr(view.cog.bot, 'get_cog'):
                tts_cog = view.cog.bot.get_cog('TTSCog')
                message_reader_cog = view.cog.bot.get_cog('MessageReaderCog')
                if tts_cog and hasattr(tts_cog, 'tts_manager'):
                    tts_cog.tts_manager.reload_config()
                if message_reader_cog and hasattr(message_reader_cog, 'tts_manager'):
                    message_reader_cog.tts_manager.reload_config()
            
            # モデル名を取得
            model_name = "不明"
            if view.available_models and str(new_model_id) in view.available_models:
                model_info = view.available_models[str(new_model_id)]
                speaker_names = list(model_info.get("id2spk", {}).values())
                model_name = speaker_names[0] if speaker_names else f"モデル{new_model_id}"
            
            # スタイル選択を更新
            view._update_style_select(new_model_id)
            
            # 新しいEmbedを作成
            embed = discord.Embed(
                title="⚙️ サーバー全体のTTS設定",
                color=discord.Color.gold()
            )
            
            description = f"**現在の設定:**\n" \
                         f"🎤 **TTS設定（全機能共通）**\n" \
                         f"モデル: {model_name} (ID: {new_model_id}) | " \
                         f"スタイル: {view.tts_config.get('style', 'Neutral')}"
            
            if view.available_models:
                description += f"\n\n📋 **利用可能モデル数:** {len(view.available_models)}種類"
                description += f"\n✅ **モデルを選択しました。下のスタイル選択で声の調子を選んでください。**"
            else:
                description += "\n\n⚠️ **モデル情報を取得できませんでした（フォールバック選択肢を使用）**"
            
            embed.description = description
            embed.set_footer(text="下のプルダウンメニューから設定を変更してください（全ユーザーに即座に反映されます）")
            
            # メッセージを編集して新しいビューを表示
            await interaction.response.edit_message(embed=embed, view=view)
            
            view.cog.logger.info(f"Global TTS model updated to {new_model_id} ({model_name})")
            
        except Exception as e:
            view.cog.logger.error(f"Failed to update TTS model: {e}")
            await interaction.response.send_message(
                "❌ TTSモデルの変更に失敗しました。",
                ephemeral=True
            )


class TTSStyleSelect(discord.ui.Select):
    """TTSスタイル選択用のSelectコンポーネント"""
    
    def __init__(self, placeholder: str, options: List[discord.SelectOption]):
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options)
    
    async def callback(self, interaction: discord.Interaction):
        try:
            new_style = self.values[0]
            view: GlobalTTSSettingsView = self.view
            
            # 設定を更新
            await view.cog._update_global_tts_config(style=new_style)
            view.current_style = new_style
            
            # TTSManagerの設定を更新
            if hasattr(view.cog.bot, 'get_cog'):
                tts_cog = view.cog.bot.get_cog('TTSCog')
                message_reader_cog = view.cog.bot.get_cog('MessageReaderCog')
                if tts_cog and hasattr(tts_cog, 'tts_manager'):
                    tts_cog.tts_manager.reload_config()
                if message_reader_cog and hasattr(message_reader_cog, 'tts_manager'):
                    message_reader_cog.tts_manager.reload_config()
            
            # モデル名を取得
            model_name = "不明"
            if view.available_models and str(view.current_model) in view.available_models:
                model_info = view.available_models[str(view.current_model)]
                speaker_names = list(model_info.get("id2spk", {}).values())
                model_name = speaker_names[0] if speaker_names else f"モデル{view.current_model}"
            
            # 新しいEmbedを作成
            embed = discord.Embed(
                title="⚙️ サーバー全体のTTS設定",
                color=discord.Color.green()  # 設定完了を表すため緑色に
            )
            
            description = f"**現在の設定:**\n" \
                         f"🎤 **TTS設定（全機能共通）**\n" \
                         f"モデル: {model_name} (ID: {view.current_model}) | " \
                         f"スタイル: {new_style}"
            
            if view.available_models:
                description += f"\n\n📋 **利用可能モデル数:** {len(view.available_models)}種類"
                description += f"\n✅ **設定完了！メッセージ読み上げと挨拶に反映されます。**"
            else:
                description += "\n\n⚠️ **モデル情報を取得できませんでした（フォールバック選択肢を使用）**"
            
            embed.description = description
            embed.set_footer(text="設定を変更したい場合は、再度 /set_global_tts コマンドを実行してください")
            
            # スタイル選択のデフォルト値を更新
            view._update_style_select_with_selection(view.current_model, new_style)
            
            # メッセージを編集
            await interaction.response.edit_message(embed=embed, view=view)
            
            view.cog.logger.info(f"Global TTS style updated to {new_style}")
            
        except Exception as e:
            view.cog.logger.error(f"Failed to update TTS style: {e}")
            await interaction.response.send_message(
                "❌ TTSスタイルの変更に失敗しました。",
                ephemeral=True
            )
    
def setup(bot):
    """Cogのセットアップ"""
    bot.add_cog(UserSettingsCog(bot, bot.config))