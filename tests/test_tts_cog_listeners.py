from cogs.tts import TTSCog


def test_tts_cog_voice_state_listener_registered():
    assert hasattr(TTSCog.on_voice_state_update, "__cog_listener__"), "on_voice_state_update should be registered as a Cog listener"
