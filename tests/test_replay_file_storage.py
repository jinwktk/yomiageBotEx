import os
import sys
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from cogs.recording import RecordingCog


@pytest.fixture
def project_root():
    return ROOT_DIR


def test_store_replay_result_saves_to_project_recordings_dir(monkeypatch, tmp_path, project_root):
    config = {"bot": {"rate_limit_delay": [0.1, 0.2]}, "recording": {"enabled": True}}
    bot = SimpleNamespace()

    monkeypatch.chdir(tmp_path)

    cog = RecordingCog(bot, config)

    guild_id = 123456789
    filename = "unit test replay.wav"
    audio_bytes = b"RIFFTESTDATA"

    cog._store_replay_result(
        guild_id=guild_id,
        user_id=None,
        duration=30.0,
        filename=filename,
        normalize=True,
        data=audio_bytes,
    )

    safe_filename = re.sub(r"[^A-Za-z0-9_.-]", "_", filename)
    expected_dir = project_root / "recordings" / "replay" / str(guild_id)
    expected_path = expected_dir / safe_filename

    stored_files = list(expected_dir.glob(f"*{safe_filename}"))
    if expected_path.exists():
        stored_files.insert(0, expected_path)

    try:
        assert stored_files, "録音ファイルがプロジェクト直下のrecordings/replayに保存されていません"
        assert stored_files[0].read_bytes() == audio_bytes
    finally:
        for path in stored_files:
            if path.exists():
                path.unlink()
        if expected_dir.exists() and not any(expected_dir.iterdir()):
            expected_dir.rmdir()
        replay_base = expected_dir.parent
        if replay_base.exists() and not any(replay_base.iterdir()):
            replay_base.rmdir()
