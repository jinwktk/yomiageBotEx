import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cogs.message_reader import MessageReaderCog


class DummyVoiceClient:
    def __init__(self):
        self._connected = True
        self.channel = SimpleNamespace(name="dummy", id=1)

    def is_connected(self):
        return self._connected


class DummyDictionaryManager:
    def __init__(self):
        self.calls = []
        self.global_dictionary = {}
        self.guild_dictionaries = {}

    def apply_dictionary(self, text, guild_id):
        self.calls.append((text, guild_id))
        return text.replace("Nymeia", "にめいや")


class DummyContext:
    def __init__(self, guild):
        self.guild = guild
        self.user = SimpleNamespace(display_name="tester")
        self.responses = []

    async def respond(self, content, ephemeral=False):
        self.responses.append({"content": content, "ephemeral": ephemeral})


@pytest.mark.asyncio
async def test_echo_command_reads_without_post(tmp_path, monkeypatch):
    monkeypatch.setattr("utils.tts.Path", lambda p: tmp_path / p)

    config = {
        "bot": {"rate_limit_delay": [0, 0]},
        "message_reading": {
            "enabled": True,
            "max_length": 200,
        },
    }

    dictionary = DummyDictionaryManager()
    bot = SimpleNamespace(config=config, dictionary_manager=dictionary, connect_voice_safely=None)
    cog = MessageReaderCog(bot, config)

    voice_client = DummyVoiceClient()
    guild = SimpleNamespace(
        id=123,
        name="Test",
        voice_client=voice_client,
        voice_channels=[],
        get_channel=lambda cid: None,
    )
    ctx = DummyContext(guild)

    tts_mock = AsyncMock(return_value=b"audio")
    cog.tts_manager.generate_speech = tts_mock
    play_mock = AsyncMock()
    cog.play_audio_from_bytes = play_mock

    await MessageReaderCog.echo_command.callback(cog, ctx, "Nymeia test")

    assert dictionary.calls == [("Nymeia test", 123)]
    assert tts_mock.await_args.kwargs["text"] == "にめいや test"
    play_mock.assert_awaited_once()
    assert play_mock.await_args.args[0] is voice_client
    assert ctx.responses[-1]["ephemeral"] is True
    assert "🔊" in ctx.responses[-1]["content"]
