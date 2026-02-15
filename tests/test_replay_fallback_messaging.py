from types import SimpleNamespace

import pytest

from cogs.recording import RecordingCog


class FakeFollowup:
    def __init__(self):
        self.messages = []

    async def send(self, content=None, **kwargs):
        payload = {"content": content}
        payload.update(kwargs)
        self.messages.append(payload)


class FakeContext:
    def __init__(self, guild_id: int):
        self.guild = SimpleNamespace(id=guild_id, name="guild")
        self.followup = FakeFollowup()
        self.user = SimpleNamespace(display_name="tester")


class FakeUser:
    def __init__(self, user_id: int, display_name: str):
        self.id = user_id
        self.display_name = display_name
        self.mention = f"<@{user_id}>"


@pytest.mark.asyncio
async def test_replay_fallback_does_not_send_new_system_no_data_message(monkeypatch):
    config = {
        "recording": {"enabled": True, "prefer_replay_buffer_manager": True},
        "bot": {"rate_limit_delay": [0, 0]},
        "audio_processing": {"normalize": False},
    }
    bot = SimpleNamespace()
    cog = RecordingCog(bot, config)

    async def fake_new_replay(*args, **kwargs):
        assert kwargs.get("suppress_no_data_message") is True
        return False

    async def fake_get_audio_for_time_range(*args, **kwargs):
        return {}

    async def fake_clean_old_buffers(*args, **kwargs):
        return None

    cog.real_time_recorder = SimpleNamespace(
        get_audio_for_time_range=lambda *a, **k: {},
        clean_old_buffers=fake_clean_old_buffers,
        get_buffer_health_summary=lambda *a, **k: {"entries": []},
        connections={},
        continuous_buffers={},
    )

    monkeypatch.setattr(cog, "_process_new_replay_async", fake_new_replay)

    ctx = FakeContext(guild_id=123)
    user = FakeUser(42, "Nymeia")

    await cog._process_replay_async(ctx, duration=30.0, user=user, normalize=True)

    assert ctx.followup.messages, "フォローアップメッセージが送信されていません"
    all_content = "\n".join((m.get("content") or "") for m in ctx.followup.messages)
    assert "❌ @Nymeia の過去30.0秒間の音声データが見つかりません" not in all_content
    assert "⚠️" in all_content
