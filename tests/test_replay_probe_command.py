import io
import time
from types import SimpleNamespace

import pytest

from cogs.recording import RecordingCog
from utils.recording_callback_manager import AudioChunk


def make_wav(duration_seconds: float = 1.0, sample_rate: int = 48000) -> bytes:
    import wave

    frames = int(sample_rate * duration_seconds)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(2)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x01\x00" * frames * 2)
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
        self.deferred = False

    async def defer(self, **kwargs):
        self.deferred = True


class StubCallbackManager:
    def __init__(self, chunks):
        self.is_initialized = True
        self._chunks = chunks

    async def get_recent_audio(self, **_kwargs):
        return self._chunks


@pytest.mark.asyncio
async def test_replay_probe_sends_latest_chunk(monkeypatch, tmp_path):
    config = {
        "recording": {"enabled": True},
        "bot": {"rate_limit_delay": [0, 0]},
        "audio_processing": {"normalize": False},
    }
    bot = SimpleNamespace()
    cog = RecordingCog(bot, config)
    cog.replay_dir_base = tmp_path / "replay"
    cog.replay_dir_base.mkdir(parents=True, exist_ok=True)

    wav_data = make_wav(0.5)
    chunk = AudioChunk(
        user_id=111,
        guild_id=123,
        data=wav_data,
        timestamp=time.time(),
        duration=0.5,
    )
    stub_manager = StubCallbackManager([chunk])
    monkeypatch.setattr("cogs.recording.recording_callback_manager", stub_manager)

    sent_files = []

    class DummyFile:
        def __init__(self, fp, filename):
            sent_files.append({"filename": filename, "fp": fp})
            self.fp = fp
            self.filename = filename

    monkeypatch.setattr("cogs.recording.discord.File", DummyFile)

    ctx = FakeContext(guild_id=123)

    await RecordingCog.replay_probe.callback(cog, ctx, user=None, duration=10.0)

    assert ctx.deferred is True
    assert ctx.followup.messages, "フォローアップ応答が送信されていません"
    assert sent_files, "診断用のWAVが送信されていません"
    message = ctx.followup.messages[-1]
    assert "音声サンプル" in message["content"]
    assert message["ephemeral"] is True


@pytest.mark.asyncio
async def test_replay_probe_handles_no_chunks(monkeypatch):
    config = {
        "recording": {"enabled": True},
        "bot": {"rate_limit_delay": [0, 0]},
        "audio_processing": {"normalize": False},
    }
    bot = SimpleNamespace()
    cog = RecordingCog(bot, config)

    stub_manager = StubCallbackManager([])
    monkeypatch.setattr("cogs.recording.recording_callback_manager", stub_manager)

    ctx = FakeContext(guild_id=123)

    await RecordingCog.replay_probe.callback(cog, ctx, user=None, duration=10.0)

    assert ctx.followup.messages, "フォローアップ応答が送信されていません"
    message = ctx.followup.messages[-1]
    assert "取得できません" in message["content"]
    assert message["ephemeral"] is True
