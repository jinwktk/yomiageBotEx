import asyncio
import io
import wave
from types import SimpleNamespace

import pytest

from utils.manual_recording_manager import (
    ManualRecordingError,
    ManualRecordingManager,
)


def make_wav(duration_seconds: float = 1.0, sample_rate: int = 48000) -> bytes:
    """Generate silent WAV bytes for testing."""
    total_frames = int(sample_rate * duration_seconds)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\x00\x00" * total_frames * 2)
    return buffer.getvalue()


class FakeAudio:
    def __init__(self, data: bytes):
        self.file = io.BytesIO(data)


class FakeSink:
    encoding = "wav"

    def __init__(self):
        self.audio_data = {}


class FakeVoiceClient:
    """Mimics the subset of discord.VoiceClient behaviour used by the manager."""

    def __init__(self, guild_id: int):
        self.guild = SimpleNamespace(id=guild_id)
        self.channel = SimpleNamespace(id=999, name="test-channel")
        self.recording = False
        self._start_calls = 0
        self._sink = None
        self._callback = None
        self._callback_task = None
        self.next_payload = {}

    def is_connected(self):
        return True

    def start_recording(self, sink, callback):
        self._start_calls += 1
        self.recording = True
        self._sink = sink
        self._callback = callback

    def stop_recording(self):
        if not self.recording:
            raise RuntimeError("not recording")
        self.recording = False
        if self._sink is not None:
            self._sink.audio_data = self.next_payload
        if self._callback is not None:
            if asyncio.iscoroutinefunction(self._callback):
                self._callback_task = asyncio.create_task(self._callback(self._sink))
            else:
                self._callback(self._sink)

    async def wait_for_callback(self):
        if self._callback_task:
            await self._callback_task


@pytest.mark.asyncio
async def test_start_session_registers_voice_recording(tmp_path):
    manager = ManualRecordingManager(base_dir=tmp_path, sink_factory=FakeSink)
    voice_client = FakeVoiceClient(guild_id=123)

    session = await manager.start_session(
        guild_id=123,
        voice_client=voice_client,
        initiated_by=456,
    )

    assert session.guild_id == 123
    assert voice_client.recording is True
    assert voice_client._start_calls == 1


@pytest.mark.asyncio
async def test_start_session_twice_raises(tmp_path):
    manager = ManualRecordingManager(base_dir=tmp_path, sink_factory=FakeSink)
    voice_client = FakeVoiceClient(guild_id=321)

    await manager.start_session(guild_id=321, voice_client=voice_client, initiated_by=1)

    with pytest.raises(ManualRecordingError):
        await manager.start_session(guild_id=321, voice_client=voice_client, initiated_by=2)


@pytest.mark.asyncio
async def test_stop_session_collects_audio_payload(tmp_path):
    manager = ManualRecordingManager(base_dir=tmp_path, sink_factory=FakeSink)
    voice_client = FakeVoiceClient(guild_id=777)
    await manager.start_session(guild_id=777, voice_client=voice_client, initiated_by=2)

    wav_bytes = make_wav(1.2)
    voice_client.next_payload = {42: FakeAudio(wav_bytes)}

    result = await manager.stop_session(guild_id=777, timeout=1.0)

    await voice_client.wait_for_callback()

    assert result.guild_id == 777
    assert 42 in result.audio_map
    assert result.audio_map[42] == wav_bytes
    assert pytest.approx(result.durations[42], rel=1e-2) == 1.2
    assert result.initiated_by == 2


@pytest.mark.asyncio
async def test_stop_without_session_raises(tmp_path):
    manager = ManualRecordingManager(base_dir=tmp_path, sink_factory=FakeSink)
    with pytest.raises(ManualRecordingError):
        await manager.stop_session(guild_id=404, timeout=0.1)

