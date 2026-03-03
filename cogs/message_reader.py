"""
メッセージ読み上げ機能Cog
"""

import asyncio
import logging
import re
import json
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
        self.dictionary_manager = self._resolve_dictionary_manager()
        self.last_voice_channel: Dict[int, int] = {}
        self.sessions_file = Path("sessions.json")
        self.guild_queues: Dict[int, asyncio.Queue] = {}
        self.queue_workers: Dict[int, asyncio.Task] = {}
        
        # 読み上げ設定
        self.reading_enabled = config.get("message_reading", {}).get("enabled", True)
        self.max_length = config.get("message_reading", {}).get("max_length", 100)
        self.ignore_prefixes = config.get("message_reading", {}).get("ignore_prefixes", ["!", "/", ".", "?", "`", ";"])
        self.ignore_bots = config.get("message_reading", {}).get("ignore_bots", True)
        self.handshake_wait_timeout = float(config.get("message_reading", {}).get("handshake_wait_timeout", 8.0))
        self.handshake_retry_interval = float(config.get("message_reading", {}).get("handshake_retry_interval", 0.5))
        
        # ギルドごとの読み上げ有効/無効状態
        self.guild_reading_enabled: Dict[int, bool] = {}
        self.guild_auto_paused: Dict[int, bool] = {}
        self.guild_auto_paused: Dict[int, bool] = {}
        
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
    
    def _resolve_dictionary_manager(self) -> DictionaryManager:
        manager = getattr(self.bot, "dictionary_manager", None)
        if manager is None:
            manager = DictionaryManager(self.config)
            try:
                setattr(self.bot, "dictionary_manager", manager)
            except AttributeError:
                self.logger.warning("MessageReader: Could not attach dictionary manager to bot instance")
        return manager

    def _is_auto_paused(self, guild_id: int) -> bool:
        return self.guild_auto_paused.get(guild_id, False)

    def _clear_auto_pause_if_disconnected(self, guild_id: int):
        if not self._is_auto_paused(guild_id):
            return
        guild_lookup = getattr(self.bot, "get_guild", None)
        guild = guild_lookup(guild_id) if guild_lookup else None
        voice_client = getattr(guild, "voice_client", None) if guild else None
        if not voice_client or not voice_client.is_connected():
            self.guild_auto_paused.pop(guild_id, None)

    def _set_auto_pause_state(self, guild_id: int, should_pause: bool, reason: str):
        previous = self.guild_auto_paused.get(guild_id, False)
        if should_pause:
            if not previous:
                self.guild_auto_paused[guild_id] = True
                self.logger.info("MessageReader: Auto-paused reading for guild %s (%s)", guild_id, reason)
        else:
            if previous:
                self.logger.info("MessageReader: Auto-resumed reading for guild %s (%s)", guild_id, reason)
            self.guild_auto_paused.pop(guild_id, None)

    def _ensure_listeners_or_pause(self, guild_id: int, voice_client: discord.VoiceClient, context: str) -> bool:
        has_listeners = self._has_non_bot_listeners(voice_client)
        self._set_auto_pause_state(guild_id, not has_listeners, context)
        return has_listeners

    def _evaluate_auto_pause_for_guild(self, guild: discord.Guild, context: str):
        voice_client = getattr(guild, "voice_client", None)
        channel = getattr(voice_client, "channel", None) if voice_client else None
        if not voice_client or not channel:
            self._set_auto_pause_state(guild.id, False, context)
            return
        has_listeners = self._has_non_bot_listeners(voice_client)
        self._set_auto_pause_state(guild.id, not has_listeners, context)

    def cog_unload(self):
        """Cogアンロード時のクリーンアップ"""
        asyncio.create_task(self.tts_manager.cleanup())
    
    def is_reading_enabled(self, guild_id: int) -> bool:
        """ギルドで読み上げが有効かチェック"""
        if not self.reading_enabled:
            return False
        if not self.guild_reading_enabled.get(guild_id, True):
            return False
        self._clear_auto_pause_if_disconnected(guild_id)
        if self._is_auto_paused(guild_id):
            return False
        return True
    
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
            if self._is_auto_paused(message.guild.id):
                self.logger.debug(
                    "MessageReader: Auto-paused reading in guild %s due to empty voice channel",
                    message.guild.name,
                )
            return False

        return True

    @staticmethod
    def _has_non_bot_listeners(voice_client: discord.VoiceClient) -> bool:
        """VCにBot以外の参加者がいるか判定"""
        if not voice_client:
            return False
        channel = getattr(voice_client, "channel", None)
        if not channel:
            return False
        members = getattr(channel, "members", None)
        if not members:
            return False
        for member in members:
            if not getattr(member, "bot", False):
                return True
        return False

    @staticmethod
    def _channel_has_non_bot_members(channel) -> bool:
        members = getattr(channel, "members", None)
        if not members:
            return False
        for member in members:
            if not getattr(member, "bot", False):
                return True
        return False
    
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
            block_status_getter = getattr(self.bot, "get_voice_connect_block_status", None)
            if callable(block_status_getter):
                blocked, remaining, reason = block_status_getter(guild.id)
                if blocked:
                    self.logger.info(
                        "MessageReader: Skip auto-reconnect for %s due to voice cooldown (%.1fs): %s",
                        guild.name,
                        remaining,
                        reason,
                    )
                    return False

            self.logger.info(f"MessageReader: Attempting auto-reconnect in {guild.name}")

            existing_client = guild.voice_client

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
                fallback_channel = self._find_fallback_channel(guild)
                if fallback_channel:
                    target_channel = fallback_channel
                    self.logger.info(
                        "MessageReader: Using fallback channel %s in %s for auto-reconnect",
                        target_channel.name,
                        guild.name,
                    )
                else:
                    self.logger.warning(f"MessageReader: No voice channels with users found in {guild.name}")
                    self._set_auto_pause_state(guild.id, True, "auto-reconnect skipped due to no listeners")
                    return False

            if not self._channel_has_non_bot_members(target_channel):
                self.logger.warning(
                    "MessageReader: Target channel %s has no non-bot listeners, skipping auto-reconnect",
                    target_channel.name,
                )
                self._set_auto_pause_state(guild.id, True, "auto-reconnect target had no listeners")
                return False

            # 既存の接続をクリーンアップ（対象チャンネルが判明してから実施）
            if existing_client:
                # すでにターゲットチャンネルに接続済みであれば再利用を試みる
                try:
                    if existing_client.channel == target_channel:
                        if await self._wait_for_existing_client(existing_client, target_channel):
                            self._set_auto_pause_state(guild.id, False, "existing voice client reused")
                            return True

                except Exception as state_error:
                    self.logger.debug(f"MessageReader: Failed to inspect existing client state: {state_error}")

                self.logger.info(f"MessageReader: Cleaning up existing voice client (connected: {existing_client.is_connected()})")
                try:
                    await existing_client.disconnect(force=True)
                    await asyncio.sleep(1)  # 切断完了を待つ
                except Exception as e:
                    self.logger.warning(f"MessageReader: Failed to disconnect existing client: {e}")
            
            # connect_voice_safely が利用可能なら優先して使用
            connect_callable = getattr(self.bot, "connect_voice_safely", None)
            try:
                if connect_callable:
                    voice_client = await connect_callable(target_channel)
                else:
                    voice_client = await target_channel.connect(reconnect=False, timeout=15.0)

                await asyncio.sleep(1)  # 接続安定化待機
                
                if voice_client and voice_client.is_connected():
                    self.logger.info(f"MessageReader: Auto-reconnect successful to {target_channel.name}")
                    if target_channel:
                        self.last_voice_channel[guild.id] = target_channel.id
                    self._set_auto_pause_state(guild.id, False, "auto-reconnect succeeded")
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
                        voice_client = await target_channel.connect(reconnect=False, timeout=15.0)
                    await asyncio.sleep(1)
                    if voice_client and voice_client.is_connected():
                        self.logger.info(f"MessageReader: Auto-reconnect successful to {target_channel.name} after retry")
                        if target_channel:
                            self.last_voice_channel[guild.id] = target_channel.id
                        self._set_auto_pause_state(guild.id, False, "auto-reconnect retry succeeded")
                        return True
                except Exception as retry_error:
                    self.logger.error(f"MessageReader: Retry connect failed: {retry_error}")
                return False
            except Exception as connect_error:
                if "Voice connect cooldown active" in str(connect_error):
                    self.logger.info(
                        "MessageReader: Voice cooldown active while reconnecting in %s: %s",
                        guild.name,
                        connect_error,
                    )
                    return False
                self.logger.error(f"MessageReader: Direct connect failed: {connect_error}")
                return False
                
        except Exception as e:
            self.logger.error(f"MessageReader: Auto-reconnect exception: {e}")
            return False

    async def _wait_for_existing_client(self, existing_client, target_channel):
        """既存のボイスクライアントが接続完了するのを待機"""
        if existing_client.is_connected():
            self.logger.info("MessageReader: Existing voice client already connected to target channel")
            return True

        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.handshake_wait_timeout
        attempts = 0

        while loop.time() < deadline:
            attempts += 1
            ws = getattr(existing_client, "ws", None)
            ws_open = bool(getattr(ws, "open", False))
            self.logger.debug(
                "MessageReader: Waiting for existing voice client handshake (attempt %s, ws_open=%s)",
                attempts,
                ws_open,
            )

            if existing_client.is_connected():
                self.logger.info(
                    "MessageReader: Existing voice client finished handshake for channel %s after %s attempts",
                    target_channel.name,
                    attempts,
                )
                return True

            await asyncio.sleep(self.handshake_retry_interval)

            if existing_client.is_connected():
                self.logger.info(
                    "MessageReader: Existing voice client finished handshake for channel %s after %s attempts",
                    target_channel.name,
                    attempts,
                )
                return True

        self.logger.warning(
            "MessageReader: Existing voice client did not finish handshake within %.1fs, proceeding to reconnect",
            self.handshake_wait_timeout,
        )
        return False

    def _find_fallback_channel(self, guild: discord.Guild):
        """最後に接続したチャンネルや保存済みセッションから候補を取得"""
        channel_id = self.last_voice_channel.get(guild.id)
        if channel_id:
            channel = guild.get_channel(channel_id)
            if channel:
                return channel
        if self.sessions_file.exists():
            try:
                with open(self.sessions_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                saved_id = data.get(str(guild.id)) or data.get(guild.id)
                if saved_id:
                    channel = guild.get_channel(saved_id)
                    if channel:
                        return channel
            except Exception as e:
                self.logger.debug(f"MessageReader: Failed to load fallback channel info: {e}")
        return None

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """VCの参加状況に応じて自動停止状態を更新"""
        guild = getattr(member, "guild", None)
        if not guild:
            return
        voice_client = getattr(guild, "voice_client", None)
        if not voice_client:
            self._set_auto_pause_state(guild.id, False, "voice client disconnected")
            return
        channel = getattr(voice_client, "channel", None)
        if not channel:
            self._set_auto_pause_state(guild.id, False, "voice client channel missing")
            return

        relevant = False
        before_channel = getattr(before, "channel", None)
        after_channel = getattr(after, "channel", None)
        if before_channel and before_channel.id == channel.id:
            relevant = True
        if after_channel and after_channel.id == channel.id:
            relevant = True
        if not relevant:
            return

        has_listeners = self._has_non_bot_listeners(voice_client)
        self._set_auto_pause_state(guild.id, not has_listeners, "voice_state_update")
    
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
                self.logger.info(
                    f"MessageReader: Voice connection confirmed - channel: {voice_client.channel.name if voice_client.channel else 'Unknown'}"
                )

            self.logger.info(f"MessageReader: Bot connected to voice channel: {voice_client.channel.name}")
            if voice_client.channel:
                self.last_voice_channel[message.guild.id] = voice_client.channel.id

            if not self._ensure_listeners_or_pause(message.guild.id, voice_client, "on_message"):
                self.logger.info("MessageReader: No non-bot members in voice channel, skipping TTS queue")
                return

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
            
            self.logger.info(f"MessageReader: Queueing message from {message.author.display_name}: {processed_content[:50]}...")
            await self._enqueue_message(message.guild, processed_content, message.author.display_name)

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
            manual_state = self.guild_reading_enabled.get(guild_id, True)
            new_state = not manual_state
            
            self.guild_reading_enabled[guild_id] = new_state
            
            state_text = "有効" if new_state else "無効"
            note = ""
            if new_state and self._is_auto_paused(guild_id):
                note = "\n⚠️ 現在VCに人がいないため、自動的に読み上げが一時停止中です。"
            await ctx.respond(
                f"📢 チャット読み上げを{state_text}にしました。{note}",
                ephemeral=True
            )
            
            self.logger.info(f"MessageReader: Reading toggled to {new_state} for guild {ctx.guild.name}")
            
        except Exception as e:
            self.logger.error(f"MessageReader: Failed to toggle reading: {e}")
            await ctx.respond(
                "❌ 設定の変更に失敗しました。",
                ephemeral=True
            )

    @discord.slash_command(name="echo", description="指定テキストを音声で読み上げます（チャットには残しません）")
    async def echo_command(
        self,
        ctx: discord.ApplicationContext,
        text: discord.Option(str, "読み上げるテキスト", max_length=200),
    ):
        """任意テキストをボイスチャットで読み上げる"""
        try:
            if not ctx.guild:
                await ctx.respond("❌ ギルド内で実行してください。", ephemeral=True)
                return

            guild = ctx.guild
            voice_client = guild.voice_client
            if not voice_client or not voice_client.is_connected():
                reconnected = await self._attempt_auto_reconnect(guild)
                voice_client = guild.voice_client
                if not reconnected or not voice_client or not voice_client.is_connected():
                    await ctx.respond("❌ ボイスチャンネルに接続してから実行してください。", ephemeral=True)
                    return
            if voice_client.channel:
                self.last_voice_channel[guild.id] = voice_client.channel.id

            if not self._ensure_listeners_or_pause(guild.id, voice_client, "echo_command"):
                await ctx.respond("❌ ボイスチャンネルに参加者がいません。", ephemeral=True)
                return

            message_text = text.strip()
            if not message_text:
                await ctx.respond("❌ 読み上げるテキストを入力してください。", ephemeral=True)
                return

            if len(message_text) > self.max_length:
                message_text = message_text[: self.max_length] + "以下省略"

            processed_text = self.dictionary_manager.apply_dictionary(message_text, guild.id)

            tts_config = self.tts_manager.tts_config
            tts_settings = {
                "model_id": tts_config.get("model_id", 5),
                "speaker_id": tts_config.get("speaker_id", 0),
                "style": tts_config.get("style", "01"),
            }

            audio_data = await self.tts_manager.generate_speech(
                text=processed_text,
                model_id=tts_settings.get("model_id", 0),
                speaker_id=tts_settings.get("speaker_id", 0),
                style=tts_settings.get("style", "Neutral"),
            )

            if not audio_data:
                await ctx.respond("❌ 音声生成に失敗しました。", ephemeral=True)
                return

            await self.play_audio_from_bytes(voice_client, audio_data)
            await ctx.respond("音声を流しました", ephemeral=True)
            self.logger.info(
                "MessageReader: Echo command played %s characters for %s",
                len(processed_text),
                ctx.user.display_name if hasattr(ctx, "user") else "unknown",
            )

        except Exception as e:
            self.logger.error(f"MessageReader: Echo command failed: {e}")
            await ctx.respond("❌ 読み上げ中にエラーが発生しました。", ephemeral=True)

    async def _enqueue_message(self, guild: discord.Guild, text: str, author: str):
        queue = self.guild_queues.setdefault(guild.id, asyncio.Queue())
        await queue.put({"text": text, "author": author, "attempts": 0})
        if guild.id not in self.queue_workers or self.queue_workers[guild.id].done():
            self.queue_workers[guild.id] = asyncio.create_task(self._process_queue(guild.id))

    async def _process_queue(self, guild_id: int):
        queue = self.guild_queues.get(guild_id)
        if not queue:
            return
        while True:
            if queue.empty():
                break
            job = await queue.get()
            guild = self.bot.get_guild(guild_id)
            if not guild:
                queue.task_done()
                break
            success = await self._play_job(guild, job)
            if not success and job["attempts"] < 3:
                job["attempts"] += 1
                await queue.put(job)
                await asyncio.sleep(1.0)
            queue.task_done()
        self.queue_workers.pop(guild_id, None)

    async def _play_job(self, guild: discord.Guild, job: Dict[str, str]) -> bool:
        voice_client = await self._ensure_voice_connection(guild)
        if not voice_client:
            self.logger.warning(f"MessageReader: No voice client for guild {guild.name}, requeueing")
            return False
        if not self._ensure_listeners_or_pause(guild.id, voice_client, "_play_job"):
            self.logger.info(
                "MessageReader: Skipping queued message because voice channel %s has no non-bot members",
                voice_client.channel.name if getattr(voice_client, "channel", None) else "unknown",
            )
            return False
        tts_settings = self._tts_settings()
        audio_data = await self.tts_manager.generate_speech(
            text=job["text"],
            model_id=tts_settings.get("model_id", 0),
            speaker_id=tts_settings.get("speaker_id", 0),
            style=tts_settings.get("style", "Neutral"),
        )
        if not audio_data:
            self.logger.warning("MessageReader: Failed to generate audio for queued message")
            return False
        await self.play_audio_from_bytes(voice_client, audio_data)
        self.logger.info(
            "MessageReader: Played queued message (%s chars) for guild %s",
            len(job["text"]),
            guild.name,
        )
        return True

    async def _ensure_voice_connection(self, guild: discord.Guild):
        vc = guild.voice_client
        if vc and vc.is_connected():
            return vc
        reconnected = await self._attempt_auto_reconnect(guild)
        vc = guild.voice_client
        if reconnected and vc and vc.is_connected():
            return vc
        return None

    def _tts_settings(self):
        tts_config = self.tts_manager.tts_config
        return {
            "model_id": tts_config.get("model_id", 5),
            "speaker_id": tts_config.get("speaker_id", 0),
            "style": tts_config.get("style", "01"),
        }


def setup(bot):
    """Cogのセットアップ"""
    bot.add_cog(MessageReaderCog(bot, bot.config))
