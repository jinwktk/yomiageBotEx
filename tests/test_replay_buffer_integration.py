import io
import time
from types import SimpleNamespace

import pytest

from cogs.recording import RecordingCog
from utils.replay_buffer_manager import ReplayResult


def make_wav(duration_seconds: float = 1.0, sample_rate: int = 48000) -> bytes:
    import wave

    frames = int(sample_rate * duration_seconds)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x01\x00" * frames)
    return buffer.getvalue()


class ExplodingRecorder:
    def __init__(self):
        self.connections = {
            123: SimpleNamespace(recording=True),
        }
        self.accessed = False
        self.force_checkpoint_calls = []

    def get_audio_for_time_range(self, *args, **kwargs):
        self.accessed = True
        raise AssertionError("fallback recorder should not be used when replay buffer manager succeeds")

    async def clean_old_buffers(self, guild_id):
        pass

    async def force_recording_checkpoint(self, guild_id: int):
        self.force_checkpoint_calls.append(guild_id)
        return True


class FakeFollowup:
    def __init__(self):
        self.messages = []

    async def send(self, content=None, **kwargs):
        payload = {"content": content}
        payload.update(kwargs)
        self.messages.append(payload)


class FakeContext:
    def __init__(self, guild_id: int):
        self.guild = SimpleNamespace(id=guild_id, name="guild")
        self.followup = FakeFollowup()
        self.user = SimpleNamespace(display_name="tester")


class FakeReplayBufferManager:
    def __init__(self, audio_bytes: bytes):
        self.audio_bytes = audio_bytes
        self.calls = []

    async def get_replay_audio(self, **kwargs):
        self.calls.append(kwargs)
        return ReplayResult(
            audio_data=self.audio_bytes,
            total_duration=kwargs.get("duration_seconds", 0.0),
            user_count=1,
            file_size=len(self.audio_bytes),
            sample_rate=48000,
            channels=1,
            generation_time=time.time(),
        )


class FakeUser:
    def __init__(self, user_id: int, display_name: str):
        self.id = user_id
        self.display_name = display_name
        self.mention = f"<@{user_id}>"


@pytest.mark.asyncio
async def test_replay_prefers_replay_buffer_manager(monkeypatch, tmp_path):
    config = {
        "recording": {"enabled": True},
        "bot": {"rate_limit_delay": [0, 0]},
        "audio_processing": {"normalize": True},
    }
    bot = SimpleNamespace()
    cog = RecordingCog(bot, config)
    cog.replay_dir_base = tmp_path / "replay"
    cog.replay_dir_base.mkdir(parents=True, exist_ok=True)
    cog.real_time_recorder = ExplodingRecorder()

    audio_bytes = make_wav()
    fake_manager = FakeReplayBufferManager(audio_bytes)
    cog._replay_buffer_manager_override = fake_manager

    sent_files = []

    class DummyFile:
        def __init__(self, fp, filename):
            sent_files.append(filename)
            self.fp = fp
            self.filename = filename

    monkeypatch.setattr("cogs.recording.discord.File", DummyFile)

    ctx = FakeContext(guild_id=123)
    user = FakeUser(42, "ソルト・ライオモッチ")

    await cog._process_replay_async(ctx, duration=30.0, user=user, normalize=True)

    assert fake_manager.calls, "ReplayBufferManager を呼び出していません"
    assert sent_files, "Discord.File が作成されていません"
    assert ctx.followup.messages, "フォローアップ応答が送信されていません"
    assert ctx.followup.messages[-1].get("view") is not None, "公開送信用ボタンViewが付与されていません"
    assert cog.real_time_recorder.force_checkpoint_calls == [123], "Replay開始時チェックポイントが実行されていません"
    assert not cog.real_time_recorder.accessed, "ReplayBufferManager 成功時に旧システムへフォールバックしています"
