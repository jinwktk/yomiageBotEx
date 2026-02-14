"""Voice receive pipeline compatibility patch for py-cord."""

from __future__ import annotations

import inspect
import logging
from typing import Any, Optional

import discord

try:
    from nacl.exceptions import CryptoError
except Exception:  # pragma: no cover
    CryptoError = None


def _should_patch_rtpsize_decrypt(original_decrypt: Any) -> bool:
    """Return True when decrypt method looks like pre-fix implementation."""
    if not callable(original_decrypt):
        return False
    try:
        source = inspect.getsource(original_decrypt)
    except (OSError, TypeError):
        return False
    # Old path: returns strip_header_ext(...) directly.
    # Newer path (PR #2925) strips 8-byte prefix (r[8:]).
    return "strip_header_ext" in source and "r[8:]" not in source


def apply_voice_receive_patch(logger: Optional[logging.Logger] = None) -> None:
    """
    Patch VoiceClient receive/decrypt behavior for voice recording stability.

    - Relax RTP payload type check to bitmask style.
    - Keep decrypt error handling resilient.
    - Patch AEAD rtpsize decrypt for older py-cord builds.
    """
    log = logger or logging.getLogger(__name__)
    VoiceClient = discord.voice_client.VoiceClient

    if getattr(VoiceClient, "_yomiage_voice_receive_patch", False):
        return

    original_unpack_audio = VoiceClient.unpack_audio
    raw_data_cls = discord.voice_client.RawData

    def patched_unpack_audio(self, data):
        if not data or len(data) < 2:
            return
        # py-cord older builds use strict `!= 0x78` which drops valid packets.
        if data[1] & 0x78 != 0x78:
            return
        if self.paused:
            return
        if not getattr(self, "decoder", None):
            return

        try:
            packet = raw_data_cls(data, self)
        except Exception as err:
            if CryptoError is not None and isinstance(err, CryptoError):
                guild = getattr(getattr(self, "guild", None), "name", "unknown")
                channel = getattr(getattr(self, "channel", None), "name", "unknown")
                log.warning(
                    "Voice decrypt error skipped (guild=%s channel=%s): %s",
                    guild,
                    channel,
                    err,
                )
            else:
                log.warning("Voice packet parse skipped: %s", err)
            return

        if packet.decrypted_data == b"\xf8\xff\xfe":  # Frame of silence
            return

        self.decoder.decode(packet)

    VoiceClient.unpack_audio = patched_unpack_audio

    original_decrypt = getattr(
        VoiceClient,
        "_decrypt_aead_xchacha20_poly1305_rtpsize",
        None,
    )
    if _should_patch_rtpsize_decrypt(original_decrypt):
        def patched_rtpsize_decrypt(self, header, data):
            decrypted = original_decrypt(self, header, data)
            if decrypted is None:
                return decrypted
            if len(decrypted) <= 8:
                return b""
            return decrypted[8:]

        VoiceClient._decrypt_aead_xchacha20_poly1305_rtpsize = patched_rtpsize_decrypt
        log.info("Applied AEAD rtpsize decrypt compatibility patch (8-byte prefix strip).")

    VoiceClient._yomiage_voice_receive_patch = True
    log.info("Applied voice receive pipeline patch for payload/decrypt compatibility.")

