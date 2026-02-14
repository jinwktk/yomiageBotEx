import io
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from cogs.recording import RecordingCog
from utils.replay_buffer_manager import ReplayResult


def make_wav(duration_seconds: float = 0.5, sample_rate: int = 48000) -> bytes:
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
        self.user = SimpleNamespace(display_name="tester")


class FakeReplayBufferManager:
    def __init__(self, audio_bytes: bytes):
        self.audio_bytes = audio_bytes

    async def get_replay_audio(self, **kwargs):
        return ReplayResult(
            audio_data=self.audio_bytes,
            total_duration=kwargs.get("duration_seconds", 0.0),
            user_count=1,
            file_size=len(self.audio_bytes),
            sample_rate=48000,
            channels=2,
            generation_time=time.time(),
        )


class FakeUser:
    def __init__(self, user_id: int, display_name: str):
        self.id = user_id
        self.display_name = display_name
        self.mention = f"<@{user_id}>"


@pytest.mark.asyncio
async def test_new_replay_outputs_debug_stage_files(monkeypatch, tmp_path: Path):
    config = {
        "recording": {"enabled": True},
        "bot": {"rate_limit_delay": [0, 0]},
        "audio_processing": {"normalize": False},
    }
    bot = SimpleNamespace()
    cog = RecordingCog(bot, config)
    cog.replay_dir_base = tmp_path / "replay"
    cog.replay_dir_base.mkdir(parents=True, exist_ok=True)

    wav_bytes = make_wav()
    cog._replay_buffer_manager_override = FakeReplayBufferManager(wav_bytes)

    async def fake_process_audio_buffer(audio_buffer, normalize=True, debug_stage_output=None):
        payload = audio_buffer.getvalue()
        if debug_stage_output is not None:
            debug_stage_output["raw"] = payload
            debug_stage_output["normalized"] = payload
            debug_stage_output["processed"] = payload
        return payload

    monkeypatch.setattr(cog, "_process_audio_buffer", fake_process_audio_buffer)

    created_files = []

    class DummyFile:
        def __init__(self, fp, filename):
            created_files.append(filename)
            self.fp = fp
            self.filename = filename

    monkeypatch.setattr("cogs.recording.discord.File", DummyFile)

    ctx = FakeContext(guild_id=123)
    user = FakeUser(42, "Varna")

    success = await cog._process_new_replay_async(
        ctx,
        duration=30.0,
        user=user,
        normalize=True,
        debug_audio_stages=True,
    )

    assert success is True
    assert len(ctx.followup.messages) >= 2
    assert any("工程別音声" in (msg.get("content") or "") for msg in ctx.followup.messages)

    debug_dir = cog.replay_dir_base / "123" / "debug"
    assert list(debug_dir.glob("*_01_raw.wav"))
    assert list(debug_dir.glob("*_02_normalized.wav"))
    assert list(debug_dir.glob("*_03_processed.wav"))
    assert list(debug_dir.glob("*_stages.zip"))

    assert created_files, "Discord.File が作成されていません"
