"""
TTSCog v2 - シンプルなTTS読み上げ機能
- StyleBertVITS2による音声合成
- チャットメッセージ読み上げ
- 読み上げON/OFF切り替え
"""

import asyncio
import logging
from typing import Dict, Set

import discord
from discord.ext import commands

from utils.tts_client import TTSClientV2

logger = logging.getLogger(__name__)

class TTSCogV2(commands.Cog):
    """TTS読み上げCog"""
    
    def __init__(self, bot):
        self.bot = bot
        self.config = bot.config.get('tts', {})
        
        # TTS機能が有効かチェック
        self.enabled = self.config.get('enabled', True)
        
        # ギルド別読み上げ状態管理
        self.reading_enabled: Dict[int, bool] = {}  # guild_id: enabled
        
        # TTSクライアント
        self.tts_client = None
        if self.enabled:
            self.tts_client = TTSClientV2(self.config)
        
        logger.info(f"TTSCog v2 initialized - Enabled: {self.enabled}")
    
    async def cog_load(self):
        """Cog読み込み時の処理"""
        if self.tts_client:
            await self.tts_client.start()
    
    def cog_unload(self):
        """Cog終了時の処理"""
        if self.tts_client:
            # 非同期処理なのでタスクとして実行
            import asyncio
            asyncio.create_task(self.tts_client.close())
        logger.info("TTSCog v2 unloading...")
    
    @discord.slash_command(name="reading", description="読み上げ機能のON/OFF切り替え")
    async def reading_command(self, ctx: discord.ApplicationContext, 
                            enabled: discord.Option(bool, "読み上げを有効にするか", required=True)):
        """読み上げON/OFFコマンド"""
        await ctx.defer(ephemeral=True)
        
        try:
            if not self.enabled:
                await ctx.followup.send("❌ TTS機能が無効になっています", ephemeral=True)
                return
            
            guild_id = ctx.guild.id
            self.reading_enabled[guild_id] = enabled
            
            status = "有効" if enabled else "無効"
            await ctx.followup.send(f"✅ 読み上げ機能を{status}にしました", ephemeral=True)
            
            logger.info(f"Reading {status} for guild {ctx.guild.name}")
            
        except Exception as e:
            logger.error(f"Reading command error: {e}", exc_info=True)
            await ctx.followup.send("❌ エラーが発生しました", ephemeral=True)
    
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """メッセージ受信時の読み上げ処理"""
        # 基本チェック
        if not self.enabled:
            return
        
        if message.author.bot:
            return
        
        if not message.guild:
            return
        
        guild_id = message.guild.id
        
        # 読み上げが無効の場合
        if not self.reading_enabled.get(guild_id, False):
            return
        
        # VoiceClientが接続していない場合
        voice_cog = self.bot.get_cog('VoiceCogV2')
        if not voice_cog:
            return
        
        voice_client = voice_cog.get_voice_client(guild_id)
        if not voice_client or not voice_client.is_connected():
            return
        
        # メッセージ読み上げ処理
        await self.read_message(message, voice_client)
    
    async def read_message(self, message: discord.Message, voice_client: discord.VoiceClient):
        """メッセージを読み上げ"""
        try:
            # テキスト前処理
            text = self.tts_client.preprocess_text(message.content)
            
            if not text:
                return
            
            # 辞書適用
            dict_cog = self.bot.get_cog('DictionaryCogV2')
            if dict_cog:
                text = dict_cog.apply_dictionary(text)
            
            logger.debug(f"Reading message: {text[:50]}...")
            
            # 音声合成
            audio_source = await self.tts_client.synthesize_speech(text)
            
            if not audio_source:
                logger.warning("Failed to synthesize speech")
                return
            
            # 既に再生中の場合は停止
            if voice_client.is_playing():
                voice_client.stop()
            
            # 音声再生
            voice_client.play(audio_source)
            
            # 再生完了まで待機（最大30秒）
            timeout = 30
            while voice_client.is_playing() and timeout > 0:
                await asyncio.sleep(0.1)
                timeout -= 0.1
            
        except Exception as e:
            logger.error(f"Read message error: {e}", exc_info=True)
    
    def is_reading_enabled(self, guild_id: int) -> bool:
        """指定ギルドで読み上げが有効かチェック"""
        return self.reading_enabled.get(guild_id, False)

def setup(bot):
    bot.add_cog(TTSCogV2(bot))