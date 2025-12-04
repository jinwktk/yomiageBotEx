import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cogs.message_reader import MessageReaderCog


class DummyVoiceClient:
    def __init__(self, channel_name="vc", members=None):
        if members is None:
            members = [SimpleNamespace(bot=False)]
        self._connected = True
        self.channel = SimpleNamespace(name=channel_name, id=1, members=members)

    def is_connected(self):
        return self._connected


@pytest.mark.asyncio
async def test_message_queue_retries_until_connection(tmp_path, monkeypatch):
    monkeypatch.setattr("utils.tts.Path", lambda p: tmp_path / p)

    config = {
        "bot": {"rate_limit_delay": [0, 0]},
        "message_reading": {"enabled": True, "max_length": 200},
    }

    dictionary = SimpleNamespace(global_dictionary={}, guild_dictionaries={}, apply_dictionary=lambda text, gid: text)
    bot = SimpleNamespace(config=config, dictionary_manager=dictionary, connect_voice_safely=None)

    guild = SimpleNamespace(
        id=1,
        name="TestGuild",
        voice_client=None,
        voice_channels=[],
    )

    def get_guild(gid):
        return guild

    bot.get_guild = get_guild

    cog = MessageReaderCog(bot, config)
    cog.dictionary_manager = dictionary

    async def fake_reconnect(target_guild):
        target_guild.voice_client = DummyVoiceClient()
        return True

    cog._attempt_auto_reconnect = fake_reconnect
    cog.tts_manager.generate_speech = AsyncMock(return_value=b"audio")
    cog.play_audio_from_bytes = AsyncMock()

    await cog._enqueue_message(guild, "test", "user")
    await asyncio.sleep(0.1)

    cog.play_audio_from_bytes.assert_awaited_once()


@pytest.mark.asyncio
async def test_on_message_skips_when_voice_channel_has_no_listeners(tmp_path, monkeypatch):
    monkeypatch.setattr("utils.tts.Path", lambda p: tmp_path / p)

    config = {
        "bot": {"rate_limit_delay": [0, 0]},
        "message_reading": {"enabled": True, "max_length": 200},
    }

    dictionary = SimpleNamespace(global_dictionary={}, guild_dictionaries={}, apply_dictionary=lambda text, gid: text)
    bot = SimpleNamespace(config=config, dictionary_manager=dictionary, connect_voice_safely=None)

    voice_client = DummyVoiceClient(members=[])
    guild = SimpleNamespace(
        id=99,
        name="EmptyGuild",
        voice_client=voice_client,
        voice_channels=[],
    )

    message = SimpleNamespace(
        guild=guild,
        author=SimpleNamespace(bot=False, display_name="tester"),
        content="こんにちは",
        attachments=[],
        stickers=[],
    )

    cog = MessageReaderCog(bot, config)
    cog.dictionary_manager = dictionary
    enqueue_mock = AsyncMock()
    cog._enqueue_message = enqueue_mock

    await cog.on_message(message)

    enqueue_mock.assert_not_called()
