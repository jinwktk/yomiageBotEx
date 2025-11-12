from types import SimpleNamespace

import pytest

from cogs.dictionary import DictionaryCog
from cogs.message_reader import MessageReaderCog
from utils.dictionary import DictionaryManager


@pytest.fixture
def shared_config(tmp_path):
    dict_path = tmp_path / "dictionary.json"
    return {
        "dictionary": {
            "file_path": str(dict_path),
            "max_words_per_guild": 10,
            "max_word_length": 50,
            "max_reading_length": 100,
        },
        "message_reading": {
            "enabled": True,
            "max_length": 100,
            "ignore_prefixes": [],
            "ignore_bots": False,
        },
        "bot": {
            "rate_limit_delay": [0, 0],
        },
    }


def _reset_manager_state(manager: DictionaryManager):
    manager.global_dictionary.clear()
    manager.guild_dictionaries.clear()
    manager._global_patterns = []
    manager._guild_patterns = {}
    manager._save_dictionaries()


def test_cogs_share_dictionary_manager_for_realtime_updates(shared_config, tmp_path, monkeypatch):
    monkeypatch.setattr("utils.tts.Path", lambda p: tmp_path / p)

    shared_manager = DictionaryManager(shared_config, dict_file=tmp_path / "dictionary.json")
    _reset_manager_state(shared_manager)

    bot = SimpleNamespace(
        config=shared_config,
        dictionary_manager=shared_manager,
        connect_voice_safely=None,
    )

    reader_cog = MessageReaderCog(bot, shared_config)
    dictionary_cog = DictionaryCog(bot, shared_config)

    assert reader_cog.dictionary_manager is shared_manager
    assert dictionary_cog.dictionary_manager is shared_manager

    shared_manager.add_word(123, "テスト", "てすと")

    applied = reader_cog.dictionary_manager.apply_dictionary("テスト", 123)
    assert applied == "てすと"
