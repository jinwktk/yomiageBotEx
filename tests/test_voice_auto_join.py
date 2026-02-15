import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cogs.voice import VoiceCog


class DummyVoiceClient:
    def __init__(self, channel, *, connected=False):
        self.channel = channel
        self.recording = False
        self._connected = connected
        self.move_to = AsyncMock()

    def is_connected(self):
        return self._connected


@pytest.mark.asyncio
async def test_handle_user_join_reconnects_when_voice_client_is_disconnected(monkeypatch):
    cog = VoiceCog.__new__(VoiceCog)
    cog.config = {"bot": {"auto_join": True}}
    connect_mock = AsyncMock()
    cog.bot = SimpleNamespace(connect_to_voice=connect_mock, get_cog=lambda name: None)
    cog.logger = logging.getLogger("test.voice")
    cog.notify_bot_joined_channel = AsyncMock()
    cog.save_sessions = lambda: None

    channel = SimpleNamespace(name="おもちだいすきクラブ", members=[])
    guild = SimpleNamespace(name="Valworld", id=111, voice_client=DummyVoiceClient(channel, connected=False))

    await VoiceCog.handle_user_join(cog, guild, channel)

    connect_mock.assert_awaited_once_with(channel)
    cog.notify_bot_joined_channel.assert_awaited_once_with(guild, channel)


@pytest.mark.asyncio
async def test_handle_user_join_does_not_move_when_already_connected_to_other_channel():
    cog = VoiceCog.__new__(VoiceCog)
    cog.config = {"bot": {"auto_join": True}}
    connect_mock = AsyncMock()
    cog.bot = SimpleNamespace(connect_to_voice=connect_mock, get_cog=lambda name: None)
    cog.logger = logging.getLogger("test.voice")
    cog.notify_bot_joined_channel = AsyncMock()
    cog.save_sessions = lambda: None

    current_channel = SimpleNamespace(name="おもちだいすきクラブ", members=[])
    joined_channel = SimpleNamespace(name="別チャンネル", members=[])
    voice_client = DummyVoiceClient(current_channel, connected=True)
    guild = SimpleNamespace(name="Valworld", id=111, voice_client=voice_client)

    await VoiceCog.handle_user_join(cog, guild, joined_channel)

    voice_client.move_to.assert_not_awaited()
    connect_mock.assert_not_awaited()
    cog.notify_bot_joined_channel.assert_not_awaited()
