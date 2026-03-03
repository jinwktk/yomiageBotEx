"""Voice gateway error helpers."""

from __future__ import annotations

import re
from typing import Optional


_CLOSE_CODE_PATTERN = re.compile(r"\b(4\d{3})\b")


def extract_voice_close_code(error: BaseException | None) -> Optional[int]:
    """Extract a voice websocket close code from nested exceptions."""
    if error is None:
        return None

    stack: list[BaseException] = [error]
    visited: set[int] = set()

    while stack:
        current = stack.pop()
        marker = id(current)
        if marker in visited:
            continue
        visited.add(marker)

        for attr in ("code", "close_code"):
            raw = getattr(current, attr, None)
            if isinstance(raw, int):
                return raw
            if isinstance(raw, str) and raw.isdigit():
                return int(raw)

        ws_obj = getattr(current, "ws", None)
        if ws_obj is not None:
            for attr in ("close_code", "code"):
                raw = getattr(ws_obj, attr, None)
                if isinstance(raw, int):
                    return raw
                if isinstance(raw, str) and raw.isdigit():
                    return int(raw)

        match = _CLOSE_CODE_PATTERN.search(str(current))
        if match:
            return int(match.group(1))

        cause = getattr(current, "__cause__", None)
        context = getattr(current, "__context__", None)
        if isinstance(cause, BaseException):
            stack.append(cause)
        if isinstance(context, BaseException):
            stack.append(context)

    return None


def is_dave_required_close_code(close_code: int | None) -> bool:
    """Return True when close code indicates DAVE-required rejection."""
    return close_code == 4017
