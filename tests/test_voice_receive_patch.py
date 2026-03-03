import threading
from types import SimpleNamespace

import pytest

import utils.voice_receive_patch as voice_receive_patch


class _DummyDecoder:
    def __init__(self):
        self.calls = []

    def decode(self, packet):
        self.calls.append(packet)


def _build_fake_voice_client():
    class _FakeVoiceClient:
        paused = False

        def __init__(self):
            self.decoder = _DummyDecoder()
            self.mode = "aead_xchacha20_poly1305_rtpsize"
            self.guild = SimpleNamespace(name="g")
            self.channel = SimpleNamespace(name="c")

        def unpack_audio(self, data):
            # old behavior (strict payload type match)
            if data[1] != 0x78:
                return
            self.decoder.decode(data)

        def _decrypt_aead_xchacha20_poly1305_rtpsize(self, header, data):
            return self.strip_header_ext(data)

        @staticmethod
        def strip_header_ext(data):
            return data

        async def on_voice_server_update(self, _data):
            if not self._handshaking:
                await self.ws.close(4000)
                return
            self._voice_server_complete = True

        async def poll_voice_ws(self, _reconnect):
            await self.ws.poll_event()

    return _FakeVoiceClient


class _MissingSentinel:
    pass


class _FakeRawData:
    def __init__(self, data, client):
        self.data = data
        self.client = client
        self.decrypted_data = b"voice"


class _FakeDecodeManager:
    def __init__(self):
        self.decode_queue = [object()]
        self.decoder = {"ssrc": object()}
        self._end_thread = threading.Event()

    @property
    def decoding(self):
        return bool(self.decode_queue)

    def stop(self):
        while self.decoding:
            self.decode_queue.pop(0)
            self.decoder = {}
            print("Decoder Process Killed")
        self._end_thread.set()


def test_voice_receive_patch_accepts_rtp_marker_payload(monkeypatch):
    fake_voice_client = _build_fake_voice_client()
    monkeypatch.setattr(voice_receive_patch, "_resolve_voice_client_class", lambda: fake_voice_client)
    monkeypatch.setattr(voice_receive_patch, "_resolve_raw_data_class", lambda: _FakeRawData)
    voice_receive_patch.apply_voice_receive_patch()

    vc = fake_voice_client()
    # second byte 0xF8 should pass bitmask check (&0x78 == 0x78)
    vc.unpack_audio(bytes([0x80, 0xF8, 0x00, 0x00]))

    assert len(vc.decoder.calls) == 1


def test_voice_receive_patch_ignores_non_audio_payload(monkeypatch):
    fake_voice_client = _build_fake_voice_client()
    monkeypatch.setattr(voice_receive_patch, "_resolve_voice_client_class", lambda: fake_voice_client)
    monkeypatch.setattr(voice_receive_patch, "_resolve_raw_data_class", lambda: _FakeRawData)
    voice_receive_patch.apply_voice_receive_patch()

    vc = fake_voice_client()
    vc.unpack_audio(bytes([0x80, 0x60, 0x00, 0x00]))

    assert len(vc.decoder.calls) == 0


def test_voice_receive_patch_adds_rtpsize_prefix_strip_for_old_impl(monkeypatch):
    fake_voice_client = _build_fake_voice_client()
    monkeypatch.setattr(voice_receive_patch, "_resolve_voice_client_class", lambda: fake_voice_client)
    monkeypatch.setattr(voice_receive_patch, "_resolve_raw_data_class", lambda: _FakeRawData)
    voice_receive_patch.apply_voice_receive_patch()

    vc = fake_voice_client()
    out = vc._decrypt_aead_xchacha20_poly1305_rtpsize(b"h", b"12345678ABCDEFG")

    assert out == b"ABCDEFG"


def test_voice_receive_patch_suppresses_decode_manager_killed_spam(monkeypatch, capsys):
    fake_voice_client = _build_fake_voice_client()
    monkeypatch.setattr(voice_receive_patch, "_resolve_voice_client_class", lambda: fake_voice_client)
    monkeypatch.setattr(voice_receive_patch, "_resolve_raw_data_class", lambda: _FakeRawData)
    monkeypatch.setattr(voice_receive_patch.discord.opus, "DecodeManager", _FakeDecodeManager, raising=False)
    if hasattr(_FakeDecodeManager, "_yomiage_stop_patch_applied"):
        delattr(_FakeDecodeManager, "_yomiage_stop_patch_applied")

    voice_receive_patch.apply_voice_receive_patch()

    manager = _FakeDecodeManager()
    manager.stop()

    captured = capsys.readouterr()
    assert "Decoder Process Killed" not in captured.out
    assert manager._end_thread.is_set()
    assert manager.decode_queue == []


@pytest.mark.asyncio
async def test_voice_receive_patch_ignores_missing_ws_close_in_server_update(monkeypatch):
    fake_voice_client = _build_fake_voice_client()
    monkeypatch.setattr(voice_receive_patch, "_resolve_voice_client_class", lambda: fake_voice_client)
    monkeypatch.setattr(voice_receive_patch, "_resolve_raw_data_class", lambda: _FakeRawData)
    voice_receive_patch.apply_voice_receive_patch()

    vc = fake_voice_client()
    vc._handshaking = False
    vc.ws = _MissingSentinel()

    await vc.on_voice_server_update({"guild_id": "1"})


@pytest.mark.asyncio
async def test_voice_receive_patch_ignores_missing_ws_poll_event(monkeypatch):
    fake_voice_client = _build_fake_voice_client()
    monkeypatch.setattr(voice_receive_patch, "_resolve_voice_client_class", lambda: fake_voice_client)
    monkeypatch.setattr(voice_receive_patch, "_resolve_raw_data_class", lambda: _FakeRawData)
    voice_receive_patch.apply_voice_receive_patch()

    vc = fake_voice_client()
    vc.ws = _MissingSentinel()

    await vc.poll_voice_ws(True)
