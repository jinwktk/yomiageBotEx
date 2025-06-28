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


class MessageReaderCog(commands.Cog):
    """チャットメッセージの読み上げ機能"""
    
    def __init__(self, bot: commands.Bot, config: Dict[str, Any]):
        self.bot = bot
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.tts_manager = TTSManager(config)
        
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
    
    def cog_unload(self):
        """Cogアンロード時のクリーンアップ"""
        asyncio.create_task(self.tts_manager.cleanup())
    
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
            
            if not self.should_read_message(message):
                return
            
            # ボットがVCに接続しているかチェック
            voice_client = message.guild.voice_client
            if not voice_client or not voice_client.is_connected():
                return
            
            # メッセージの前処理
            processed_content = self.preprocess_message(message.content)
            if not processed_content:
                return
            
            self.logger.info(f"MessageReader: Reading message from {message.author.display_name}: {processed_content[:50]}...")
            
            # 音声生成と再生
            audio_data = await self.tts_manager.generate_speech(
                text=processed_content,
                model_id=self.config.get("message_reading", {}).get("model_id", "default"),
                speaker_id=self.config.get("message_reading", {}).get("speaker_id", 0),
                style=self.config.get("message_reading", {}).get("style", "Neutral")
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