"""FastAPI application: REST, the UI WebSocket, and the built frontend."""

import asyncio
import contextlib
import logging
import os
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ltt import __version__
from ltt.capture import Capture
from ltt.nemo import NemoEndpoint
from ltt.pipeline import CaptureFactory, Session
from ltt.sources import Source, SourceRegistry, watch_sources
from ltt.transcript import LanguageDetector, LanguageIdentifier, Transcript

HEARTBEAT_INTERVAL_S = 1.0
DEFAULT_ASR_ENDPOINT_URL = "ws://127.0.0.1:8080"
DEFAULT_LANGUAGES = "en,fr"

log = logging.getLogger(__name__)

SourceMode = Literal["single", "diarize"]
Watcher = Callable[[SourceRegistry, Callable[[list[Source]], Awaitable[None]]], Awaitable[None]]


class SourceSetting(BaseModel):
    selected: bool = False
    mode: SourceMode = "single"


class SourceUpdate(BaseModel):
    selected: bool | None = None
    mode: SourceMode | None = None


class SpeakerUpdate(BaseModel):
    display_name: str | None = None


class SpeakerMerge(BaseModel):
    from_speaker_id: str
    into_speaker_id: str


def default_setting(source: Source) -> SourceSetting:
    # A microphone usually has one speaker; the monitor of an output device carries a call.
    return SourceSetting(mode="single" if source.kind == "microphone" else "diarize")


class Hub:
    """The current Sources, their settings, the Session, and the connected UI sockets."""

    def __init__(self) -> None:
        self.registry = SourceRegistry()
        self.settings: dict[str, SourceSetting] = {}  # by Source key; kept when a device goes
        self.transcript = Transcript()  # the current or last Session
        self.session: Session | None = None  # the running Session
        self._clients: set[asyncio.Queue] = set()

    def sources_payload(self) -> list[dict]:
        out = []
        for s in self.registry.sources():
            setting = self.settings.get(s.key) or default_setting(s)
            out.append(
                {
                    "key": s.key,
                    "kind": s.kind,
                    "description": s.description,
                    **setting.model_dump(),
                }
            )
        return out

    def update(self, key: str, change: SourceUpdate) -> None:
        source = self.registry.get(key)
        if source is None:
            raise KeyError(key)
        setting = self.settings.get(key) or default_setting(source)
        self.settings[key] = setting.model_copy(update=change.model_dump(exclude_none=True))

    def selected_sources(self) -> list[tuple[Source, bool]]:
        """The selected Sources that are present now, each with its diarize flag."""
        out = []
        for s in self.registry.sources():
            setting = self.settings.get(s.key) or default_setting(s)
            if setting.selected:
                out.append((s, setting.mode == "diarize"))
        return out

    async def broadcast_sources(self, _sources: list[Source] | None = None) -> None:
        self._broadcast({"type": "sources", "sources": self.sources_payload()})

    def publish(self, event: dict) -> None:
        """Record a Session event for the snapshot and send it to every UI."""
        self.transcript.apply(event)
        self._broadcast(event)

    def _broadcast(self, msg: dict) -> None:
        for q in self._clients:
            q.put_nowait(msg)

    def subscribe(self) -> tuple[asyncio.Queue, list[dict]]:
        """Return a queue for the live events, and the snapshot that comes before them."""
        q: asyncio.Queue = asyncio.Queue()
        self._clients.add(q)
        return q, self.transcript.snapshot()  # no await in between, so no event is lost

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._clients.discard(q)


async def _run_watcher(watch: Watcher, hub: Hub) -> None:
    try:
        await watch(hub.registry, hub.broadcast_sources)
    except FileNotFoundError:
        log.warning("pw-dump not found: no PipeWire sources")


def create_app(
    watch: Watcher = watch_sources,
    *,
    asr_endpoint_url: str | None = None,
    capture_factory: CaptureFactory = Capture,
    detect_language: LanguageDetector | None = None,
) -> FastAPI:
    """Create the app.

    `asr_endpoint_url` defaults to `LTT_ASR_ENDPOINT_URL`, then to ws://127.0.0.1:8080.
    `detect_language` defaults to lingua, limited to `LTT_LANGUAGES` (default "en,fr").
    """
    hub = Hub()
    endpoint = NemoEndpoint(
        asr_endpoint_url or os.environ.get("LTT_ASR_ENDPOINT_URL") or DEFAULT_ASR_ENDPOINT_URL
    )
    detectors: list[LanguageDetector] = [detect_language] if detect_language else []

    def language_detector() -> LanguageDetector:
        if not detectors:  # built once, at the first Session start
            codes = os.environ.get("LTT_LANGUAGES", DEFAULT_LANGUAGES)
            detectors.append(LanguageIdentifier([c.strip() for c in codes.split(",") if c]))
        return detectors[0]

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        task = asyncio.create_task(_run_watcher(watch, hub))
        yield
        if hub.session is not None:
            await hub.session.stop()
            hub.session = None
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    app = FastAPI(title="live-transcribe-translate", version=__version__, lifespan=lifespan)
    app.state.hub = hub
    app.state.asr_endpoint = endpoint

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok", "version": __version__}

    @app.get("/api/sources")
    async def get_sources() -> list[dict]:
        return hub.sources_payload()

    @app.patch("/api/sources/{key:path}")
    async def patch_source(key: str, change: SourceUpdate) -> list[dict]:
        if hub.session is not None:
            raise HTTPException(409, "source selection and mode are locked during a session")
        try:
            hub.update(key, change)
        except KeyError as e:
            raise HTTPException(404, f"unknown source: {key}") from e
        await hub.broadcast_sources()
        return hub.sources_payload()

    @app.post("/api/session/start")
    async def start_session() -> dict:
        if hub.session is not None:
            raise HTTPException(409, "a session is running")
        sources = hub.selected_sources()
        if not sources:
            raise HTTPException(400, "no source is selected")
        detect = await asyncio.to_thread(language_detector)
        if hub.session is not None:  # started by another request in the meantime
            raise HTTPException(409, "a session is running")
        hub.transcript.reset()
        hub.session = Session(sources, endpoint, hub.publish, capture_factory, detect)
        hub.session.start()
        return hub.session.event("started")

    @app.post("/api/session/stop")
    async def stop_session() -> dict:
        session = hub.session
        if session is None:
            raise HTTPException(409, "no session is running")
        await session.stop()
        hub.session = None
        return session.event("stopped")

    @app.patch("/api/speakers/{speaker_id:path}")
    async def rename_speaker(speaker_id: str, change: SpeakerUpdate) -> dict:
        speaker = hub.transcript.speakers.get(speaker_id)
        if speaker is None:
            raise HTTPException(404, f"unknown speaker: {speaker_id}")
        event = {**speaker, "display_name": (change.display_name or "").strip() or None}
        hub.publish(event)
        return event

    @app.post("/api/speakers/merge")
    async def merge_speakers(merge: SpeakerMerge) -> dict:
        t = hub.transcript
        ids = (merge.from_speaker_id, merge.into_speaker_id)
        for sid in ids:
            if sid not in t.speakers:
                raise HTTPException(404, f"unknown speaker: {sid}")
        if merge.from_speaker_id == merge.into_speaker_id:
            raise HTTPException(400, "a speaker cannot be merged into itself")
        for sid in ids:
            if t.merged_away(sid):
                raise HTTPException(409, f"speaker {sid} is already merged into another")
        event = {"type": "merge", **merge.model_dump()}
        hub.publish(event)
        return event

    @app.websocket("/ws")
    async def ui_socket(ws: WebSocket) -> None:
        """Send hello, the Source list (again after each change), the Session snapshot,
        then the live Session events and a heartbeat."""
        await ws.accept()
        queue, snapshot = hub.subscribe()
        try:
            await ws.send_json({"type": "hello", "version": __version__})
            await ws.send_json({"type": "sources", "sources": hub.sources_payload()})
            for event in snapshot:
                await ws.send_json(event)
            seq = 0
            next_beat = time.monotonic()
            while True:
                timeout = max(0.0, next_beat - time.monotonic())
                try:
                    await ws.send_json(await asyncio.wait_for(queue.get(), timeout))
                except TimeoutError:
                    seq += 1
                    await ws.send_json(
                        {"type": "heartbeat", "seq": seq, "server_time": time.time()}
                    )
                    next_beat += HEARTBEAT_INTERVAL_S
        except WebSocketDisconnect:
            pass
        finally:
            hub.unsubscribe(queue)

    static_dir = Path(
        os.environ.get("LTT_STATIC_DIR", Path(__file__).resolve().parents[3] / "frontend" / "dist")
    )
    # Mounted last so that /api and /ws take precedence. In development Vite serves
    # the frontend, so the directory may not exist.
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")
    return app


app = create_app()
