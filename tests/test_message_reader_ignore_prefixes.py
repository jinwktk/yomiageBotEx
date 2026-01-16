from types import SimpleNamespace

import pytest

from cogs.message_reader import MessageReaderCog


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["`code", "/slash", ";semi"])
async def test_should_read_message_skips_default_prefixes(tmp_path, monkeypatch, content):
    monkeypatch.setattr("utils.tts.Path", lambda p: tmp_path / p)

    config = {
        "bot": {"rate_limit_delay": [0, 0]},
        "message_reading": {"enabled": True, "max_length": 200},
    }

    dictionary = SimpleNamespace(global_dictionary={}, guild_dictionaries={}, apply_dictionary=lambda text, gid: text)
    bot = SimpleNamespace(config=config, dictionary_manager=dictionary)

    guild = SimpleNamespace(id=1, name="TestGuild")
    message = SimpleNamespace(
        guild=guild,
        author=SimpleNamespace(bot=False, display_name="tester"),
        content=content,
        attachments=[],
        stickers=[],
    )

    cog = MessageReaderCog(bot, config)
    cog.dictionary_manager = dictionary

    assert cog.should_read_message(message) is False
