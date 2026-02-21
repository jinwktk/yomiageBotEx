from types import SimpleNamespace

import pytest

from utils.real_audio_recorder import RealTimeAudioRecorder


@pytest.mark.asyncio
async def test_finished_callback_keeps_status_when_voice_client_still_recording():
    recorder = RealTimeAudioRecorder(None)
    guild_id = 1
    recorder.recording_status[guild_id] = True
    recorder.connections[guild_id] = SimpleNamespace(recording=True)

    sink = SimpleNamespace(audio_data={})
    await recorder._finished_callback(sink, guild_id)

    assert recorder.recording_status[guild_id] is True


@pytest.mark.asyncio
async def test_finished_callback_clears_status_when_not_recording():
    recorder = RealTimeAudioRecorder(None)
    guild_id = 2
    recorder.recording_status[guild_id] = True
    recorder.connections[guild_id] = SimpleNamespace(recording=False)

    sink = SimpleNamespace(audio_data={})
    await recorder._finished_callback(sink, guild_id)

    assert recorder.recording_status[guild_id] is False


def test_apply_recording_config_updates_buffer_retention():
    recorder = RealTimeAudioRecorder(None)

    recorder.apply_recording_config(
        {
            "buffer_expiration_seconds": 120,
            "continuous_buffer_duration_seconds": 120,
        }
    )

    assert recorder.BUFFER_EXPIRATION == 120
    assert recorder.CONTINUOUS_BUFFER_DURATION == 120
