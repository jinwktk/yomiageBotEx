import time
from types import SimpleNamespace

from utils.smooth_audio_relay import SmoothAudioRelay, RelaySession, RelayStatus


def build_relay(threshold_cycles=2, enabled=True):
    config = {
        "audio_relay": {
            "enabled": True,
            "silence_restart": {
                "enabled": enabled,
                "threshold_cycles": threshold_cycles,
            },
        }
    }
    logger = SimpleNamespace(info=lambda *args, **kwargs: None, debug=lambda *args, **kwargs: None)
    logger.warning = logger.info
    logger.error = logger.info
    bot = SimpleNamespace()
    return SmoothAudioRelay(bot, config, logger)


def make_session():
    now = time.time()
    return RelaySession(
        session_id="test",
        source_guild_id=1,
        source_channel_id=2,
        target_guild_id=3,
        target_channel_id=4,
        status=RelayStatus.ACTIVE,
        created_at=now,
        last_activity=now,
    )


def test_silence_restart_triggers_after_threshold():
    relay = build_relay(threshold_cycles=2)
    session = make_session()

    assert relay._update_silence_state(session, has_audio=False, non_bot_present=True) is False
    assert session.silence_cycles == 1

    assert relay._update_silence_state(session, has_audio=False, non_bot_present=True) is True
    assert session.silence_cycles == 0


def test_silence_restart_ignores_when_no_members():
    relay = build_relay(threshold_cycles=2)
    session = make_session()

    assert relay._update_silence_state(session, has_audio=False, non_bot_present=False) is False
    assert session.silence_cycles == 0


def test_silence_restart_resets_on_audio():
    relay = build_relay(threshold_cycles=2)
    session = make_session()
    session.silence_cycles = 1
    before = session.last_audio_time

    assert relay._update_silence_state(session, has_audio=True, non_bot_present=True) is False
    assert session.silence_cycles == 0
    assert session.last_audio_time >= before
