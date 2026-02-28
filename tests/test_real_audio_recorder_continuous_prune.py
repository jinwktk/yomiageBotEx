import io
import time
import wave

from utils.real_audio_recorder import RealTimeAudioRecorder


def make_wav_bytes(duration: float = 0.3, sample_rate: int = 48000, channels: int = 2) -> bytes:
    frames = int(duration * sample_rate)
    pcm = b"\x00\x00" * frames * channels
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm)
    return buf.getvalue()


def test_get_audio_for_time_range_prunes_expired_continuous_chunks():
    recorder = RealTimeAudioRecorder(None)
    recorder.CONTINUOUS_BUFFER_DURATION = 120.0
    guild_id = 100
    user_id = 200

    now = time.time()
    old_start = now - 1000.0
    old_end = now - 999.5
    recorder.continuous_buffers[guild_id] = {user_id: [(make_wav_bytes(), old_start, old_end)]}

    result = recorder.get_audio_for_time_range(guild_id, duration_seconds=30.0, user_id=user_id)

    assert result == {}
    assert guild_id not in recorder.continuous_buffers or user_id not in recorder.continuous_buffers.get(guild_id, {})
