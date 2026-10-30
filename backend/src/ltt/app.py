"""FastAPI application: REST, the UI WebSocket, and the built frontend."""

import asyncio
import contextlib
import logging
import os
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ltt import __version__
from ltt.capture import Capture
from ltt.export import SessionExport
from ltt.nemo import NemoEndpoint
from ltt.pipeline import CaptureFactory, Session
from ltt.sources import Source, SourceRegistry, watch_sources
from ltt.store import (
    FSYNC_INTERVAL_S,
    SavedSession,
    SessionLog,
    SessionStore,
    default_data_dir,
)
from ltt.transcript import LanguageDetector, LanguageIdentifier, Transcript
from ltt.translation import (
    DEFAULT_TARGET_LANGUAGE,
    TARGET_LANGUAGES,
    TranslationEndpoint,
    Translator,
    normalize_target,
)

HEARTBEAT_INTERVAL_S = 1.0
DEFAULT_ASR_ENDPOINT_URL = "ws://127.0.0.1:8080"
DEFAULT_LANGUAGES = "en,fr"

log = logging.getLogger(__name__)

SourceMode = Literal["single", "diarize"]
ExportFormat = Literal["md", "json"]
Watcher = Callable[[SourceRegistry, Callable[[list[Source]], Awaitable[None]]], Awaitable[None]]


class SourceSetting(BaseModel):
    selected: bool = False
    mode: SourceMode = "single"


class SourceUpdate(BaseModel):
    selected: bool | None = None
    mode: SourceMode | None = None


class SessionStart(BaseModel):
    target_language: str = DEFAULT_TARGET_LANGUAGE
    save_audio: bool = True


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

    def __init__(self, store: SessionStore) -> None:
        self.registry = SourceRegistry()
        self.settings: dict[str, SourceSetting] = {}  # by Source key; kept when a device goes
        self.transcript = Transcript()  # the current or last Session
        self.session: Session | None = None  # the running Session
        self.store = store
        # The log of the current or last Session. It stays open after the stop, so that a
        # rename or a merge of the last Session is saved too, until the next start.
        self.log: SessionLog | None = None
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
        """Record a Session event for the snapshot and in the log, and send it to every UI."""
        self.transcript.apply(event)
        if self.log is not None:
            try:
                self.log.append(event)
            except OSError as e:
                log.error("cannot write the session log: %s", e)
        self._broadcast(event)

    def forget_last_session(self) -> None:
        """The last Session was deleted: clear it. A new `hello` makes each UI clear its
        state, as on a new connection; the snapshot that follows is empty."""
        self.close_log()
        self.transcript.reset()
        self._broadcast({"type": "hello", "version": __version__})

    def close_log(self) -> None:
        if self.log is not None:
            self.log.close()
            self.log = None

    def sync(self) -> None:
        """fsync the log and the saved audio of the Session."""
        try:
            if self.log is not None:
                self.log.sync()
            if self.session is not None:
                self.session.sync()
        except OSError as e:
            log.error("cannot sync the session files: %s", e)

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


def check_merge(t: Transcript, merge: SpeakerMerge) -> None:
    """Raise HTTPException unless the Merge is valid in the Session of `t`."""
    ids = (merge.from_speaker_id, merge.into_speaker_id)
    for sid in ids:
        if sid not in t.speakers:
            raise HTTPException(404, f"unknown speaker: {sid}")
    if merge.from_speaker_id == merge.into_speaker_id:
        raise HTTPException(400, "a speaker cannot be merged into itself")
    for sid in ids:
        if t.merged_away(sid):
            raise HTTPException(409, f"speaker {sid} is already merged into another")


def export_response(t: Transcript, session_id: str, fmt: ExportFormat) -> Response:
    """The Markdown or JSON export of a Session, as a download named `<session_id>.<fmt>`."""
    export = SessionExport(t, session_id, now=time.time())
    if fmt == "json":
        body, media_type = export.json(), "application/json"
    else:
        body, media_type = export.markdown(), "text/markdown; charset=utf-8"
    return Response(
        body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{session_id}.{fmt}"'},
    )


def renamed(t: Transcript, speaker_id: str, change: SpeakerUpdate) -> dict:
    """The `speaker` event of a rename; raise HTTPException for an unknown Speaker."""
    speaker = t.speakers.get(speaker_id)
    if speaker is None:
        raise HTTPException(404, f"unknown speaker: {speaker_id}")
    return {**speaker, "display_name": (change.display_name or "").strip() or None}


async def _sync_loop(hub: Hub) -> None:
    while True:
        await asyncio.sleep(FSYNC_INTERVAL_S)
        hub.sync()


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
    translation_endpoint_url: str | None = None,
    data_dir: Path | str | None = None,
) -> FastAPI:
    """Create the app.

    `asr_endpoint_url` defaults to `LTT_ASR_ENDPOINT_URL`, then to ws://127.0.0.1:8080.
    `translation_endpoint_url` defaults to `LTT_TRANSLATION_ENDPOINT_URL`, then to the
    http:// form of the ASR endpoint (the same NeMo-Speech.cpp server).
    `detect_language` defaults to lingua, limited to `LTT_LANGUAGES` (default "en,fr").
    `data_dir` defaults to `LTT_DATA_DIR`, then to `$XDG_DATA_HOME/live-transcribe-translate`.
    """
    hub = Hub(SessionStore(Path(data_dir) if data_dir else default_data_dir()))
    store = hub.store
    endpoint = NemoEndpoint(
        asr_endpoint_url or os.environ.get("LTT_ASR_ENDPOINT_URL") or DEFAULT_ASR_ENDPOINT_URL
    )
    translation_endpoint = TranslationEndpoint(
        translation_endpoint_url
        or os.environ.get("LTT_TRANSLATION_ENDPOINT_URL")
        or endpoint.http_url
    )
    detectors: list[LanguageDetector] = [detect_language] if detect_language else []

    def language_detector() -> LanguageDetector:
        if not detectors:  # built once, at the first Session start
            codes = os.environ.get("LTT_LANGUAGES", DEFAULT_LANGUAGES)
            detectors.append(LanguageIdentifier([c.strip() for c in codes.split(",") if c]))
        return detectors[0]

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # A log with no stop line is from an app that ended without a stop.
        await asyncio.to_thread(store.recover)
        tasks = [
            asyncio.create_task(_run_watcher(watch, hub)),
            asyncio.create_task(_sync_loop(hub)),
        ]
        yield
        if hub.session is not None:
            await hub.session.stop()
            hub.session = None
        hub.close_log()
        for task in tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title="live-transcribe-translate", version=__version__, lifespan=lifespan)
    app.state.hub = hub
    app.state.asr_endpoint = endpoint
    app.state.translation_endpoint = translation_endpoint
    app.state.store = store

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
    async def start_session(start: SessionStart | None = None) -> dict:
        if hub.session is not None:
            raise HTTPException(409, "a session is running")
        start = start or SessionStart()
        requested = start.target_language
        target = normalize_target(requested)
        if target is None:
            raise HTTPException(
                400,
                f"unsupported target language: {requested}; use one of "
                + ", ".join(TARGET_LANGUAGES),
            )
        sources = hub.selected_sources()
        if not sources:
            raise HTTPException(400, "no source is selected")
        detect = await asyncio.to_thread(language_detector)
        if hub.session is not None:  # started by another request in the meantime
            raise HTTPException(409, "a session is running")
        started_at = time.time()
        try:
            session_log = store.create(started_at)
        except OSError as e:
            raise HTTPException(500, f"cannot create the session directory: {e}") from e
        hub.close_log()
        hub.transcript.reset()
        hub.log = session_log  # before start(), which publishes the "started" event
        hub.session = Session(
            sources,
            endpoint,
            hub.publish,
            capture_factory,
            detect,
            resolve_source=hub.registry.get,
            translator=lambda publish: Translator(translation_endpoint, target, publish),
            audio_dir=session_log.dir if start.save_audio else None,
            started_at=started_at,
        )
        hub.session.start()
        return hub.session.event("started")

    @app.post("/api/session/stop")
    async def stop_session() -> dict:
        session = hub.session
        if session is None:
            raise HTTPException(409, "no session is running")
        await session.stop()
        hub.session = None
        hub.sync()
        return session.event("stopped")

    @app.patch("/api/speakers/{speaker_id:path}")
    async def rename_speaker(speaker_id: str, change: SpeakerUpdate) -> dict:
        event = renamed(hub.transcript, speaker_id, change)
        hub.publish(event)
        return event

    @app.post("/api/speakers/merge")
    async def merge_speakers(merge: SpeakerMerge) -> dict:
        check_merge(hub.transcript, merge)
        event = {"type": "merge", **merge.model_dump()}
        hub.publish(event)
        return event

    @app.get("/api/session/export")
    async def export_live_session(format: ExportFormat = "md") -> Response:  # noqa: A002
        """The current or last Session; a running Session is a snapshot of the moment."""
        if hub.transcript.session is None or hub.log is None:
            raise HTTPException(404, "no session")
        return export_response(hub.transcript, hub.log.id, format)

    # Past Sessions: the saved logs. The running Session is not a past Session.

    def running_id() -> str | None:
        return hub.log.id if hub.session is not None and hub.log is not None else None

    def past(session_id: str) -> SavedSession:
        if session_id == running_id():
            raise HTTPException(409, "this session is running")
        saved = store.load(session_id)
        if saved is None:
            raise HTTPException(404, f"unknown session: {session_id}")
        return saved

    def record(session_id: str, event: dict) -> None:
        """Append a change to a past Session's log. For the last live Session, publish it,
        so that the /ws snapshot and the UIs have it too."""
        if hub.log is not None and session_id == hub.log.id:
            hub.publish(event)
        else:
            store.append(session_id, event)

    @app.get("/api/sessions")
    async def list_sessions() -> list[dict]:
        skip = running_id()
        out = []
        for sid in store.ids():
            if sid == skip:
                continue
            saved = store.load(sid)
            if saved is not None:
                out.append(saved.summary())
        return out

    @app.get("/api/sessions/{session_id}")
    async def open_session(session_id: str) -> dict:
        saved = past(session_id)
        return {**saved.summary(), "events": saved.transcript().snapshot()}

    @app.get("/api/sessions/{session_id}/export")
    async def export_session(session_id: str, format: ExportFormat = "md") -> Response:  # noqa: A002
        """A saved Session. The running Session is exported as a snapshot of the moment."""
        if session_id == running_id():
            return export_response(hub.transcript, session_id, format)
        saved = store.load(session_id)
        if saved is None:
            raise HTTPException(404, f"unknown session: {session_id}")
        return export_response(saved.transcript(), session_id, format)

    @app.patch("/api/sessions/{session_id}/speakers/{speaker_id:path}")
    async def rename_past_speaker(session_id: str, speaker_id: str, change: SpeakerUpdate) -> dict:
        event = renamed(past(session_id).transcript(), speaker_id, change)
        record(session_id, event)
        return event

    @app.post("/api/sessions/{session_id}/speakers/merge")
    async def merge_past_speakers(session_id: str, merge: SpeakerMerge) -> dict:
        check_merge(past(session_id).transcript(), merge)
        event = {"type": "merge", **merge.model_dump()}
        record(session_id, event)
        return event

    @app.delete("/api/sessions/{session_id}", status_code=204)
    async def delete_session(session_id: str) -> Response:
        past(session_id)
        if hub.log is not None and session_id == hub.log.id:
            hub.forget_last_session()
        store.delete(session_id)
        return Response(status_code=204)

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
