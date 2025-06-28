"""
TTS（Text-to-Speech）機能Cog
- 挨拶機能（参加・退出時の音声再生）
- TTSキャッシュ管理
- Style-Bert-VITS2統合
"""

import asyncio
import logging
import io
import random
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
        
        # 初期化時の設定値をログ出力
        self.logger.info(f"TTS: Initializing with greeting_enabled: {self.greeting_enabled}")
        self.logger.info(f"TTS: Config tts section: {config.get('tts', {})}")
    
    async def rate_limit_delay(self):
        """レート制限対策の遅延"""
        delay = random.uniform(*self.config["bot"]["rate_limit_delay"])
        await asyncio.sleep(delay)
    
    def cog_unload(self):
        """Cogアンロード時のクリーンアップ"""
        asyncio.create_task(self.tts_manager.cleanup())
    
    async def play_audio_from_bytes(self, voice_client: discord.VoiceClient, audio_data: bytes):
        """バイト配列から音声を再生"""
        try:
            import tempfile
            import os
            
            # 一時ファイルに音声データを保存
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
                temp_file.write(audio_data)
                temp_path = temp_file.name
            
            try:
                # FFmpegを使用して音声を再生
                source = FFmpegPCMAudio(temp_path)
                
                if not voice_client.is_playing():
                    voice_client.play(source)
                    
                    # 再生完了まで待機（最大10秒）
                    timeout = 10
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
            self.logger.error(f"Failed to play audio: {e}")
    
    async def speak_greeting(self, voice_client: discord.VoiceClient, member: discord.Member, greeting_type: str):
        """挨拶音声を生成・再生（ユーザー個別設定対応）"""
        if not self.greeting_enabled:
            return
        
        try:
            greeting_config = self.config.get("tts", {}).get("greeting", {})
            
            # ユーザー個別の挨拶設定を取得
            user_settings_cog = self.bot.get_cog("UserSettingsCog")
            if user_settings_cog:
                user_greeting_settings = user_settings_cog.get_user_greeting_settings(member.id)
                user_tts_settings = user_settings_cog.get_user_tts_settings(member.id)
                
                # ユーザーが挨拶を無効にしている場合はスキップ
                if not user_greeting_settings.get("enabled", True):
                    return
                
                # カスタム挨拶メッセージの取得
                if greeting_type == "join":
                    custom_message = user_greeting_settings.get("custom_join")
                    default_message = greeting_config.get('join_message', 'さん、こんちゃ！')
                    message = custom_message if custom_message else f"{member.display_name}{default_message}"
                elif greeting_type == "leave":
                    custom_message = user_greeting_settings.get("custom_leave")
                    default_message = greeting_config.get('leave_message', 'さん、またね！')
                    message = custom_message if custom_message else f"{member.display_name}{default_message}"
                else:
                    return
            else:
                # フォールバック：デフォルト設定
                if greeting_type == "join":
                    message = f"{member.display_name}{greeting_config.get('join_message', 'さん、こんちゃ！')}"
                elif greeting_type == "leave":
                    message = f"{member.display_name}{greeting_config.get('leave_message', 'さん、またね！')}"
                else:
                    return
                
                user_tts_settings = {
                    "model_id": greeting_config.get("model_id", 0),
                    "speaker_id": greeting_config.get("speaker_id", 0),
                    "style": greeting_config.get("style", "Neutral")
                }
            
            # ユーザー個別のTTS設定で音声生成
            audio_data = await self.tts_manager.generate_speech(
                text=message,
                model_id=user_tts_settings.get("model_id", 0),
                speaker_id=user_tts_settings.get("speaker_id", 0),
                style=user_tts_settings.get("style", "Neutral")
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
        
        self.logger.info(f"TTS: Voice state update for {member.display_name} in {guild.name}")
        self.logger.info(f"TTS: Voice client connected: {voice_client is not None and voice_client.is_connected()}")
        self.logger.info(f"TTS: Greeting enabled: {self.greeting_enabled}")
        
        if not voice_client or not voice_client.is_connected():
            self.logger.warning(f"TTS: No voice client or not connected for {guild.name}")
            return
        
        # ボットと同じチャンネルでの変更のみ処理
        bot_channel = voice_client.channel
        self.logger.info(f"TTS: Bot channel: {bot_channel.name if bot_channel else 'None'}")
        self.logger.info(f"TTS: Before channel: {before.channel.name if before.channel else 'None'}")
        self.logger.info(f"TTS: After channel: {after.channel.name if after.channel else 'None'}")
        
        # ユーザーがボットのいるチャンネルに参加した場合
        if before.channel != bot_channel and after.channel == bot_channel:
            self.logger.info(f"TTS: User {member.display_name} joined bot channel {bot_channel.name}")
            await asyncio.sleep(1)  # 接続安定化のため少し待機
            await self.speak_greeting(voice_client, member, "join")
        
        # ユーザーがボットのいるチャンネルから退出した場合
        elif before.channel == bot_channel and after.channel != bot_channel:
            self.logger.info(f"TTS: User {member.display_name} left bot channel {bot_channel.name}")
            await self.speak_greeting(voice_client, member, "leave")
    
    async def handle_bot_joined_with_user(self, guild: discord.Guild, member: discord.Member):
        """ボットがVCに参加した際、既にいるユーザーに対する処理"""
        try:
            voice_client = guild.voice_client
            if voice_client and voice_client.is_connected():
                self.logger.info(f"TTS: Bot joined, greeting user {member.display_name}")
                await self.speak_greeting(voice_client, member, "join")
            else:
                self.logger.warning(f"TTS: No voice client when trying to greet {member.display_name}")
        except Exception as e:
            self.logger.error(f"TTS: Failed to handle bot joined with user: {e}")
    
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
    
    @discord.slash_command(name="tts_models", description="利用可能なTTSモデル一覧を表示します")
    async def tts_models_command(self, ctx: discord.ApplicationContext):
        """利用可能なTTSモデル一覧を表示"""
        await self.rate_limit_delay()
        
        try:
            models = await self.tts_manager.get_available_models()
            
            if models:
                model_text = self.tts_manager.format_models_for_display(models)
                
                embed = discord.Embed(
                    title="🎤 TTS モデル一覧",
                    description=model_text,
                    color=discord.Color.blue()
                )
                embed.set_footer(text="詳細は /tts_speakers <model_id> で確認できます")
                
                await ctx.respond(embed=embed, ephemeral=True)
            else:
                await ctx.respond(
                    "❌ TTSモデル情報を取得できませんでした。APIサーバーが起動していることを確認してください。",
                    ephemeral=True
                )
                
        except Exception as e:
            self.logger.error(f"Failed to get TTS models: {e}")
            await ctx.respond(
                "❌ モデル一覧の取得中にエラーが発生しました。",
                ephemeral=True
            )
    
    @discord.slash_command(name="tts_speakers", description="指定モデルの話者一覧を表示します")
    async def tts_speakers_command(
        self, 
        ctx: discord.ApplicationContext,
        model_id: discord.Option(int, "モデルID", min_value=0)
    ):
        """指定モデルの話者一覧を表示"""
        await self.rate_limit_delay()
        
        try:
            # 全モデル情報を取得してから指定モデルの情報を抽出
            models = await self.tts_manager.get_available_models()
            
            if models and str(model_id) in models:
                model_info = models[str(model_id)]
                speaker_text = self.tts_manager.format_speakers_for_display(model_id, model_info)
                
                embed = discord.Embed(
                    title=f"🗣️ モデル {model_id} の詳細",
                    description=speaker_text,
                    color=discord.Color.green()
                )
                embed.set_footer(text="話者IDとスタイルは読み上げ設定で使用できます")
                
                await ctx.respond(embed=embed, ephemeral=True)
            else:
                await ctx.respond(
                    f"❌ モデル {model_id} の情報を取得できませんでした。",
                    ephemeral=True
                )
                
        except Exception as e:
            self.logger.error(f"Failed to get TTS speakers: {e}")
            await ctx.respond(
                "❌ 話者一覧の取得中にエラーが発生しました。",
                ephemeral=True
            )
    
    @discord.slash_command(name="tts_test", description="指定設定でTTSをテストします")
    async def tts_test_command(
        self, 
        ctx: discord.ApplicationContext,
        text: discord.Option(str, "テスト用テキスト", max_length=50, default="こんにちは、これはテストです"),
        model_id: discord.Option(int, "モデルID", min_value=0, default=0),
        speaker_id: discord.Option(int, "話者ID", min_value=0, default=0),
        style: discord.Option(str, "スタイル", default="Neutral")
    ):
        """指定設定でTTSをテスト"""
        await self.rate_limit_delay()
        
        # ボットがVCに接続しているか確認
        if not ctx.guild.voice_client:
            await ctx.respond(
                "❌ ボットがボイスチャンネルに接続していません。先に /join コマンドで参加してください。",
                ephemeral=True
            )
            return
        
        try:
            await ctx.response.defer(ephemeral=True)
            
            # TTS生成・再生
            success = await self.generate_and_play_tts(
                ctx.guild.voice_client,
                text,
                model_id=model_id,
                speaker_id=speaker_id,
                style=style
            )
            
            if success:
                await ctx.followup.send(
                    f"✅ TTSテスト完了\n"
                    f"**テキスト**: {text}\n"
                    f"**モデルID**: {model_id}\n"
                    f"**話者ID**: {speaker_id}\n"
                    f"**スタイル**: {style}",
                    ephemeral=True
                )
            else:
                await ctx.followup.send(
                    "❌ TTSの生成または再生に失敗しました。",
                    ephemeral=True
                )
                
        except Exception as e:
            self.logger.error(f"Failed to test TTS: {e}")
            await ctx.followup.send(
                "❌ TTSテスト中にエラーが発生しました。",
                ephemeral=True
            )


def setup(bot):
    """Cogのセットアップ"""
    bot.add_cog(TTSCog(bot, bot.config))