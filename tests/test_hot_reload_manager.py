import os
import time
from pathlib import Path

import pytest

from utils.hot_reload import HotReloadManager


def test_collects_changed_extensions(tmp_path):
    target = tmp_path / "dummy_cog.py"
    target.write_text("print('initial')")

    manager = HotReloadManager()
    manager.register_extension("cogs.dummy", target)

    # 初回スキャンでは変更なし
    assert manager.collect_changed_extensions() == []

    time.sleep(0.01)
    target.write_text("print('updated')")

    changed = manager.collect_changed_extensions()
    assert changed == ["cogs.dummy"]

    # 連続呼び出しでは再度検出しない
    assert manager.collect_changed_extensions() == []


def test_missing_file_is_ignored(tmp_path):
    missing = tmp_path / "missing.py"
    manager = HotReloadManager()
    manager.register_extension("cogs.missing", missing)

    assert manager.collect_changed_extensions() == []

    # ファイルが後から出来ても検出できる
    missing.write_text("print('hello')")
    assert manager.collect_changed_extensions() == ["cogs.missing"]
