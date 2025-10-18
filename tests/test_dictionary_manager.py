import pytest

from utils.dictionary import DictionaryManager


@pytest.fixture
def base_config():
    return {
        "dictionary": {
            "max_words_per_guild": 2,
            "max_word_length": 10,
            "max_reading_length": 10,
        }
    }


@pytest.fixture
def manager(tmp_path, base_config):
    dict_path = tmp_path / "dictionary.json"
    manager = DictionaryManager(base_config, dict_file=dict_path)
    manager.global_dictionary.clear()
    manager.guild_dictionaries.clear()
    manager._global_patterns = []
    manager._guild_patterns = {}
    manager._save_dictionaries()
    return manager


def test_add_and_remove_guild_word(manager):
    guild_id = 123
    assert manager.add_word(guild_id, "sample", "reading")
    assert manager.get_guild_dictionary(guild_id)["sample"] == "reading"

    assert manager.remove_word(guild_id, "sample")
    assert "sample" not in manager.get_guild_dictionary(guild_id)


def test_apply_dictionary_prefers_guild_entries(manager):
    assert manager.add_word(None, "hello", "global")
    assert manager.add_word(456, "hello", "guild")

    result = manager.apply_dictionary("HELLO world", 456)
    assert result == "guild world"


def test_add_word_respects_length_limits(tmp_path, base_config):
    config = {
        "dictionary": {
            **base_config["dictionary"],
            "max_word_length": 3,
            "max_reading_length": 4,
        }
    }
    manager = DictionaryManager(config, dict_file=tmp_path / "length_limits.json")
    manager.global_dictionary.clear()
    manager.guild_dictionaries.clear()
    manager._global_patterns = []
    manager._guild_patterns = {}
    manager._save_dictionaries()

    assert not manager.add_word(None, "toolong", "ok")
    assert not manager.add_word(1, "term", "toolong")


def test_add_word_enforces_guild_capacity(manager):
    guild_id = 789
    assert manager.add_word(guild_id, "first", "one")
    assert manager.add_word(guild_id, "second", "two")
    assert not manager.add_word(guild_id, "third", "three")


def test_add_word_enforces_global_capacity(manager):
    assert manager.add_word(None, "alpha", "a")
    assert manager.add_word(None, "beta", "b")
    assert not manager.add_word(None, "gamma", "g")


def test_apply_dictionary_updates_after_changes(manager):
    assert manager.add_word(None, "Test", "テンプレ")
    assert manager.apply_dictionary("test message", None) == "テンプレ message"

    assert manager.remove_word(None, "Test")
    assert manager.apply_dictionary("test message", None) == "test message"
