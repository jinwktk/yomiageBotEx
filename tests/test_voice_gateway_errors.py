from utils.voice_gateway_errors import (
    extract_voice_close_code,
    is_dave_required_close_code,
)


class _InnerError(Exception):
    def __init__(self, code):
        super().__init__(f"inner code={code}")
        self.code = code


class _OuterError(Exception):
    pass


def test_extract_voice_close_code_from_message_text():
    err = RuntimeError("Shard ID None WebSocket closed with 4017")
    assert extract_voice_close_code(err) == 4017


def test_extract_voice_close_code_from_nested_cause():
    cause = _InnerError(4014)
    err = _OuterError("outer")
    err.__cause__ = cause
    assert extract_voice_close_code(err) == 4014


def test_extract_voice_close_code_returns_none_when_unavailable():
    err = RuntimeError("no close code here")
    assert extract_voice_close_code(err) is None


def test_is_dave_required_close_code_matches_4017_only():
    assert is_dave_required_close_code(4017) is True
    assert is_dave_required_close_code(4014) is False
    assert is_dave_required_close_code(None) is False
