from types import SimpleNamespace

from utils.voice_receive_patch import apply_voice_receive_patch


class _DummyDecoder:
    def __init__(self):
        self.calls = []

    def decode(self, packet):
        self.calls.append(packet)


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


class _FakeRawData:
    def __init__(self, data, client):
        self.data = data
        self.client = client
        self.decrypted_data = b"voice"


def test_voice_receive_patch_accepts_rtp_marker_payload(monkeypatch):
    monkeypatch.setattr("discord.voice_client.VoiceClient", _FakeVoiceClient)
    monkeypatch.setattr("discord.voice_client.RawData", _FakeRawData)

    apply_voice_receive_patch()

    vc = _FakeVoiceClient()
    # second byte 0xF8 should pass bitmask check (&0x78 == 0x78)
    vc.unpack_audio(bytes([0x80, 0xF8, 0x00, 0x00]))

    assert len(vc.decoder.calls) == 1


def test_voice_receive_patch_ignores_non_audio_payload(monkeypatch):
    monkeypatch.setattr("discord.voice_client.VoiceClient", _FakeVoiceClient)
    monkeypatch.setattr("discord.voice_client.RawData", _FakeRawData)

    apply_voice_receive_patch()

    vc = _FakeVoiceClient()
    vc.unpack_audio(bytes([0x80, 0x60, 0x00, 0x00]))

    assert len(vc.decoder.calls) == 0


def test_voice_receive_patch_adds_rtpsize_prefix_strip_for_old_impl(monkeypatch):
    monkeypatch.setattr("discord.voice_client.VoiceClient", _FakeVoiceClient)
    monkeypatch.setattr("discord.voice_client.RawData", _FakeRawData)

    apply_voice_receive_patch()

    vc = _FakeVoiceClient()
    out = vc._decrypt_aead_xchacha20_poly1305_rtpsize(b"h", b"12345678ABCDEFG")

    assert out == b"ABCDEFG"
