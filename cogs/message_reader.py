"""
メッセージ読み上げ機能Cog
- チャットメッセージの読み上げ
- メッセージの前処理（URL除去、長さ制限等）
- 読み上げ設定管理
"""

import asyncio
import logging
import re
from typing import Dict, Any, Optional

import discord
from discord.ext import commands

from utils.tts import TTSManager
from utils.dictionary import DictionaryManager


class MessageReaderCog(commands.Cog):
    """チャットメッセージの読み上げ機能"""
    
    def __init__(self, bot: commands.Bot, config: Dict[str, Any]):
        self.bot = bot
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.tts_manager = TTSManager(config)
        self.dictionary_manager = DictionaryManager(config)
        
        # 読み上げ設定
        self.reading_enabled = config.get("message_reading", {}).get("enabled", True)
        self.max_length = config.get("message_reading", {}).get("max_length", 100)
        self.ignore_prefixes = config.get("message_reading", {}).get("ignore_prefixes", ["!", "/", ".", "?"])
        self.ignore_bots = config.get("message_reading", {}).get("ignore_bots", True)
        
        # ギルドごとの読み上げ有効/無効状態
        self.guild_reading_enabled: Dict[int, bool] = {}
        self.load_guild_settings()  # 永続化設定の読み込み
        
        # 初期化時の設定値をログ出力
        self.logger.info(f"MessageReader: Initializing with reading_enabled: {self.reading_enabled}")
        self.logger.info(f"MessageReader: Config section: {config.get('message_reading', {})}")
        self.logger.info(f"MessageReader: Loaded guild settings: {self.guild_reading_enabled}")
        
        # 辞書の初期状態をログ出力
        global_count = len(self.dictionary_manager.global_dictionary)
        guild_count = len(self.dictionary_manager.guild_dictionaries)
        self.logger.info(f"MessageReader: Dictionary loaded - Global: {global_count} words, Guilds: {guild_count}")
        if global_count > 0:
            sample_words = list(self.dictionary_manager.global_dictionary.items())[:3]
            self.logger.info(f"MessageReader: Sample dictionary entries: {sample_words}")
    
    def cog_unload(self):
        """Cogアンロード時のクリーンアップ"""
        self.save_guild_settings()  # 設定を保存
        asyncio.create_task(self.tts_manager.cleanup())
    
    def load_guild_settings(self):
        """ギルド設定の読み込み"""
        try:
            import json
            from pathlib import Path
            
            settings_file = Path("data/guild_reading_settings.json")
            if settings_file.exists():
                with open(settings_file, "r", encoding="utf-8") as f:
                    saved_settings = json.load(f)
                    # 文字列キーを整数に変換
                    self.guild_reading_enabled = {int(k): v for k, v in saved_settings.items()}
                    self.logger.info(f"MessageReader: Loaded settings for {len(self.guild_reading_enabled)} guilds")
        except Exception as e:
            self.logger.error(f"MessageReader: Failed to load guild settings: {e}")
            self.guild_reading_enabled = {}
    
    def save_guild_settings(self):
        """ギルド設定の保存"""
        try:
            import json
            from pathlib import Path
            
            settings_file = Path("data/guild_reading_settings.json")
            settings_file.parent.mkdir(parents=True, exist_ok=True)
            
            # 整数キーを文字列に変換してJSON保存
            save_data = {str(k): v for k, v in self.guild_reading_enabled.items()}
            
            with open(settings_file, "w", encoding="utf-8") as f:
                json.dump(save_data, f, indent=2, ensure_ascii=False)
                
            self.logger.debug(f"MessageReader: Saved settings for {len(self.guild_reading_enabled)} guilds")
        except Exception as e:
            self.logger.error(f"MessageReader: Failed to save guild settings: {e}")
    
    def is_reading_enabled(self, guild_id: int) -> bool:
        """ギルドで読み上げが有効かチェック"""
        if not self.reading_enabled:
            return False
        return self.guild_reading_enabled.get(guild_id, True)
    
    def should_read_message(self, message: discord.Message) -> bool:
        """メッセージを読み上げるべきかチェック"""
        # ボットの場合
        if self.ignore_bots and message.author.bot:
            return False
        
        # 空のメッセージ
        if not message.content.strip():
            return False
        
        # プレフィックスチェック
        for prefix in self.ignore_prefixes:
            if message.content.startswith(prefix):
                return False
        
        # ギルドで読み上げが無効
        if not self.is_reading_enabled(message.guild.id):
            return False
        
        return True
    
    def preprocess_message(self, content: str) -> str:
        """メッセージの前処理"""
        # URL除去
        content = re.sub(r'https?://[^\s]+', 'URL', content)
        
        # Discord独特の記法を除去/変換
        content = re.sub(r'<@!?(\d+)>', 'メンション', content)  # ユーザーメンション
        content = re.sub(r'<#(\d+)>', 'チャンネル', content)     # チャンネルメンション
        content = re.sub(r'<@&(\d+)>', 'ロール', content)       # ロールメンション
        content = re.sub(r'<a?:(\w+):\d+>', r'\1', content)    # カスタム絵文字
        
        # 連続する空白を単一のスペースに
        content = re.sub(r'\s+', ' ', content)
        
        # 長さ制限
        if len(content) > self.max_length:
            content = content[:self.max_length] + "以下省略"
        
        return content.strip()
    
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """メッセージ受信時の読み上げ処理"""
        try:
            # 基本チェック
            if not message.guild:  # DMは対象外
                return
            
            guild_name = message.guild.name
            author_name = message.author.display_name
            content_preview = message.content[:50] + "..." if len(message.content) > 50 else message.content
            
            # should_read_messageの詳細チェック
            if not self.should_read_message(message):
                # 詳細な理由をログ出力
                reasons = []
                if self.ignore_bots and message.author.bot:
                    reasons.append("bot_message")
                if not message.content.strip():
                    reasons.append("empty_content")
                for prefix in self.ignore_prefixes:
                    if message.content.startswith(prefix):
                        reasons.append(f"prefix_{prefix}")
                        break
                if not self.is_reading_enabled(message.guild.id):
                    reasons.append("reading_disabled")
                
                self.logger.debug(f"MessageReader: Skipping message in {guild_name} from {author_name}: {', '.join(reasons)}")
                return
            
            # ボットがVCに接続しているかチェック
            voice_client = message.guild.voice_client
            if not voice_client or not voice_client.is_connected():
                self.logger.debug(f"MessageReader: Not connected to voice in {guild_name} - voice_client: {voice_client is not None}, connected: {voice_client.is_connected() if voice_client else False}")
                return
            
            # メッセージの前処理
            processed_content = self.preprocess_message(message.content)
            if not processed_content:
                self.logger.debug(f"MessageReader: Empty content after preprocessing in {guild_name}")
                return
            
            # 辞書を適用
            original_content = processed_content
            processed_content = self.dictionary_manager.apply_dictionary(processed_content, message.guild.id)
            
            # 辞書適用のデバッグログ
            if original_content != processed_content:
                self.logger.info(f"MessageReader: Dictionary applied: '{original_content}' -> '{processed_content}'")
            else:
                self.logger.debug(f"MessageReader: No dictionary changes applied to: '{original_content}'")
            
            self.logger.info(f"MessageReader: Reading message from {message.author.display_name}: {processed_content[:50]}...")
            
            # 統一されたTTS設定を使用（data/tts_config.jsonから）
            tts_config = self.tts_manager.tts_config
            tts_settings = {
                "model_id": tts_config.get("model_id", 5),
                "speaker_id": tts_config.get("speaker_id", 0),
                "style": tts_config.get("style", "01")
            }
            
            # 音声生成と再生
            audio_data = await self.tts_manager.generate_speech(
                text=processed_content,
                model_id=tts_settings.get("model_id", 0),
                speaker_id=tts_settings.get("speaker_id", 0),
                style=tts_settings.get("style", "Neutral")
            )
            
            if audio_data:
                await self.play_audio_from_bytes(voice_client, audio_data)
                self.logger.info(f"MessageReader: Successfully read message")
            else:
                self.logger.warning(f"MessageReader: Failed to generate audio for message")
                
        except Exception as e:
            self.logger.error(f"MessageReader: Failed to read message: {e}")
    
    async def play_audio_from_bytes(self, voice_client: discord.VoiceClient, audio_data: bytes):
        """バイト配列から音声を再生"""
        try:
            import tempfile
            import os
            from discord import FFmpegPCMAudio
            
            # 一時ファイルに音声データを保存
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
                temp_file.write(audio_data)
                temp_path = temp_file.name
            
            try:
                # 現在再生中の音声があれば停止
                if voice_client.is_playing():
                    voice_client.stop()
                    await asyncio.sleep(0.1)  # 停止の完了を待つ
                
                # 音声を再生
                source = FFmpegPCMAudio(temp_path)
                voice_client.play(source)
                
                # 再生完了まで待機（最大30秒）
                timeout = 30
                while voice_client.is_playing() and timeout > 0:
                    await asyncio.sleep(0.1)
                    timeout -= 0.1
                    
            finally:
                # 一時ファイルを削除
                try:
                    os.unlink(temp_path)
                except:
                    pass
                    
        except Exception as e:
            self.logger.error(f"MessageReader: Failed to play audio: {e}")
    
    @discord.slash_command(name="reading", description="チャット読み上げのON/OFFを切り替えます")
    async def toggle_reading(self, ctx: discord.ApplicationContext):
        """読み上げ機能のON/OFF切り替え"""
        try:
            guild_id = ctx.guild.id
            current_state = self.is_reading_enabled(guild_id)
            new_state = not current_state
            
            self.guild_reading_enabled[guild_id] = new_state
            self.save_guild_settings()  # 設定を即座に保存
            
            state_text = "有効" if new_state else "無効"
            
            # 詳細な状態情報を含める
            voice_client = ctx.guild.voice_client
            vc_status = "接続中" if voice_client and voice_client.is_connected() else "未接続"
            channel_name = voice_client.channel.name if voice_client and voice_client.is_connected() else "なし"
            
            response = f"📢 チャット読み上げを{state_text}にしました。\n"
            response += f"🔊 ボイスチャット: {vc_status} ({channel_name})\n"
            response += f"⚙️ グローバル設定: {'有効' if self.reading_enabled else '無効'}"
            
            await ctx.respond(response, ephemeral=True)
            
            self.logger.info(f"MessageReader: Reading toggled to {new_state} for guild {ctx.guild.name} (ID: {guild_id})")
            
        except Exception as e:
            self.logger.error(f"MessageReader: Failed to toggle reading: {e}")
            await ctx.respond(
                "❌ 設定の変更に失敗しました。",
                ephemeral=True
            )


def setup(bot):
    """Cogのセットアップ"""
    bot.add_cog(MessageReaderCog(bot, bot.config))