import io
import wave

import pytest

from utils.recording_callback_manager import RecordingCallbackManager


def make_wav(duration_seconds: float = 0.25, sample_rate: int = 48000, channels: int = 2) -> bytes:
    frames = int(sample_rate * duration_seconds)
    payload = b"\x34\x12" * frames * channels
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(payload)
    return buffer.getvalue()


def pcm_bytes(wav_bytes: bytes) -> bytes:
    with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
        return wav_file.readframes(wav_file.getnframes())


@pytest.mark.asyncio
async def test_process_audio_data_caches_pcm_in_audio_chunk():
    manager = RecordingCallbackManager()
    wav_data = make_wav()

    added = await manager.process_audio_data(guild_id=1, user_id=42, audio_data=wav_data)

    assert added is True
    chunk = manager.audio_buffers[1][42][0]
    assert chunk.pcm_data == pcm_bytes(wav_data)
    assert chunk.data == b""
    assert chunk.sample_rate == 48000
    assert chunk.channels == 2
    assert chunk.sample_width == 2
