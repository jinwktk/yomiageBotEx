import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cogs.voice import VoiceCog


class DummyVoiceClient:
    def __init__(self, channel):
        self.channel = channel
        self.recording = False

    def is_connected(self):
        return False


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
    guild = SimpleNamespace(name="Valworld", id=111, voice_client=DummyVoiceClient(channel))

    await VoiceCog.handle_user_join(cog, guild, channel)

    connect_mock.assert_awaited_once_with(channel)
    cog.notify_bot_joined_channel.assert_awaited_once_with(guild, channel)
