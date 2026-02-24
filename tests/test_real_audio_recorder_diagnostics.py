from types import SimpleNamespace

from utils.real_audio_recorder import RealTimeAudioRecorder


def test_get_voice_diagnostics_includes_member_voice_flags():
    recorder = RealTimeAudioRecorder(None)
    guild_id = 9999

    member = SimpleNamespace(
        id=123,
        display_name="The Arukkadion",
        bot=False,
        voice=SimpleNamespace(
            self_mute=False,
            self_deaf=False,
            mute=False,
            deaf=False,
            suppress=False,
            channel=SimpleNamespace(id=55, name="おもちだいすきクラブ"),
        ),
    )
    vc = SimpleNamespace(
        channel=SimpleNamespace(id=55, name="おもちだいすきクラブ", members=[member]),
        is_connected=lambda: True,
        recording=True,
        mode="aead_xchacha20_poly1305_rtpsize",
        ws=SimpleNamespace(ssrc_map={111: 123}),
    )
    recorder.connections[guild_id] = vc
    recorder.recording_status[guild_id] = True

    snapshot = recorder.get_voice_diagnostics(guild_id, target_user_id=123)

    assert snapshot["voice_client_connected"] is True
    assert snapshot["voice_client_recording"] is True
    assert snapshot["voice_mode"] == "aead_xchacha20_poly1305_rtpsize"
    assert snapshot["ssrc_map_size"] == 1
    assert snapshot["target_user"]["display_name"] == "The Arukkadion"
    assert snapshot["target_user"]["voice"]["self_mute"] is False
    assert snapshot["target_user"]["voice"]["channel_id"] == 55


def test_get_voice_diagnostics_handles_missing_connection():
    recorder = RealTimeAudioRecorder(None)
    snapshot = recorder.get_voice_diagnostics(12345, target_user_id=1)

    assert snapshot["guild_id"] == 12345
    assert snapshot["voice_client_present"] is False
    assert snapshot["target_user"] is None
