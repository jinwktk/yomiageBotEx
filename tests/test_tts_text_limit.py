import pytest

from utils.tts import TTSManager


class DummyCache:
    def __init__(self):
        self.requested_text = None

    async def get(self, text, model_id):
        self.requested_text = text
        return None


@pytest.mark.asyncio
async def test_generate_speech_respects_max_text_length(monkeypatch):
    manager = TTSManager(config={})
    manager.tts_config["max_text_length"] = 100
    dummy_cache = DummyCache()
    manager.cache = dummy_cache

    async def fake_is_api_available():
        return False

    manager.is_api_available = fake_is_api_available

    long_text = "A" * 150
    await manager.generate_speech(long_text, model_id=1)

    assert dummy_cache.requested_text is not None
    assert len(dummy_cache.requested_text) <= manager.tts_config["max_text_length"]
    assert dummy_cache.requested_text.endswith("...")
