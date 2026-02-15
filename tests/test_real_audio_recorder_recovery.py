import io
import wave
from types import SimpleNamespace

import pytest

from utils.real_audio_recorder import RealTimeAudioRecorder


def _make_wav_bytes(duration: float = 0.2, sample_rate: int = 48000, channels: int = 2) -> bytes:
    frames = int(duration * sample_rate)
    pcm = b"\x00\x00" * frames * channels
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm)
    return buf.getvalue()


class _DummyVoiceClient:
    def __init__(self, members):
        self.recording = True
        self.channel = SimpleNamespace(members=members, name="test")
        self.disconnect = None

    def is_connected(self):
        return True


@pytest.mark.asyncio
async def test_finished_callback_recovers_when_empty_callbacks_repeat(monkeypatch):
    recorder = RealTimeAudioRecorder(None)
    guild_id = 999

    human = SimpleNamespace(bot=False)
    bot_user = SimpleNamespace(bot=True)
    vc = _DummyVoiceClient([human, bot_user])

    recorder.connections[guild_id] = vc
    recorder.recording_status[guild_id] = True
    recorder.EMPTY_CALLBACK_RECOVERY_THRESHOLD = 2
    recorder.EMPTY_CALLBACK_RECOVERY_COOLDOWN = 0

    calls = {"stop": 0, "start": 0}

    async def fake_stop(_vc):
        calls["stop"] += 1

    async def fake_start(_vc, _sink, _callback):
        calls["start"] += 1

    monkeypatch.setattr(recorder, "_stop_recording_non_blocking", fake_stop)
    monkeypatch.setattr(recorder, "_start_recording_non_blocking", fake_start)
    monkeypatch.setattr(recorder, "_create_wave_sink", lambda: object())

    empty_sink = SimpleNamespace(audio_data={})
    await recorder._finished_callback(empty_sink, guild_id)
    await recorder._finished_callback(empty_sink, guild_id)

    assert calls["stop"] == 1
    assert calls["start"] == 1
    assert recorder.empty_callback_counts[guild_id] == 0


@pytest.mark.asyncio
async def test_finished_callback_resets_empty_counter_when_audio_received():
    recorder = RealTimeAudioRecorder(None)
    guild_id = 1001

    recorder.empty_callback_counts[guild_id] = 3
    recorder.connections[guild_id] = SimpleNamespace(recording=True)

    wav_bytes = _make_wav_bytes()
    sink = SimpleNamespace(audio_data={1: SimpleNamespace(file=io.BytesIO(wav_bytes))})

    await recorder._finished_callback(sink, guild_id)

    assert recorder.empty_callback_counts[guild_id] == 0


@pytest.mark.asyncio
async def test_recovery_continues_when_stop_recording_reports_not_recording(monkeypatch):
    recorder = RealTimeAudioRecorder(None)
    guild_id = 1002

    human = SimpleNamespace(bot=False)
    vc = _DummyVoiceClient([human])
    vc.recording = False

    recorder.connections[guild_id] = vc
    recorder.recording_status[guild_id] = True
    recorder.EMPTY_CALLBACK_RECOVERY_COOLDOWN = 0

    calls = {"start": 0}

    async def fake_stop(_vc):
        raise RuntimeError("Not currently recording audio.")

    async def fake_start(_vc, _sink, _callback):
        calls["start"] += 1

    monkeypatch.setattr(recorder, "_stop_recording_non_blocking", fake_stop)
    monkeypatch.setattr(recorder, "_start_recording_non_blocking", fake_start)
    monkeypatch.setattr(recorder, "_create_wave_sink", lambda: object())

    await recorder._attempt_recover_stuck_recording(guild_id)

    assert calls["start"] == 1


@pytest.mark.asyncio
async def test_recovery_retries_once_when_start_reports_already_recording(monkeypatch):
    recorder = RealTimeAudioRecorder(None)
    guild_id = 1003

    human = SimpleNamespace(bot=False)
    vc = _DummyVoiceClient([human])
    vc.recording = True

    recorder.connections[guild_id] = vc
    recorder.recording_status[guild_id] = True
    recorder.EMPTY_CALLBACK_RECOVERY_COOLDOWN = 0

    calls = {"stop": 0, "start": 0}

    async def fake_stop(_vc):
        calls["stop"] += 1
        _vc.recording = False

    async def fake_start(_vc, _sink, _callback):
        calls["start"] += 1
        if calls["start"] == 1:
            _vc.recording = True
            raise RuntimeError("Already recording.")
        _vc.recording = True

    monkeypatch.setattr(recorder, "_stop_recording_non_blocking", fake_stop)
    monkeypatch.setattr(recorder, "_start_recording_non_blocking", fake_start)
    monkeypatch.setattr(recorder, "_create_wave_sink", lambda: object())

    await recorder._attempt_recover_stuck_recording(guild_id)

    assert calls["start"] == 2
    assert recorder.recording_status[guild_id] is True


@pytest.mark.asyncio
async def test_recovery_escalates_to_hard_reconnect_after_repeated_soft_restarts(monkeypatch):
    recorder = RealTimeAudioRecorder(None)
    guild_id = 1004

    human = SimpleNamespace(bot=False)
    old_vc = _DummyVoiceClient([human])
    old_vc.recording = True

    connect_calls = {"count": 0}
    new_vc = _DummyVoiceClient([human])
    new_vc.recording = False

    async def fake_disconnect():
        return None

    async def fake_connect(*, cls, reconnect):
        connect_calls["count"] += 1
        assert reconnect is True
        assert cls is type(old_vc)
        return new_vc

    old_vc.disconnect = fake_disconnect
    old_vc.channel.connect = fake_connect

    recorder.connections[guild_id] = old_vc
    recorder.recording_status[guild_id] = True
    recorder.EMPTY_CALLBACK_RECOVERY_COOLDOWN = 0
    recorder.HARD_RECOVERY_AFTER_SOFT_RESTARTS = 2
    recorder._soft_recovery_restart_counts[guild_id] = 1

    start_calls = {"count": 0}

    async def fake_start(vc, _sink, _callback):
        start_calls["count"] += 1
        vc.recording = True

    async def fake_stop(_vc):
        raise AssertionError("soft restart should not run when hard reconnect is used")

    monkeypatch.setattr(recorder, "_start_recording_non_blocking", fake_start)
    monkeypatch.setattr(recorder, "_stop_recording_non_blocking", fake_stop)
    monkeypatch.setattr(recorder, "_create_wave_sink", lambda: object())

    await recorder._attempt_recover_stuck_recording(guild_id)

    assert connect_calls["count"] == 1
    assert start_calls["count"] == 1
    assert recorder.connections[guild_id] is new_vc
    assert recorder.recording_status[guild_id] is True
