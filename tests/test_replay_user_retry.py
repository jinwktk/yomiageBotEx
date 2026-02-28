import io
from types import SimpleNamespace

import pytest

from cogs.recording import RecordingCog


def make_wav(duration_seconds: float = 0.5, sample_rate: int = 48000) -> bytes:
    import wave

    frames = int(sample_rate * duration_seconds)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x01\x00" * frames)
    return buffer.getvalue()


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
async def test_replay_user_retries_once_after_no_data(monkeypatch, tmp_path):
    config = {
        "recording": {"enabled": True, "prefer_replay_buffer_manager": False},
        "bot": {"rate_limit_delay": [0, 0]},
        "audio_processing": {"normalize": False},
    }
    cog = RecordingCog(SimpleNamespace(), config)
    cog.replay_dir_base = tmp_path / "replay"
    cog.replay_dir_base.mkdir(parents=True, exist_ok=True)

    guild_id = 123
    target_user = FakeUser(42, "Nymeia")
    wav_bytes = make_wav()

    calls = {"get_audio_for_time_range": 0, "checkpoint": 0}

    def get_audio_for_time_range(_guild_id, _duration, user_id):
        calls["get_audio_for_time_range"] += 1
        assert user_id == target_user.id
        if calls["get_audio_for_time_range"] == 1:
            return {}
        return {target_user.id: wav_bytes}

    async def force_recording_checkpoint(_guild_id):
        calls["checkpoint"] += 1
        return True

    async def clean_old_buffers(_guild_id):
        return None

    cog.real_time_recorder = SimpleNamespace(
        get_audio_for_time_range=get_audio_for_time_range,
        clean_old_buffers=clean_old_buffers,
        get_buffer_health_summary=lambda *_a, **_k: {"entries": []},
        connections={guild_id: SimpleNamespace(recording=True)},
        continuous_buffers={guild_id: {target_user.id: []}},
        force_recording_checkpoint=force_recording_checkpoint,
    )

    sent = {"called": 0}

    async def fake_send_replay(*_args, **_kwargs):
        sent["called"] += 1

    async def fake_process_audio_buffer(audio_buffer, normalize):
        _ = normalize
        audio_buffer.seek(0)
        return audio_buffer.read()

    async def fast_sleep(_seconds):
        return None

    monkeypatch.setattr(cog, "_send_replay_with_share_button", fake_send_replay)
    monkeypatch.setattr(cog, "_process_audio_buffer", fake_process_audio_buffer)
    monkeypatch.setattr("cogs.recording.asyncio.sleep", fast_sleep)

    ctx = FakeContext(guild_id=guild_id)
    await cog._process_replay_async(ctx, duration=30.0, user=target_user, normalize=False)

    assert sent["called"] == 1
    assert calls["get_audio_for_time_range"] >= 2
    assert calls["checkpoint"] >= 2
