"""Simple hot-reload support for Discord cogs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class _WatchEntry:
    path: Path
    last_mtime: Optional[float]


class HotReloadManager:
    """Tracks extension files and reports which ones have changed."""

    def __init__(self) -> None:
        self._entries: Dict[str, _WatchEntry] = {}

    def register_extension(self, extension: str, path: Path | str) -> None:
        """Register an extension file to watch."""
        resolved = Path(path)
        last_mtime = self._read_mtime(resolved)
        self._entries[extension] = _WatchEntry(path=resolved, last_mtime=last_mtime)

    def collect_changed_extensions(self) -> List[str]:
        """Return a list of extensions whose file(s) changed since last check."""
        changed: List[str] = []
        for name, entry in self._entries.items():
            current_mtime = self._read_mtime(entry.path)

            if current_mtime is None:
                # File disappeared: keep waiting until it returns
                entry.last_mtime = None
                continue

            if entry.last_mtime is None:
                # Previously missing, now present: treat as change
                entry.last_mtime = current_mtime
                changed.append(name)
                continue

            if current_mtime > entry.last_mtime + 1e-9:
                entry.last_mtime = current_mtime
                changed.append(name)

        return changed

    @staticmethod
    def _read_mtime(path: Path) -> Optional[float]:
        try:
            return path.stat().st_mtime
        except FileNotFoundError:
            return None

