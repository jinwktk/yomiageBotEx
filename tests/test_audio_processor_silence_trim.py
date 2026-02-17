from utils.audio_processor import AudioProcessor


def test_build_normalize_filter_chain_includes_silenceremove_when_enabled(monkeypatch):
    monkeypatch.setattr(AudioProcessor, "_check_ffmpeg", lambda self: False)
    processor = AudioProcessor(
        {
            "audio_processing": {
                "trim_silence": True,
                "silence_remove_min_duration": 2.0,
                "silence_threshold_db": -45.0,
            }
        }
    )

    filter_chain = processor._build_normalize_filter_chain()

    assert "silenceremove" in filter_chain
    assert "start_duration=2.0" in filter_chain
    assert "stop_duration=2.0" in filter_chain
    assert "start_threshold=-45.0dB" in filter_chain
    assert "stop_threshold=-45.0dB" in filter_chain


def test_build_normalize_filter_chain_skips_silenceremove_when_disabled(monkeypatch):
    monkeypatch.setattr(AudioProcessor, "_check_ffmpeg", lambda self: False)
    processor = AudioProcessor(
        {
            "audio_processing": {
                "trim_silence": False,
            }
        }
    )

    filter_chain = processor._build_normalize_filter_chain()

    assert "silenceremove" not in filter_chain
