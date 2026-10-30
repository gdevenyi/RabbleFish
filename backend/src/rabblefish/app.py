"""FastAPI application: REST, the UI WebSocket, and the built frontend."""

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from rabblefish import __version__
from rabblefish.capture import Capture
from rabblefish.endpoint_status import RECHECK_S, check_endpoint, initial_status
from rabblefish.export import SessionExport
from rabblefish.nemo import NemoEndpoint
from rabblefish.pipeline import CaptureFactory, Session
from rabblefish.settings import Settings, load_settings, static_dir
from rabblefish.sources import Source, SourceRegistry, watch_sources
from rabblefish.store import FSYNC_INTERVAL_S, SavedSession, SessionLog, SessionStore
from rabblefish.transcript import LanguageDetector, LanguageIdentifier, Transcript
from rabblefish.translation import (
    DEFAULT_TARGET_LANGUAGE,
    TARGET_LANGUAGES,
    TranslationEndpoint,
    Translator,
    normalize_target,
)

HEARTBEAT_INTERVAL_S = 1.0

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

    def __init__(self, store: SessionStore, default_target_language: str = "en") -> None:
        self.default_target_language = default_target_language
        self.endpoint_status: dict | None = None  # the last endpoint_status event
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
                    "muted": s.muted,
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
        self._broadcast(self.hello())

    def hello(self) -> dict:
        return {
            "type": "hello",
            "version": __version__,
            "default_target_language": self.default_target_language,
        }

    def set_endpoint_status(self, status: dict) -> None:
        """Keep the last endpoint state (not a Session event: never in the log)."""
        self.endpoint_status = status
        self._broadcast(status)

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


async def _endpoint_loop(hub: Hub, check: Callable[[], Awaitable[dict]], wake: asyncio.Event):
    """Check the endpoint now, again when `wake` is set (a Session start), and every
    RECHECK_S seconds while it is not ready. It never stops the app."""
    while True:
        wake.clear()
        status = await check()
        before = hub.endpoint_status
        if before is None or before.get("state") != status["state"]:
            level = logging.INFO if status["state"] == "ready" else logging.WARNING
            log.log(
                level,
                "endpoint %s: %s%s",
                status["asr_url"],
                status["state"],
                f" ({status['message']})" if status["message"] else "",
            )
        hub.set_endpoint_status(status)
        timeout = None if status["state"] == "ready" else RECHECK_S
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(wake.wait(), timeout)


async def _run_watcher(watch: Watcher, hub: Hub) -> None:
    try:
        await watch(hub.registry, hub.broadcast_sources)
    except FileNotFoundError:
        log.warning("pw-dump not found: no PipeWire sources")


def create_app(
    watch: Watcher = watch_sources,
    *,
    settings: Settings | None = None,
    asr_endpoint_url: str | None = None,
    capture_factory: CaptureFactory = Capture,
    detect_language: LanguageDetector | None = None,
    translation_endpoint_url: str | None = None,
    data_dir: Path | str | None = None,
) -> FastAPI:
    """Create the app. With no `settings`, it reads them with `load_settings()` (the
    config file and the RABBLEFISH_* environment variables; see `rabblefish.settings`).

    The other arguments replace a setting (tests use them). `translation_endpoint_url`
    with no setting is the http:// form of the ASR endpoint (the same server).
    `detect_language` defaults to lingua, limited to the `detect_languages` setting.
    """
    settings = settings or load_settings()
    hub = Hub(
        SessionStore(Path(data_dir) if data_dir else settings.data_dir),
        settings.default_target_language,
    )
    store = hub.store
    endpoint = NemoEndpoint(asr_endpoint_url or settings.asr_endpoint_url)
    translation_endpoint = TranslationEndpoint(
        translation_endpoint_url or settings.translation_endpoint_url or endpoint.http_url
    )
    hub.endpoint_status = initial_status(endpoint.http_url, translation_endpoint.url)
    recheck = asyncio.Event()
    detectors: list[LanguageDetector] = [detect_language] if detect_language else []

    def language_detector() -> LanguageDetector:
        if not detectors:  # built once, at the first Session start
            detectors.append(LanguageIdentifier(list(settings.detect_languages)))
        return detectors[0]

    async def check() -> dict:
        return await asyncio.to_thread(check_endpoint, endpoint.http_url, translation_endpoint.url)

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # A log with no stop line is from an app that ended without a stop.
        await asyncio.to_thread(store.recover)
        tasks = [
            asyncio.create_task(_run_watcher(watch, hub)),
            asyncio.create_task(_sync_loop(hub)),
            asyncio.create_task(_endpoint_loop(hub, check, recheck)),
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

    app = FastAPI(title="rabblefish", version=__version__, lifespan=lifespan)
    app.state.hub = hub
    app.state.asr_endpoint = endpoint
    app.state.translation_endpoint = translation_endpoint
    app.state.store = store
    app.state.settings = settings

    @app.get("/api/config")
    async def get_config() -> dict:
        """The settings that the UI uses, and the last endpoint state."""
        return {
            "version": __version__,
            "default_target_language": settings.default_target_language,
            "detect_languages": list(settings.detect_languages),
            "asr_endpoint_url": endpoint.url,
            "translation_endpoint_url": translation_endpoint.url,
            "endpoint_status": hub.endpoint_status,
        }

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
            silence=(settings.silent_after_s, settings.silence_dbfs),
        )
        hub.session.start()
        recheck.set()  # the endpoint chip shows the state at this start too
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
            await ws.send_json(hub.hello())
            await ws.send_json({"type": "sources", "sources": hub.sources_payload()})
            if hub.endpoint_status is not None:
                await ws.send_json(hub.endpoint_status)
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

    # Mounted last so that /api and /ws take precedence. In development Vite serves
    # the frontend, so the directory may not exist.
    ui_dir = static_dir()
    if ui_dir is not None and ui_dir.is_dir():
        app.mount("/", StaticFiles(directory=ui_dir, html=True), name="frontend")
    else:
        log.info("no built UI (run `pnpm build`); only the API is served")
    return app
