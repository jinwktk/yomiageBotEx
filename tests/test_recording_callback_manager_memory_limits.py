import io
import wave

import pytest

from utils.recording_callback_manager import RecordingCallbackManager


def make_wav(sample_value: int, duration_seconds: float = 0.2, sample_rate: int = 48000, channels: int = 2) -> bytes:
    frames = int(sample_rate * duration_seconds)
    sample = int(sample_value).to_bytes(2, "little", signed=True)
    payload = sample * frames * channels
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(payload)
    return buffer.getvalue()


def estimate_chunk_bytes(wav_data: bytes) -> int:
    pcm_size = max(len(wav_data) - 44, 0)
    return len(wav_data) + pcm_size


@pytest.mark.asyncio
async def test_process_audio_data_evicts_oldest_chunk_when_user_limit_exceeded():
    manager = RecordingCallbackManager()
    manager.max_buffer_duration = 9999

    first = make_wav(sample_value=200)
    second = make_wav(sample_value=400)

    chunk_bytes = estimate_chunk_bytes(first)
    manager.max_user_buffer_bytes = chunk_bytes + 32
    manager.max_guild_buffer_bytes = chunk_bytes * 4
    manager.max_total_buffer_bytes = chunk_bytes * 8

    await manager.process_audio_data(guild_id=1, user_id=10, audio_data=first)
    await manager.process_audio_data(guild_id=1, user_id=10, audio_data=second)

    user_chunks = manager.audio_buffers[1][10]
    assert len(user_chunks) == 1
    assert user_chunks[0].data == second


@pytest.mark.asyncio
async def test_process_audio_data_evicts_oldest_chunk_when_total_limit_exceeded():
    manager = RecordingCallbackManager()
    manager.max_buffer_duration = 9999

    wav_a = make_wav(sample_value=100)
    wav_b = make_wav(sample_value=200)
    wav_c = make_wav(sample_value=300)

    chunk_bytes = estimate_chunk_bytes(wav_a)
    manager.max_user_buffer_bytes = chunk_bytes * 4
    manager.max_guild_buffer_bytes = chunk_bytes * 4
    manager.max_total_buffer_bytes = chunk_bytes * 2 + 32

    await manager.process_audio_data(guild_id=1, user_id=10, audio_data=wav_a)
    await manager.process_audio_data(guild_id=2, user_id=20, audio_data=wav_b)
    await manager.process_audio_data(guild_id=2, user_id=21, audio_data=wav_c)

    assert 1 not in manager.audio_buffers
    assert set(manager.audio_buffers[2].keys()) == {20, 21}
