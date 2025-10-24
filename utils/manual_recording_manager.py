"""Manual recording session manager built around discord WaveSink."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional
import io
import wave

try:
    from discord.sinks import WaveSink  # type: ignore
except Exception:  # pragma: no cover - discord not available in tests
    WaveSink = None  # type: ignore


class ManualRecordingError(RuntimeError):
    """Raised when manual recording operations fail."""


@dataclass
class ManualRecordingResult:
    guild_id: int
    audio_map: Dict[int, bytes]
    durations: Dict[int, float]
    initiated_by: Optional[int]
    started_at: datetime
    finished_at: datetime
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class ManualRecordingSession:
    guild_id: int
    voice_client: Any
    sink: Any
    initiated_by: Optional[int]
    started_at: datetime
    completion_future: asyncio.Future = field(default_factory=asyncio.Future)
    metadata: Optional[Dict[str, Any]] = None


class ManualRecordingManager:
    """Handles manual recording sessions per guild."""

    def __init__(
        self,
        base_dir: Path | str = Path("recordings/manual"),
        *,
        sink_factory: Optional[Callable[[], Any]] = None,
    ):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._sessions: Dict[int, ManualRecordingSession] = {}
        self._loop = asyncio.get_event_loop()
        self._sink_factory = sink_factory or self._default_sink_factory

    def _default_sink_factory(self):
        if WaveSink is None:
            raise ManualRecordingError(
                "WaveSink is unavailable; ensure py-cord[voice] is installed."
            )
        return WaveSink()

    def has_session(self, guild_id: int) -> bool:
        return guild_id in self._sessions

    async def start_session(
        self,
        *,
        guild_id: int,
        voice_client: Any,
        initiated_by: Optional[int],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ManualRecordingSession:
        if self.has_session(guild_id):
            raise ManualRecordingError("Manual recording already active for this guild.")

        if not hasattr(voice_client, "start_recording"):
            raise ManualRecordingError("Voice client does not support recording.")

        sink = self._sink_factory()
        future: asyncio.Future = self._loop.create_future()
        session = ManualRecordingSession(
            guild_id=guild_id,
            voice_client=voice_client,
            sink=sink,
            initiated_by=initiated_by,
            started_at=datetime.now(UTC),
            completion_future=future,
            metadata=metadata,
        )
        self._sessions[guild_id] = session

        async def finished(recorded_sink):
            await self._handle_finished(session, recorded_sink)

        try:
            voice_client.start_recording(sink, finished)
        except Exception as exc:  # pragma: no cover - start failure
            self._sessions.pop(guild_id, None)
            raise ManualRecordingError(f"Failed to start manual recording: {exc}") from exc

        return session

    async def stop_session(
        self,
        *,
        guild_id: int,
        timeout: float = 15.0,
    ) -> ManualRecordingResult:
        if guild_id not in self._sessions:
            raise ManualRecordingError("No manual recording session found for this guild.")

        session = self._sessions[guild_id]

        try:
            session.voice_client.stop_recording()
        except Exception as exc:  # pragma: no cover - stop failure
            self._sessions.pop(guild_id, None)
            raise ManualRecordingError(f"Failed to stop manual recording: {exc}") from exc

        try:
            result: ManualRecordingResult = await asyncio.wait_for(
                session.completion_future, timeout=timeout
            )
            return result
        except asyncio.TimeoutError as exc:
            self._sessions.pop(guild_id, None)
            raise ManualRecordingError("Timed out while finalising manual recording.") from exc

    async def _handle_finished(
        self,
        session: ManualRecordingSession,
        sink: Any,
    ) -> None:
        audio_map: Dict[int, bytes] = {}
        durations: Dict[int, float] = {}

        try:
            for user_id, audio in getattr(sink, "audio_data", {}).items():
                file_obj = getattr(audio, "file", None)
                if not file_obj:
                    continue
                file_obj.seek(0)
                data = file_obj.read()
                if not data:
                    continue
                audio_map[user_id] = data
                durations[user_id] = self._extract_duration(data)
        finally:
            self._sessions.pop(session.guild_id, None)

        result = ManualRecordingResult(
            guild_id=session.guild_id,
            audio_map=audio_map,
            durations=durations,
            initiated_by=session.initiated_by,
            started_at=session.started_at,
            finished_at=datetime.now(UTC),
            metadata=session.metadata,
        )

        if not session.completion_future.done():
            session.completion_future.set_result(result)

    def _extract_duration(self, wav_bytes: bytes) -> float:
        try:
            with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
                frames = wav_file.getnframes()
                framerate = wav_file.getframerate()
                if framerate:
                    return frames / float(framerate)
        except wave.Error:
            pass
        return 0.0
