"""
メッセージ読み上げ機能Cog
"""

import asyncio
import logging
import re
from pathlib import Path
from typing import Dict, Any

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
        
        # 初期化時の設定値をログ出力
        self.logger.info(f"MessageReader: Initializing with reading_enabled: {self.reading_enabled}")
        self.logger.info(f"MessageReader: Config section: {config.get('message_reading', {})}")
        
        # 辞書の初期状態をログ出力
        global_count = len(self.dictionary_manager.global_dictionary)
        guild_count = len(self.dictionary_manager.guild_dictionaries)
        self.logger.info(f"MessageReader: Dictionary loaded - Global: {global_count} words, Guilds: {guild_count}")
        if global_count > 0:
            sample_words = list(self.dictionary_manager.global_dictionary.items())[:3]
            self.logger.info(f"MessageReader: Sample dictionary entries: {sample_words}")
    
    def cog_unload(self):
        """Cogアンロード時のクリーンアップ"""
        asyncio.create_task(self.tts_manager.cleanup())
    
    def is_reading_enabled(self, guild_id: int) -> bool:
        """ギルドで読み上げが有効かチェック"""
        if not self.reading_enabled:
            return False
        return self.guild_reading_enabled.get(guild_id, True)
    
    def _has_readable_content(self, message: discord.Message) -> bool:
        """本文または添付・スタンプがあるか確認"""
        if message.content and message.content.strip():
            return True
        attachments = getattr(message, "attachments", [])
        stickers = getattr(message, "stickers", [])
        return bool(attachments or stickers)

    def should_read_message(self, message: discord.Message) -> bool:
        """メッセージを読み上げるべきかチェック"""
        # ボットの場合
        if self.ignore_bots and message.author.bot:
            return False
        
        if not self._has_readable_content(message):
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

    @staticmethod
    def _guess_attachment_kind(attachment) -> str:
        """添付ファイルの種類を判定"""
        content_type = (getattr(attachment, "content_type", "") or "").lower()
        filename = (getattr(attachment, "filename", "") or "")
        suffix = Path(filename).suffix.lower()

        if content_type.startswith("image/") or suffix in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}:
            return "画像"
        if content_type.startswith("video/") or suffix in {".mp4", ".mov", ".wmv", ".avi", ".mkv"}:
            return "動画"
        if content_type.startswith("audio/") or suffix in {".mp3", ".wav", ".aac", ".flac", ".ogg"}:
            return "音声"
        if content_type in {"application/pdf"} or suffix == ".pdf":
            return "PDF"
        if suffix in {".txt", ".md", ".csv"}:
            return "テキスト"
        return "ファイル"

    @staticmethod
    def _summarize_attachments(attachments) -> str:
        """添付ファイルの概要を生成"""
        if not attachments:
            return ""

        return "ファイル"

    @staticmethod
    def _summarize_stickers(stickers) -> str:
        """スタンプの概要を生成"""
        if not stickers:
            return ""
        names = [getattr(sticker, "name", "スタンプ") for sticker in stickers[:3]]
        summary = "、".join(names)
        total = len(stickers)
        if total > 3:
            summary += f"、ほか{total - 3}件"
        return f"スタンプ: {summary}"

    def compose_message_text(self, message: discord.Message) -> str:
        """本文と添付要素を組み合わせた読み上げ対象文字列を作成"""
        segments = []

        base_text = self.preprocess_message(message.content)
        if base_text:
            segments.append(base_text)

        attachment_summary = self._summarize_attachments(getattr(message, "attachments", []))
        if attachment_summary:
            segments.append(attachment_summary)

        sticker_summary = self._summarize_stickers(getattr(message, "stickers", []))
        if sticker_summary:
            segments.append(sticker_summary)

        if not segments:
            return ""
        return "。".join(segments)
    
    async def _attempt_auto_reconnect(self, guild: discord.Guild) -> bool:
        """ボイスチャンネルへの自動再接続を試行"""
        try:
            self.logger.info(f"MessageReader: Attempting auto-reconnect in {guild.name}")
            
            # 既存の接続をクリーンアップ
            existing_client = guild.voice_client
            if existing_client:
                self.logger.info(f"MessageReader: Cleaning up existing voice client (connected: {existing_client.is_connected()})")
                try:
                    await existing_client.disconnect(force=True)
                    await asyncio.sleep(1)  # 切断完了を待つ
                except Exception as e:
                    self.logger.warning(f"MessageReader: Failed to disconnect existing client: {e}")
            
            # ユーザーがいるボイスチャンネルを探す
            target_channel = None
            for channel in guild.voice_channels:
                # Botを除いた実際のユーザーがいるかチェック
                non_bot_members = [member for member in channel.members if not member.bot]
                if non_bot_members:
                    target_channel = channel
                    self.logger.info(f"MessageReader: Found users in channel: {channel.name} ({len(non_bot_members)} users)")
                    break
            
            if not target_channel:
                self.logger.warning(f"MessageReader: No voice channels with users found in {guild.name}")
                return False
            
            # connect_voice_safely が利用可能なら優先して使用
            connect_callable = getattr(self.bot, "connect_voice_safely", None)
            try:
                if connect_callable:
                    voice_client = await connect_callable(target_channel)
                else:
                    voice_client = await target_channel.connect(reconnect=True, timeout=15.0)

                await asyncio.sleep(1)  # 接続安定化待機
                
                if voice_client and voice_client.is_connected():
                    self.logger.info(f"MessageReader: Auto-reconnect successful to {target_channel.name}")
                    return True
                self.logger.warning("MessageReader: Voice client not properly connected after join")
                return False
            except IndexError as index_error:
                self.logger.warning(f"MessageReader: Voice connect IndexError detected, retrying once: {index_error}")
                await asyncio.sleep(1.0)
                try:
                    if connect_callable:
                        voice_client = await connect_callable(target_channel)
                    else:
                        voice_client = await target_channel.connect(reconnect=True, timeout=15.0)
                    await asyncio.sleep(1)
                    if voice_client and voice_client.is_connected():
                        self.logger.info(f"MessageReader: Auto-reconnect successful to {target_channel.name} after retry")
                        return True
                except Exception as retry_error:
                    self.logger.error(f"MessageReader: Retry connect failed: {retry_error}")
                return False
            except Exception as connect_error:
                self.logger.error(f"MessageReader: Direct connect failed: {connect_error}")
                return False
                
        except Exception as e:
            self.logger.error(f"MessageReader: Auto-reconnect exception: {e}")
            return False
    
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """メッセージ受信時の読み上げ処理"""
        try:
            self.logger.info(f"MessageReader: Processing message from {message.author.display_name}: '{message.content[:50]}'")
            
            # 基本チェック
            if not message.guild:  # DMは対象外
                self.logger.debug("MessageReader: Skipping DM message")
                return
            
            if not self.should_read_message(message):
                self.logger.info(f"MessageReader: Message filtered out - Bot:{message.author.bot}, Content:'{message.content[:30]}'")
                return
            
            # ボットがVCに接続しているかチェック
            voice_client = message.guild.voice_client
            if not voice_client or not voice_client.is_connected():
                self.logger.warning(f"MessageReader: Bot not connected to voice channel in {message.guild.name}")
                self.logger.info(f"MessageReader: Voice client status - exists: {voice_client is not None}, connected: {voice_client.is_connected() if voice_client else 'N/A'}")
                
                # 自動再接続を試行
                reconnected = await self._attempt_auto_reconnect(message.guild)
                if not reconnected:
                    self.logger.warning(f"MessageReader: Auto-reconnect failed, skipping TTS")
                    return
                    
                # 再接続後のvoice_clientを取得
                voice_client = message.guild.voice_client
                self.logger.info(f"MessageReader: After reconnect - voice client exists: {voice_client is not None}, connected: {voice_client.is_connected() if voice_client else 'N/A'}")
            else:
                self.logger.info(f"MessageReader: Voice connection confirmed - channel: {voice_client.channel.name if voice_client.channel else 'Unknown'}")
            
            self.logger.info(f"MessageReader: Bot connected to voice channel: {voice_client.channel.name}")
            
            # メッセージの前処理
            message_text = self.compose_message_text(message)
            if not message_text:
                return

            # 辞書を適用
            original_content = message_text
            processed_content = self.dictionary_manager.apply_dictionary(message_text, message.guild.id)
            
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
            
            state_text = "有効" if new_state else "無効"
            await ctx.respond(
                f"📢 チャット読み上げを{state_text}にしました。",
                ephemeral=True
            )
            
            self.logger.info(f"MessageReader: Reading toggled to {new_state} for guild {ctx.guild.name}")
            
        except Exception as e:
            self.logger.error(f"MessageReader: Failed to toggle reading: {e}")
            await ctx.respond(
                "❌ 設定の変更に失敗しました。",
                ephemeral=True
            )


def setup(bot):
    """Cogのセットアップ"""
    bot.add_cog(MessageReaderCog(bot, bot.config))
