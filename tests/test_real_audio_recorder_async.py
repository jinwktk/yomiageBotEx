import asyncio
import threading
import time
from types import SimpleNamespace

import pytest

from utils.real_audio_recorder import RealTimeAudioRecorder


class DummyVoiceClient:
    def __init__(self):
        self.stop_thread = None
        self.start_thread = None

    def stop_recording(self):
        self.stop_thread = threading.current_thread().name
        time.sleep(0.05)

    def start_recording(self, sink, callback):
        self.start_thread = threading.current_thread().name
        time.sleep(0.05)


@pytest.mark.asyncio
async def test_stop_recording_runs_off_event_loop(tmp_path, monkeypatch):
    monkeypatch.setattr("utils.tts.Path", lambda p: tmp_path / p)
    recorder = RealTimeAudioRecorder(SimpleNamespace())
    voice_client = DummyVoiceClient()

    main_thread = threading.current_thread().name
    await recorder._stop_recording_non_blocking(voice_client)

    assert voice_client.stop_thread is not None
    assert voice_client.stop_thread != main_thread


@pytest.mark.asyncio
async def test_start_recording_runs_off_event_loop(tmp_path, monkeypatch):
    monkeypatch.setattr("utils.tts.Path", lambda p: tmp_path / p)
    recorder = RealTimeAudioRecorder(SimpleNamespace())
    voice_client = DummyVoiceClient()

    main_thread = threading.current_thread().name
    await recorder._start_recording_non_blocking(voice_client, sink=object(), callback=lambda *_: None)

    assert voice_client.start_thread is not None
    assert voice_client.start_thread != main_thread
