#!/usr/bin/env python3
"""
yomiageBotEx - 軽量版（py-cord + discord.sinks.WaveSink）
前回のyomiage-botコードを参考にした実装
"""

import os
import io
import asyncio
import logging
import time
import wave
from datetime import datetime, timedelta
from typing import Dict, Any

import discord
from discord.sinks import WaveSink
import yaml
from dotenv import load_dotenv

# 環境変数の読み込み
load_dotenv()

# ロギング設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/yomiage.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ディレクトリ作成
os.makedirs("logs", exist_ok=True)
os.makedirs("recordings", exist_ok=True)

# 設定ファイル読み込み
def load_config():
    try:
        with open("config.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        # デフォルト設定
        return {
            "bot": {
                "auto_join": True,
                "auto_leave": True
            },
            "recording": {
                "cleanup_hours": 1,
                "max_duration": 300
            }
        }

config = load_config()

# Bot設定
intents = discord.Intents.all()
bot = discord.Bot(intents=intents)

# グローバル変数
connections: Dict[int, discord.VoiceClient] = {}
user_audio_buffers: Dict[int, list] = {}
BUFFER_EXPIRATION = 900  # 15分

@bot.event
async def on_ready():
    """Bot準備完了時のイベント"""
    logger.info(f"Bot is ready! Logged in as {bot.user} (ID: {bot.user.id})")
    logger.info(f"Connected to {len(bot.guilds)} guild(s)")
    logger.info("Using py-cord with discord.sinks.WaveSink")
    
    # スラッシュコマンドの確認と同期
    try:
        # py-cordでは自動同期されるが、明示的に同期を確認
        pending_commands = [cmd for cmd in bot.commands if hasattr(cmd, 'name')]
        logger.info(f"Registered commands: {[cmd.name for cmd in pending_commands]}")
        
        # 手動同期を試行
        synced = await bot.sync_commands()
        logger.info(f"Synced {len(synced) if synced else 0} slash commands")
        
        if synced:
            logger.info(f"Command names: {[cmd.name for cmd in synced]}")
        else:
            logger.warning("No commands were synced - this might be normal for py-cord")
            
    except Exception as e:
        logger.error(f"Command sync failed: {e}", exc_info=True)
    
    # ステータス設定
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.listening,
            name="実際の音声録音対応 | /join"
        )
    )

@bot.event
async def on_application_command_error(ctx, error):
    """スラッシュコマンドエラー"""
    logger.error(f"Slash command error in {ctx.command}: {error}", exc_info=True)
    await ctx.respond(f"❌ エラーが発生しました: {str(error)}", ephemeral=True)

@bot.event
async def on_voice_state_update(member, before, after):
    """ボイスチャンネルの参加・退出イベント"""
    if member.bot:
        return
    
    guild = member.guild
    logger.info(f"Voice state update: {member.display_name} in {guild.name}")
    logger.info(f"Before: {before.channel.name if before.channel else None}")
    logger.info(f"After: {after.channel.name if after.channel else None}")
    
    # ユーザーがVCに参加した場合（自動参加）
    if (before.channel is None and after.channel is not None and 
        config["bot"]["auto_join"]):
        
        logger.info(f"Auto-join triggered for {member.display_name} -> {after.channel.name}")
        
        if guild.id not in connections or not guild.voice_client:
            try:
                logger.info(f"Attempting to connect to {after.channel.name}")
                vc = await after.channel.connect()
                await start_recording(vc, guild.id)
                logger.info(f"Auto-joined: {after.channel.name} in {guild.name}")
            except Exception as e:
                logger.error(f"Auto-join failed: {e}", exc_info=True)
        else:
            logger.info("Bot already connected, skipping auto-join")
    
    # ユーザーがVCから退出した場合（自動退出）
    if (before.channel is not None and after.channel is None and 
        config["bot"]["auto_leave"]):
        
        logger.info(f"Auto-leave triggered for {member.display_name} <- {before.channel.name}")
        
        if guild.voice_client and before.channel == guild.voice_client.channel:
            # チャンネルが空になったかチェック
            remaining_members = len(before.channel.members)
            logger.info(f"Remaining members in {before.channel.name}: {remaining_members}")
            
            if remaining_members <= 1:  # ボット自身のみ
                try:
                    await stop_recording(guild.id)
                    await guild.voice_client.disconnect()
                    logger.info(f"Auto-left: {before.channel.name} in {guild.name}")
                except Exception as e:
                    logger.error(f"Auto-leave failed: {e}", exc_info=True)

async def start_recording(vc: discord.VoiceClient, guild_id: int):
    """録音開始"""
    try:
        sink = WaveSink()
        connections[guild_id] = vc
        vc.start_recording(sink, finished_callback, guild_id)
        logger.info(f"Started recording for guild {guild_id}")
    except Exception as e:
        logger.error(f"Failed to start recording: {e}")

async def stop_recording(guild_id: int):
    """録音停止"""
    try:
        if guild_id in connections:
            vc = connections[guild_id]
            if vc.recording:
                vc.stop_recording()
            del connections[guild_id]
            logger.info(f"Stopped recording for guild {guild_id}")
    except Exception as e:
        logger.error(f"Failed to stop recording: {e}")

async def finished_callback(sink: WaveSink, guild_id: int):
    """録音完了時のコールバック"""
    try:
        for user_id, audio in sink.audio_data.items():
            if audio.file:
                audio.file.seek(0)
                audio_data = audio.file.read()
                
                if audio_data:
                    user_audio_buffer = io.BytesIO(audio_data)
                    
                    # バッファに追加
                    if user_id not in user_audio_buffers:
                        user_audio_buffers[user_id] = []
                    user_audio_buffers[user_id].append((user_audio_buffer, time.time()))
                    
                    logger.debug(f"Added audio buffer for user {user_id}")
                    
    except Exception as e:
        logger.error(f"Error in finished_callback: {e}")

async def clean_old_buffers():
    """古いバッファを削除"""
    current_time = time.time()
    for user_id in list(user_audio_buffers.keys()):
        user_audio_buffers[user_id] = [
            (buffer, timestamp) for buffer, timestamp in user_audio_buffers[user_id]
            if current_time - timestamp <= BUFFER_EXPIRATION
        ]
        
        if not user_audio_buffers[user_id]:
            del user_audio_buffers[user_id]

@bot.slash_command(name="join", description="ボイスチャンネルに参加します")
async def join_command(ctx: discord.ApplicationContext):
    """VCに参加"""
    logger.info(f"🎯 /join command called by {ctx.author} in {ctx.guild.name}")
    
    if not ctx.author.voice:
        await ctx.respond("❌ ボイスチャンネルに接続してください。", ephemeral=True)
        return
    
    channel = ctx.author.voice.channel
    logger.info(f"Target channel: {channel.name}")
    
    # 既に接続している場合
    if ctx.guild.voice_client:
        if ctx.guild.voice_client.channel == channel:
            await ctx.respond(f"✅ 既に {channel.name} に接続しています。")
            return
    
    try:
        # 既存の接続があれば切断
        if ctx.guild.voice_client:
            await stop_recording(ctx.guild.id)
            await ctx.guild.voice_client.disconnect()
        
        # 新規接続
        vc = await channel.connect()
        await start_recording(vc, ctx.guild.id)
        
        await ctx.respond(f"✅ {channel.name} に接続し、録音を開始しました！")
        logger.info(f"Successfully connected to {channel.name}")
        
    except Exception as e:
        await ctx.respond("❌ 接続に失敗しました。")
        logger.error(f"Failed to connect: {e}", exc_info=True)

@bot.slash_command(name="leave", description="ボイスチャンネルから退出します")
async def leave_command(ctx: discord.ApplicationContext):
    """VCから退出"""
    if not ctx.guild.voice_client:
        await ctx.respond("❌ ボイスチャンネルに接続していません。", ephemeral=True)
        return
    
    try:
        channel_name = ctx.guild.voice_client.channel.name
        await stop_recording(ctx.guild.id)
        await ctx.guild.voice_client.disconnect()
        
        await ctx.respond(f"👋 {channel_name} から退出しました。")
        logger.info(f"Disconnected from {channel_name}")
        
    except Exception as e:
        await ctx.respond("❌ 退出に失敗しました。")
        logger.error(f"Failed to disconnect: {e}")

@bot.slash_command(name="replay", description="最近の音声を録音ファイルとして投稿します")
async def replay_command(
    ctx: discord.ApplicationContext,
    duration: discord.Option(float, "録音する時間（秒）", default=30.0, min_value=5.0, max_value=300.0) = 30.0,
    user: discord.Option(discord.Member, "対象ユーザー（省略時は全体）", required=False) = None
):
    """録音をリプレイ"""
    await ctx.defer()
    
    if ctx.guild.id not in connections:
        await ctx.respond("⚠️ 現在録音中ではありません。", ephemeral=True)
        return
    
    try:
        # 録音を一時停止・再開
        vc = connections[ctx.guild.id]
        vc.stop_recording()
        await asyncio.sleep(1)
        
        # バッファクリーンアップ
        await clean_old_buffers()
        
        if user:
            # 特定ユーザーの音声
            if user.id not in user_audio_buffers:
                await ctx.respond(f"⚠️ {user.mention} の音声データが見つかりません。", ephemeral=True)
                return
            
            # 最新のバッファを取得
            sorted_buffers = sorted(user_audio_buffers[user.id], key=lambda x: x[1])
            if not sorted_buffers:
                await ctx.respond(f"⚠️ {user.mention} の音声データがありません。", ephemeral=True)
                return
            
            # 最新のバッファを結合
            audio_buffer = io.BytesIO()
            for buffer, timestamp in sorted_buffers[-5:]:  # 最新5個
                buffer.seek(0)
                audio_buffer.write(buffer.read())
            
            audio_buffer.seek(0)
            
            # WAVファイルとして保存
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"recording_{user.id}_{timestamp}.wav"
            
            await ctx.respond(
                f"🎵 {user.mention} の録音です（{duration}秒分）",
                file=discord.File(audio_buffer, filename=filename)
            )
            
        else:
            await ctx.respond("⚠️ ユーザーを指定してください。全体録音は未実装です。", ephemeral=True)
        
        # 録音再開
        await start_recording(vc, ctx.guild.id)
        
    except Exception as e:
        await ctx.respond(f"⚠️ リプレイに失敗しました: {str(e)}", ephemeral=True)
        logger.error(f"Replay failed: {e}", exc_info=True)

def main():
    """メイン実行関数"""
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        logger.error("DISCORD_TOKEN not found")
        print("エラー: .envファイルにDISCORD_TOKENを設定してください。")
        return
    
    try:
        logger.info("Starting bot...")
        bot.run(token)
    except Exception as e:
        logger.error(f"Bot failed to start: {e}")

if __name__ == "__main__":
    main()