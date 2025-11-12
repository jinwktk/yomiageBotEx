import asyncio
from types import SimpleNamespace

import pytest

from cogs.tts import TTSCog
from utils.dictionary import DictionaryManager


def _reset_manager_state(manager: DictionaryManager):
    manager.global_dictionary.clear()
    manager.guild_dictionaries.clear()
    manager._global_patterns = []
    manager._guild_patterns = {}
    manager._save_dictionaries()


@pytest.mark.asyncio
async def test_greeting_applies_dictionary(monkeypatch, tmp_path):
    monkeypatch.setattr("utils.tts.Path", lambda p: tmp_path / p)

    config = {
        "bot": {"rate_limit_delay": [0, 0]},
        "dictionary": {"file_path": str(tmp_path / "dictionary.json")},
    }

    manager = DictionaryManager(config, dict_file=tmp_path / "dictionary.json")
    _reset_manager_state(manager)
    manager.add_word(123, "Nymeia", "にめいや")

    bot = SimpleNamespace(config=config, dictionary_manager=manager)
    cog = TTSCog(bot, config)

    captured_messages = []

    async def fake_generate_and_play(self, vc, message, settings):
        captured_messages.append(message)

    monkeypatch.setattr(TTSCog, "_generate_and_play_greeting", fake_generate_and_play)

    voice_client = SimpleNamespace()
    member = SimpleNamespace(display_name="Nymeia", guild=SimpleNamespace(id=123))

    await cog.speak_greeting(voice_client, member, "join")
    await asyncio.sleep(0)

    assert captured_messages == ["にめいやさん、こんちゃ！"]
