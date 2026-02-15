import io
import wave

import pytest

from utils.recording_callback_manager import AudioChunk
from utils.replay_buffer_manager import ReplayBufferManager


def make_wav(duration_seconds: float = 0.5, sample_rate: int = 48000, channels: int = 2) -> bytes:
    frames = int(sample_rate * duration_seconds)
    payload = b"\x10\x00" * frames * channels
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(payload)
    return buffer.getvalue()


def add_junk_chunk(wav_bytes: bytes, payload: bytes = b"abcd1234") -> bytes:
    # RIFF(12) + fmt chunk(24) + ... の標準PCM前提
    riff_header = wav_bytes[:12]
    fmt_chunk = wav_bytes[12:36]
    rest = wav_bytes[36:]
    junk = b"JUNK" + len(payload).to_bytes(4, "little") + payload
    if len(payload) % 2 == 1:
        junk += b"\x00"
    merged = riff_header + fmt_chunk + junk + rest

    total_size = len(merged) - 8
    merged = merged[:4] + total_size.to_bytes(4, "little") + merged[8:]
    return merged


def pcm_bytes(wav_bytes: bytes) -> bytes:
    with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
        return wav_file.readframes(wav_file.getnframes())


@pytest.mark.asyncio
async def test_process_user_audio_parses_variable_wav_header():
    manager = ReplayBufferManager(config={})

    chunk1 = make_wav(0.4)
    chunk2 = add_junk_chunk(make_wav(0.6))

    chunks = [
        AudioChunk(user_id=1, guild_id=1, data=chunk2, timestamp=2.0, duration=0.6),
        AudioChunk(user_id=1, guild_id=1, data=chunk1, timestamp=1.0, duration=0.4),
    ]

    merged = await manager._process_user_audio(chunks, normalize=False)

    expected_pcm = pcm_bytes(chunk1) + pcm_bytes(chunk2)
    actual_pcm = pcm_bytes(merged)

    assert actual_pcm == expected_pcm


@pytest.mark.asyncio
async def test_process_user_audio_normalize_limits_peak():
    manager = ReplayBufferManager(config={})
    loud = make_wav(0.2)
    # 人為的にクリップ気味のPCMへ置換
    with wave.open(io.BytesIO(loud), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_rate = wav_file.getframerate()
        frames = wav_file.getnframes()
    clipped_pcm = (b"\xff\x7f" * frames * channels)
    loud_buffer = io.BytesIO()
    with wave.open(loud_buffer, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(clipped_pcm)
    loud_wav = loud_buffer.getvalue()

    chunks = [AudioChunk(user_id=1, guild_id=1, data=loud_wav, timestamp=1.0, duration=0.2)]
    merged = await manager._process_user_audio(chunks, normalize=True)

    with wave.open(io.BytesIO(merged), "rb") as wav_file:
        pcm = wav_file.readframes(wav_file.getnframes())
    # 正規化で最大値32767張り付きが解消されること
    assert b"\xff\x7f" not in pcm[:200]


@pytest.mark.asyncio
async def test_process_user_audio_skips_overlapping_region():
    manager = ReplayBufferManager(config={})
    # 5秒 + 5秒チャンクだが、時刻上は2秒重複
    c1 = AudioChunk(user_id=1, guild_id=1, data=make_wav(5.0), timestamp=10.0, duration=5.0)
    c2 = AudioChunk(user_id=1, guild_id=1, data=make_wav(5.0), timestamp=13.0, duration=5.0)

    merged = await manager._process_user_audio([c1, c2], normalize=False)
    with wave.open(io.BytesIO(merged), "rb") as wav_file:
        duration = wav_file.getnframes() / wav_file.getframerate()

    assert 7.8 <= duration <= 8.2


@pytest.mark.asyncio
async def test_process_user_audio_uses_cached_pcm_when_available(monkeypatch):
    manager = ReplayBufferManager(config={})
    wav_data = make_wav(0.3)
    cached_pcm = pcm_bytes(wav_data)
    chunk = AudioChunk(
        user_id=1,
        guild_id=1,
        data=wav_data,
        timestamp=1.0,
        duration=0.3,
        sample_rate=48000,
        channels=2,
        sample_width=2,
        pcm_data=cached_pcm,
    )

    original_wave_open = wave.open

    def block_read_wave_open(file_obj, mode="rb", *args, **kwargs):
        if "r" in mode:
            raise AssertionError("wave.open(read) should not be called when pcm_data is available")
        return original_wave_open(file_obj, mode, *args, **kwargs)

    monkeypatch.setattr("utils.replay_buffer_manager.wave.open", block_read_wave_open)
    merged = await manager._process_user_audio([chunk], normalize=False)
    monkeypatch.undo()

    assert pcm_bytes(merged) == cached_pcm


def test_trim_audio_to_duration_keeps_tail():
    manager = ReplayBufferManager(config={})
    src = make_wav(12.0, channels=1)
    trimmed = manager._trim_audio_to_duration(src, 5.0)

    with wave.open(io.BytesIO(trimmed), "rb") as wav_file:
        duration = wav_file.getnframes() / wav_file.getframerate()
        channels = wav_file.getnchannels()

    assert 4.9 <= duration <= 5.1
    assert channels == 1
