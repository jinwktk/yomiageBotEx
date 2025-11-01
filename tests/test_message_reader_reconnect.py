import asyncio
from types import SimpleNamespace

import pytest

from cogs.message_reader import MessageReaderCog


class DummyMember:
    def __init__(self, *, bot: bool):
        self.bot = bot


class DummyChannel:
    def __init__(self, name: str, members):
        self.name = name
        self.members = members


class DummyVoiceClient:
    def __init__(self, channel, connected: bool):
        self.channel = channel
        self._connected = connected
        self.disconnect_called = False

    def is_connected(self):
        return self._connected

    async def disconnect(self, force: bool = False):
        self.disconnect_called = True


class DummyHandshakingVoiceClient(DummyVoiceClient):
    def __init__(self, channel):
        super().__init__(channel, connected=False)
        self._connect_attempts = 0


class DummyGuild:
    def __init__(self, *, voice_client, channels):
        self.name = "テストギルド"
        self.voice_client = voice_client
        self.voice_channels = channels


@pytest.mark.asyncio
async def test_attempt_auto_reconnect_keeps_existing_connection_when_no_targets(tmp_path, monkeypatch):
    # bot/configの最低限のスタブを用意
    config = {
        "message_reading": {
            "enabled": True,
            "max_length": 100,
            "ignore_prefixes": [],
            "ignore_bots": False,
        }
    }

    # TTS設定ファイルをtmpに向けるため、MessageReaderCogが参照するパスをモック
    monkeypatch.setattr("utils.tts.Path", lambda p: tmp_path / p)

    bot = SimpleNamespace(connect_voice_safely=None, config=config)
    cog = MessageReaderCog(bot, config)

    # 既存クライアントは「接続済みだが状態不良」という想定でis_connected=False
    channel = DummyChannel("vc", [DummyMember(bot=True)])
    voice_client = DummyVoiceClient(channel, connected=False)
    guild = DummyGuild(voice_client=voice_client, channels=[channel])

    result = await cog._attempt_auto_reconnect(guild)

    assert result is False
    assert voice_client.disconnect_called is False


@pytest.mark.asyncio
async def test_attempt_auto_reconnect_waits_for_handshake(tmp_path, monkeypatch):
    config = {
        "message_reading": {
            "enabled": True,
            "max_length": 100,
            "ignore_prefixes": [],
            "ignore_bots": False,
        }
    }

    monkeypatch.setattr("utils.tts.Path", lambda p: tmp_path / p)

    bot = SimpleNamespace(connect_voice_safely=None, config=config)
    # ハンドシェイク中は非Botメンバーがいることが条件
    channel = DummyChannel("vc", [DummyMember(bot=False)])
    voice_client = DummyHandshakingVoiceClient(channel)
    guild = DummyGuild(voice_client=voice_client, channels=[channel])

    async def fake_sleep(duration):
        voice_client._connect_attempts += 1
        # 1回目の待機後に接続完了したとみなす
        if voice_client._connect_attempts == 1:
            voice_client._connected = True

    monkeypatch.setattr("asyncio.sleep", fake_sleep)

    cog = MessageReaderCog(bot, config)

    result = await cog._attempt_auto_reconnect(guild)

    assert result is True
    # ハンドシェイク完了まで待機してから接続を再利用するため、切断は呼ばれない
    assert voice_client.disconnect_called is False
