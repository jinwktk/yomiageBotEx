from types import SimpleNamespace

from utils.real_audio_recorder import RealTimeAudioRecorder


def test_create_wave_sink_adds_receive_router_compat(monkeypatch):
    class DummySink:
        pass

    monkeypatch.setattr("utils.real_audio_recorder.WaveSink", DummySink)
    recorder = RealTimeAudioRecorder(SimpleNamespace())

    sink = recorder._create_wave_sink()

    assert hasattr(sink, "__sink_listeners__")
    assert sink.__sink_listeners__ == []
    assert callable(getattr(sink, "walk_children", None))
    assert sink.walk_children() == []
    assert callable(getattr(sink, "is_opus", None))
    assert sink.is_opus() is False


def test_create_wave_sink_keeps_existing_receive_router_hooks(monkeypatch):
    class DummySink:
        __sink_listeners__ = [("on_voice_member_speaking_start", "on_start")]

        def walk_children(self):
            return ["child"]

    monkeypatch.setattr("utils.real_audio_recorder.WaveSink", DummySink)
    recorder = RealTimeAudioRecorder(SimpleNamespace())

    sink = recorder._create_wave_sink()

    assert sink.__sink_listeners__ == [("on_voice_member_speaking_start", "on_start")]
    assert sink.walk_children() == ["child"]


def test_is_voice_client_recording_supports_new_and_old_api(monkeypatch):
    monkeypatch.setattr("utils.real_audio_recorder.WaveSink", type("DummySink", (), {}))
    recorder = RealTimeAudioRecorder(SimpleNamespace())

    class OldClient:
        recording = True

    class NewClient:
        def is_recording(self):
            return True

    class StoppedClient:
        def is_recording(self):
            return False

    assert recorder._is_voice_client_recording(OldClient()) is True
    assert recorder._is_voice_client_recording(NewClient()) is True
    assert recorder._is_voice_client_recording(StoppedClient()) is False
