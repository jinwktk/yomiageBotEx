from pathlib import Path


def test_start_sh_uses_project_environment():
    content = Path("scripts/start.sh").read_text(encoding="utf-8")
    assert "uv run python bot.py" in content
    assert "uv run --no-project python bot.py" not in content


def test_start_bat_uses_project_environment():
    content = Path("scripts/start.bat").read_text(encoding="utf-8")
    assert "uv run python bot.py" in content
    assert "uv run --no-project python bot.py" not in content
