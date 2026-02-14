import array
import io
import wave
from types import SimpleNamespace

import pytest

from utils import real_audio_recorder as recorder_module
from utils.real_audio_recorder import RealTimeAudioRecorder


def make_silent_wav(duration_seconds: float, sample_rate: int = 48000, channels: int = 2) -> bytes:
    total_frames = int(sample_rate * duration_seconds)
    data = array.array("h", [0] * (total_frames * channels))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(data.tobytes())
    return buffer.getvalue()


def test_continuous_buffer_records_actual_duration(monkeypatch):
    recorder = RealTimeAudioRecorder(None)
    now_holder = {"value": 1000.0}
    monkeypatch.setattr(recorder_module.time, "time", lambda: now_holder["value"])

    wav_bytes = make_silent_wav(1.5)
    recorder._add_to_continuous_buffer(guild_id=1, user_id=42, audio_data=wav_bytes, timestamp=now_holder["value"])

    stored = recorder.continuous_buffers[1][42][-1]
    _, start_time, end_time = stored
    assert pytest.approx(end_time, rel=1e-3) == now_holder["value"]
    assert pytest.approx(start_time, rel=1e-3) == now_holder["value"] - 1.5


def test_get_audio_for_time_range_returns_latest_chunk(monkeypatch):
    recorder = RealTimeAudioRecorder(None)
    time_state = {"value": 2000.0}
    monkeypatch.setattr(recorder_module.time, "time", lambda: time_state["value"])

    wav_bytes = make_silent_wav(2.0)
    recorder._add_to_continuous_buffer(guild_id=7, user_id=99, audio_data=wav_bytes, timestamp=time_state["value"])

    # advance current time slightly so request window includes the chunk
    time_state["value"] += 1.0
    result = recorder.get_audio_for_time_range(guild_id=7, duration_seconds=5.0, user_id=99)

    assert 99 in result
    assert result[99] == wav_bytes


@pytest.mark.asyncio
async def test_checkpoint_and_finished_callback_do_not_duplicate_audio(monkeypatch):
    recorder = RealTimeAudioRecorder(None)
    time_state = {"value": 3000.0}
    monkeypatch.setattr(recorder_module.time, "time", lambda: time_state["value"])

    wav_bytes = make_silent_wav(1.0)

    class MockAudio:
        def __init__(self, payload: bytes):
            self.file = io.BytesIO(payload)

    mock_audio = MockAudio(wav_bytes)

    await recorder._process_checkpoint_data(1, {123: mock_audio})

    time_state["value"] += 0.05
    mock_audio.file.seek(0)

    sink = SimpleNamespace(audio_data={123: mock_audio})
    await recorder._finished_callback(sink, 1)

    result = recorder.get_audio_for_time_range(guild_id=1, duration_seconds=5.0, user_id=123)

    assert 123 in result
    assert result[123] == wav_bytes


@pytest.mark.asyncio
async def test_checkpoint_data_is_forwarded_to_recording_callback_manager(monkeypatch):
    recorder = RealTimeAudioRecorder(None)
    time_state = {"value": 4000.0}
    monkeypatch.setattr(recorder_module.time, "time", lambda: time_state["value"])

    wav_bytes = make_silent_wav(1.0)

    class StubCallbackManager:
        def __init__(self):
            self.is_initialized = True
            self.calls = []

        async def process_audio_data(self, guild_id, user_id, audio_data):
            self.calls.append((guild_id, user_id, audio_data))
            return True

    stub_manager = StubCallbackManager()
    monkeypatch.setattr(recorder_module, "recording_callback_manager", stub_manager, raising=False)

    class MockAudio:
        def __init__(self, payload: bytes):
            self.file = io.BytesIO(payload)

    mock_audio = MockAudio(wav_bytes)
    await recorder._process_checkpoint_data(10, {321: mock_audio})

    time_state["value"] += 0.05
    mock_audio.file.seek(0)
    sink = SimpleNamespace(audio_data={321: mock_audio})
    await recorder._finished_callback(sink, 10)

    assert len(stub_manager.calls) == 1
    guild_id, user_id, forwarded_audio = stub_manager.calls[0]
    assert guild_id == 10
    assert user_id == 321
    assert forwarded_audio == wav_bytes
