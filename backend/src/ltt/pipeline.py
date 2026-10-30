"""A Session: for each selected Source, one capture and one NeMo realtime connection.

The capture runs for the whole Session. The connection reconnects by itself when it is
lost; the audio of the gap is not transcribed, and the `source_status` "live" event that
follows carries the gap. While a Source is not connected, its audio is not sent to NeMo.
With "Save audio" on, all captured audio is saved (see `ltt.audio`), also during a gap.

The level of each chunk is measured also while the Source is not connected. Each
`source_status` event has the current `warning` ("muted", "silent" or None, see
`ltt.level`), and a change of the warning sends a `source_status` event with the current
state and message.
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Protocol

from ltt.audio import AudioRecorder
from ltt.capture import BYTES_PER_SAMPLE, NS_PER_S, AudioChunk, Capture, CaptureError
from ltt.level import SilenceDetector
from ltt.nemo import EndpointError, NemoConnection, NemoEndpoint
from ltt.sources import Source
from ltt.transcript import LanguageDetector, SourceMapper
from ltt.translation import Translator

log = logging.getLogger(__name__)

RETRY_MIN_S = 1.0
RETRY_MAX_S = 10.0
COMMIT_TIMEOUT_S = 5.0
TRANSLATION_DRAIN_S = 10.0  # at stop, the time to translate the last Segments

Publish = Callable[[dict], None]
ResolveSource = Callable[[str], Source | None]  # the current Source for a key


class AudioCapture(Protocol):
    def chunks(self) -> AsyncIterator[AudioChunk]: ...

    async def stop(self) -> None: ...


CaptureFactory = Callable[[Source], AudioCapture]


class SourcePipeline:
    def __init__(
        self,
        source: Source,
        diarize: bool,
        mapper: SourceMapper,
        endpoint: NemoEndpoint,
        publish: Publish,
        capture_factory: CaptureFactory,
        clock: Callable[[], int] = time.monotonic_ns,
        resolve_source: ResolveSource | None = None,
        recorder: AudioRecorder | None = None,
    ) -> None:
        self.source = source
        self.recorder = recorder
        self.resolve_source = resolve_source
        self.diarize = diarize
        self.mapper = mapper
        self.endpoint = endpoint
        self.publish = publish
        self.capture_factory = capture_factory
        self.clock = clock
        self._conn: NemoConnection | None = None
        self._capture: AudioCapture | None = None
        self._stopping = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._capture_task: asyncio.Task | None = None
        self.silence = SilenceDetector()
        self._state: str | None = None  # of the last source_status event
        self._message: str | None = None
        # A Source that is muted at the start shows "muted" in its first event.
        self.silence.warning = "muted" if source.muted else None

    @property
    def key(self) -> str:
        return self.source.key

    def start(self) -> None:
        self._capture_task = asyncio.create_task(self._capture_loop())
        self._task = asyncio.create_task(self._connection_loop())

    async def stop(self) -> None:
        """Stop the capture, let NeMo finalize the last audio, and close."""
        self._stopping.set()
        if self._capture is not None:
            await self._capture.stop()
        if self._capture_task is not None:
            await _finish(self._capture_task, 2.0)
        conn = self._conn
        if conn is not None:
            with contextlib.suppress(Exception):
                await conn.commit()
        if self._task is not None:
            await _finish(self._task, COMMIT_TIMEOUT_S)
        if self.recorder is not None:
            self.recorder.close()

    def _status(self, state: str, message: str | None = None, **extra) -> None:
        self._state, self._message = state, message
        self.publish(
            {
                "type": "source_status",
                "source_key": self.key,
                "state": state,
                "message": message,
                "warning": self.silence.warning,
                **extra,
            }
        )

    def _measure(self, chunk: AudioChunk) -> None:
        """Update the warning from one chunk; send it if it changed."""
        current = self.resolve_source(self.key) if self.resolve_source else None
        muted = (current or self.source).muted
        if self.silence.feed(chunk, muted) and self._state is not None:
            self._status(self._state, self._message)

    def _session_time(self, ns: int) -> float:
        return round((ns - self.mapper.session_start_ns) / NS_PER_S, 3)

    async def _wait_stop(self, seconds: float) -> bool:
        """Sleep up to `seconds`; return True if the Session is stopping."""
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._stopping.wait(), seconds)
        return self._stopping.is_set()

    async def _capture_loop(self) -> None:
        retry = RETRY_MIN_S
        while not self._stopping.is_set():
            # A device that comes back after a capture error can have a new serial.
            if self.resolve_source is not None:
                self.source = self.resolve_source(self.key) or self.source
            self._capture = self.capture_factory(self.source)
            try:
                async for chunk in self._capture.chunks():
                    retry = RETRY_MIN_S
                    self._measure(chunk)
                    if self.recorder is not None:
                        self.recorder.write(chunk)
                    conn = self._conn
                    if conn is None:
                        continue  # not connected: the audio of the gap is lost
                    self.mapper.audio(chunk.start_ns, len(chunk.pcm) // BYTES_PER_SAMPLE)
                    try:
                        await conn.send_audio(chunk.pcm)
                    except Exception:  # noqa: BLE001 - the reader sees the lost connection
                        pass
            except CaptureError as e:
                log.warning("%s", e)
                self._status("error", f"capture: {e}")
            if self.recorder is not None:
                self.recorder.capture_break()
            if self._stopping.is_set() or await self._wait_stop(retry):
                return
            retry = min(retry * 2, RETRY_MAX_S)

    async def _connection_loop(self) -> None:
        retry = RETRY_MIN_S
        lost_ns: int | None = None  # when the last connection was lost
        message: str | None = None
        while not self._stopping.is_set():
            self._status("connecting", message)
            try:
                await self.endpoint.check(self.diarize)
                conn = await self.endpoint.connect(self.diarize)
            except EndpointError as e:
                message = str(e)
                self._status("error", message)
                if await self._wait_stop(retry):
                    return
                retry = min(retry * 2, RETRY_MAX_S)
                continue
            retry = RETRY_MIN_S
            # No await between these two lines: the capture loop sends the next chunk
            # to the new connection, and the mapper times it from the new TimeMap.
            self.mapper.new_connection()
            self._conn = conn
            extra = {}
            if lost_ns is not None:
                now = self.clock()
                extra["gap"] = {
                    "start": self._session_time(lost_ns),
                    "end": self._session_time(now),
                }
            self._status("live", None, **extra)
            try:
                async for event in conn.events():
                    for out in self.mapper.handle(event):
                        self.publish(out)
                    if event.get("type") == "input_audio_buffer.committed" and (
                        self._stopping.is_set()
                    ):
                        break
            finally:
                self._conn = None
                with contextlib.suppress(Exception):
                    await conn.close()
            if self._stopping.is_set():
                return
            lost_ns = self.clock()
            message = conn.last_error or "connection closed by the endpoint"
            log.warning("%s: %s", self.key, message)
            if await self._wait_stop(RETRY_MIN_S):
                return


async def _finish(task: asyncio.Task, seconds: float) -> None:
    try:
        await asyncio.wait_for(asyncio.shield(task), seconds)
    except TimeoutError:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
    except Exception:  # noqa: BLE001
        log.exception("pipeline task failed")


class Session:
    """One running Session over a fixed set of Sources."""

    def __init__(
        self,
        sources: list[tuple[Source, bool]],  # (Source, diarize)
        endpoint: NemoEndpoint,
        publish: Publish,
        capture_factory: CaptureFactory = Capture,
        detect_language: LanguageDetector | None = None,
        clock: Callable[[], int] = time.monotonic_ns,
        resolve_source: ResolveSource | None = None,
        translator: Callable[[Publish], Translator] | None = None,
        audio_dir: Path | None = None,
        started_at: float | None = None,
    ) -> None:
        """`audio_dir` is the Session directory to save the audio in; None saves none.
        `started_at` is the unix time of the start (default: now)."""
        self.start_ns = clock()
        self.started_at = time.time() if started_at is None else started_at
        self.ended_at: float | None = None
        self.publish = publish
        self.translator = translator(publish) if translator else None
        self.target_lang = self.translator.target_lang if self.translator else None
        self.pipelines = [
            SourcePipeline(
                source,
                diarize,
                SourceMapper(
                    source.key,
                    source.description,
                    diarize,
                    self.start_ns,
                    detect_language or (lambda _text: None),
                ),
                endpoint,
                self._publish_source_event,
                capture_factory,
                clock,
                resolve_source,
                None
                if audio_dir is None
                else AudioRecorder(audio_dir, source.key, self.start_ns, self.publish),
            )
            for source, diarize in sources
        ]

    def _publish_source_event(self, event: dict) -> None:
        self.publish(event)
        if event["type"] == "segment" and self.translator is not None:
            self.translator.submit(event)

    def event(self, state: str) -> dict:
        event = {
            "type": "session",
            "state": state,
            "started_at": self.started_at,
            "target_lang": self.target_lang,
        }
        if state == "stopped":
            event["ended_at"] = self.ended_at
        return event

    def sync(self) -> None:
        """fsync the saved audio that is not on the disk yet."""
        for p in self.pipelines:
            if p.recorder is not None:
                p.recorder.sync()

    def start(self) -> None:
        self.publish(self.event("started"))
        if self.translator is not None:
            self.translator.start()
        for p in self.pipelines:
            p.start()

    async def stop(self) -> None:
        await asyncio.gather(*(p.stop() for p in self.pipelines))
        if self.translator is not None:
            await self.translator.stop(TRANSLATION_DRAIN_S)
        self.ended_at = round(time.time(), 3)
        self.publish(self.event("stopped"))
