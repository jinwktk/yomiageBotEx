import io
import wave
from datetime import datetime
from types import SimpleNamespace

import pytest

from cogs.recording import RecordingCog
from utils.manual_recording_manager import ManualRecordingResult


def make_wav(duration_seconds: float = 1.0, sample_rate: int = 48000) -> bytes:
    frames = int(sample_rate * duration_seconds)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(2)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x01\x00" * frames * 2)
    return buffer.getvalue()


class StubManualManager:
    def __init__(self):
        self.active = False
        self.start_calls = []
        self.stop_calls = []
        self.result_to_return = None

    def has_session(self, guild_id: int) -> bool:
        return self.active

    async def start_session(self, **kwargs):
        self.active = True
        self.start_calls.append(kwargs)

    async def stop_session(self, *, guild_id: int):
        self.active = False
        self.stop_calls.append(guild_id)
        if self.result_to_return is None:
            raise AssertionError("result_to_return not configured")
        return self.result_to_return


class StubRealTimeRecorder:
    def __init__(self):
        self.recording_status = {}
        self.force_checkpoint_calls = []
        self.stop_calls = []
        self.start_calls = []

    async def force_recording_checkpoint(self, guild_id: int):
        self.force_checkpoint_calls.append(guild_id)
        return True

    async def stop_recording(self, guild_id: int, voice_client=None):
        self.recording_status[guild_id] = False
        self.stop_calls.append((guild_id, voice_client))

    async def start_recording(self, guild_id: int, voice_client):
        self.recording_status[guild_id] = True
        self.start_calls.append((guild_id, voice_client))


class FakeFollowup:
    def __init__(self):
        self.messages = []

    async def send(self, content=None, **kwargs):
        self.messages.append({"content": content, **kwargs})


class FakeContext:
    def __init__(self, author, guild):
        self.author = author
        self.guild = guild
        self.followup = FakeFollowup()
        self.responses = []
        self.deferred = False

    async def respond(self, content, **kwargs):
        self.responses.append({"content": content, **kwargs})

    async def defer(self, **kwargs):
        self.deferred = True


class FakeVoiceState:
    def __init__(self, channel):
        self.channel = channel


class FakeChannel:
    def __init__(self, channel_id=10, name="voice"):
        self.id = channel_id
        self.name = name


class FakeVoiceClient:
    def __init__(self, channel):
        self.channel = channel

    def is_connected(self):
        return True


class FakeGuild:
    def __init__(self, guild_id, voice_client, members=None):
        self.id = guild_id
        self.voice_client = voice_client
        self._members = members or {}

    def get_member(self, user_id):
        return self._members.get(user_id)


class FakeMember:
    def __init__(self, user_id, display_name):
        self.id = user_id
        self.display_name = display_name
        self.mention = f"<@{user_id}>"


def build_cog(tmp_path):
    config = {
        "recording": {"enabled": True},
        "bot": {"rate_limit_delay": [0, 0]},
        "audio_processing": {"normalize": False},
    }
    bot = SimpleNamespace()
    cog = RecordingCog(bot, config)
    cog.manual_recording_dir_base = tmp_path
    cog.manual_recording_manager = StubManualManager()
    cog.real_time_recorder = StubRealTimeRecorder()

    async def no_delay():
        return None

    cog.rate_limit_delay = no_delay
    return cog


@pytest.mark.asyncio
async def test_start_record_command_initiates_manual_session(tmp_path):
    channel = FakeChannel()
    voice_client = FakeVoiceClient(channel)
    author = SimpleNamespace(id=111, voice=FakeVoiceState(channel))
    guild = FakeGuild(42, voice_client)
    ctx = FakeContext(author, guild)

    cog = build_cog(tmp_path)
    cog.real_time_recorder.recording_status[42] = True

    await RecordingCog.start_record_command.callback(cog, ctx, True)

    assert cog.manual_recording_manager.start_calls
    assert cog.manual_recording_context[42]["normalize"] is True
    assert ctx.responses[-1]["content"].startswith("⏺️ 手動録音を開始しました")
    assert cog.real_time_recorder.stop_calls  # real-time recording paused


@pytest.mark.asyncio
async def test_stop_record_command_mixes_audio_and_resumes(tmp_path):
    channel = FakeChannel()
    voice_client = FakeVoiceClient(channel)
    members = {
        1: FakeMember(1, "Alice"),
        2: FakeMember(2, "Bob"),
    }
    guild = FakeGuild(99, voice_client, members=members)
    author = SimpleNamespace(id=500, voice=FakeVoiceState(channel))
    ctx = FakeContext(author, guild)

    cog = build_cog(tmp_path)
    cog.manual_recording_context[99] = {
        "normalize": False,
        "resume_real_time": True,
        "initiated_by": author.id,
    }
    wav_a = make_wav(0.5)
    wav_b = make_wav(0.5)
    cog.manual_recording_manager.active = True
    cog.manual_recording_manager.result_to_return = ManualRecordingResult(
        guild_id=99,
        audio_map={1: wav_a, 2: wav_b},
        durations={1: 0.5, 2: 0.5},
        initiated_by=author.id,
        started_at=datetime.now(),
        finished_at=datetime.now(),
        metadata=None,
    )

    await RecordingCog.stop_record_command.callback(cog, ctx)

    assert ctx.deferred is True
    assert cog.manual_recording_manager.stop_calls == [99]
    assert cog.real_time_recorder.start_calls  # real-time recording resumed
    assert 99 not in cog.manual_recording_context
    followup = ctx.followup.messages[-1]
    assert "🎙️ 手動録音が完了しました" in followup["content"]
    assert followup["ephemeral"] is True
    assert followup["files"]  # combined file attached
    assert any(hasattr(file, "filename") and file.filename.endswith(".wav") for file in followup["files"])

    manual_files = list((tmp_path / "99").glob("*"))
    assert manual_files  # files saved to disk
