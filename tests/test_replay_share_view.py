from types import SimpleNamespace

import pytest

from cogs.recording import ReplayShareView


class FakeResponse:
    def __init__(self):
        self.messages = []

    async def send_message(self, content=None, **kwargs):
        payload = {"content": content}
        payload.update(kwargs)
        self.messages.append(payload)


class FakeChannel:
    def __init__(self):
        self.messages = []

    async def send(self, content=None, **kwargs):
        payload = {"content": content}
        payload.update(kwargs)
        self.messages.append(payload)


class FakeInteraction:
    def __init__(self, user_id: int):
        self.user = SimpleNamespace(id=user_id)
        self.channel = FakeChannel()
        self.response = FakeResponse()


@pytest.mark.asyncio
async def test_replay_share_view_posts_public_message(monkeypatch):
    sent_files = []

    class DummyFile:
        def __init__(self, fp, filename):
            sent_files.append({"fp": fp, "filename": filename})
            self.fp = fp
            self.filename = filename

    monkeypatch.setattr("cogs.recording.discord.File", DummyFile)

    view = ReplayShareView(
        requester_id=111,
        filename="replay_test.wav",
        audio_data=b"RIFFdummy",
        public_content="🎵 公開リプレイです",
    )
    interaction = FakeInteraction(user_id=111)

    await view.children[0].callback(interaction)

    assert interaction.channel.messages, "公開メッセージが送信されていません"
    assert interaction.channel.messages[-1]["content"] == "🎵 公開リプレイです"
    assert sent_files and sent_files[-1]["filename"] == "replay_test.wav"
    assert interaction.response.messages, "ボタン押下時の応答が返っていません"
    assert "送信しました" in interaction.response.messages[-1]["content"]


@pytest.mark.asyncio
async def test_replay_share_view_rejects_non_requester(monkeypatch):
    class DummyFile:
        def __init__(self, fp, filename):
            self.fp = fp
            self.filename = filename

    monkeypatch.setattr("cogs.recording.discord.File", DummyFile)

    view = ReplayShareView(
        requester_id=111,
        filename="replay_test.wav",
        audio_data=b"RIFFdummy",
        public_content="🎵 公開リプレイです",
    )
    interaction = FakeInteraction(user_id=222)

    await view.children[0].callback(interaction)

    assert not interaction.channel.messages, "実行者以外で公開送信されてしまいました"
    assert interaction.response.messages, "拒否応答が返っていません"
    assert "実行者のみ" in interaction.response.messages[-1]["content"]
