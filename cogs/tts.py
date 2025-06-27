"""
TTS（Text-to-Speech）機能Cog
- 挨拶機能（参加・退出時の音声再生）
- TTSキャッシュ管理
- Style-Bert-VITS2統合
"""

import asyncio
import logging
import io
from typing import Dict, Any, Optional

import discord
from discord.ext import commands
from discord import FFmpegPCMAudio

from utils.tts import TTSManager


class TTSCog(commands.Cog):
    """TTS機能を提供するCog"""
    
    def __init__(self, bot: commands.Bot, config: Dict[str, Any]):
        self.bot = bot
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.tts_manager = TTSManager(config)
        self.greeting_enabled = config.get("tts", {}).get("greeting", {}).get("enabled", False)
    
    def cog_unload(self):
        """Cogアンロード時のクリーンアップ"""
        asyncio.create_task(self.tts_manager.cleanup())
    
    async def play_audio_from_bytes(self, voice_client: discord.VoiceClient, audio_data: bytes):
        """バイト配列から音声を再生"""
        try:
            # 一時ファイルを使わずにメモリから直接再生
            audio_io = io.BytesIO(audio_data)
            
            # FFmpegを使用して音声を再生
            source = FFmpegPCMAudio(
                audio_io,
                pipe=True,
                before_options='-f wav',
                options='-vn'
            )
            
            if not voice_client.is_playing():
                voice_client.play(source)
                
                # 再生完了まで待機（最大10秒）
                timeout = 10
                while voice_client.is_playing() and timeout > 0:
                    await asyncio.sleep(0.1)
                    timeout -= 0.1
                    
        except Exception as e:
            self.logger.error(f"Failed to play audio: {e}")
    
    async def speak_greeting(self, voice_client: discord.VoiceClient, member_name: str, greeting_type: str):
        """挨拶音声を生成・再生"""
        if not self.greeting_enabled:
            return
        
        try:
            greeting_config = self.config.get("tts", {}).get("greeting", {})
            
            if greeting_type == "join":
                message = f"{member_name}{greeting_config.get('join_message', 'さん、こんちゃ！')}"
            elif greeting_type == "leave":
                message = f"{member_name}{greeting_config.get('leave_message', 'さん、またね！')}"
            else:
                return
            
            # 音声生成
            audio_data = await self.tts_manager.generate_speech(
                text=message,
                model_id=greeting_config.get("model_id", "default"),
                speaker_id=greeting_config.get("speaker_id", 0),
                style=greeting_config.get("style", "Neutral")
            )
            
            if audio_data:
                await self.play_audio_from_bytes(voice_client, audio_data)
                self.logger.info(f"Played greeting: {message}")
            else:
                self.logger.warning(f"Failed to generate greeting audio: {message}")
                
        except Exception as e:
            self.logger.error(f"Failed to speak greeting: {e}")
    
    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """ボイスステート変更時の挨拶処理"""
        if member.bot:  # ボット自身の変更は無視
            return
        
        guild = member.guild
        voice_client = guild.voice_client
        
        if not voice_client or not voice_client.is_connected():
            return
        
        # ボットと同じチャンネルでの変更のみ処理
        bot_channel = voice_client.channel
        
        # ユーザーがボットのいるチャンネルに参加した場合
        if before.channel != bot_channel and after.channel == bot_channel:
            await asyncio.sleep(1)  # 接続安定化のため少し待機
            await self.speak_greeting(voice_client, member.display_name, "join")
        
        # ユーザーがボットのいるチャンネルから退出した場合
        elif before.channel == bot_channel and after.channel != bot_channel:
            await self.speak_greeting(voice_client, member.display_name, "leave")
    
    async def generate_and_play_tts(self, voice_client: discord.VoiceClient, text: str, **kwargs):
        """TTSを生成して再生（汎用メソッド）"""
        try:
            audio_data = await self.tts_manager.generate_speech(text, **kwargs)
            if audio_data:
                await self.play_audio_from_bytes(voice_client, audio_data)
                return True
            return False
        except Exception as e:
            self.logger.error(f"Failed to generate and play TTS: {e}")
            return False


async def setup(bot: commands.Bot, config: Dict[str, Any]):
    """Cogのセットアップ"""
    await bot.add_cog(TTSCog(bot, config))