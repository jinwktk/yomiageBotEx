from types import SimpleNamespace

import pytest

from cogs.recording import RecordingCog


@pytest.mark.asyncio
async def test_on_voice_state_update_awaits_stop_recording():
    config = {
        "recording": {"enabled": True},
        "bot": {"rate_limit_delay": [0, 0]},
        "audio_processing": {"normalize": False},
    }
    bot = SimpleNamespace()
    cog = RecordingCog(bot, config)

    class StubRecorder:
        def __init__(self):
            self.stopped = False

        async def stop_recording(self, guild_id, voice_client):
            self.stopped = True

    stub_recorder = StubRecorder()
    cog.real_time_recorder = stub_recorder

    bot_member = SimpleNamespace(bot=True, display_name="bot")
    channel = SimpleNamespace(name="general", members=[bot_member])
    voice_client = SimpleNamespace(is_connected=lambda: True, channel=channel)
    guild = SimpleNamespace(id=1, name="guild", voice_client=voice_client)

    member = SimpleNamespace(bot=False, display_name="user", guild=guild)
    before = SimpleNamespace(channel=channel)
    after = SimpleNamespace(channel=None)

    await cog.on_voice_state_update(member, before, after)

    assert stub_recorder.stopped is True
