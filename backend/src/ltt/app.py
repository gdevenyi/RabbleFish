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
from ltt.sources import Source, SourceRegistry, watch_sources

HEARTBEAT_INTERVAL_S = 1.0

log = logging.getLogger(__name__)

SourceMode = Literal["single", "diarize"]
Watcher = Callable[[SourceRegistry, Callable[[list[Source]], Awaitable[None]]], Awaitable[None]]


class SourceSetting(BaseModel):
    selected: bool = False
    mode: SourceMode = "single"


class SourceUpdate(BaseModel):
    selected: bool | None = None
    mode: SourceMode | None = None


def default_setting(source: Source) -> SourceSetting:
    # A microphone usually has one speaker; the monitor of an output device carries a call.
    return SourceSetting(mode="single" if source.kind == "microphone" else "diarize")


class Hub:
    """The current Sources, their settings, and the connected UI sockets."""

    def __init__(self) -> None:
        self.registry = SourceRegistry()
        self.settings: dict[str, SourceSetting] = {}  # by Source key; kept when a device goes
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

    async def broadcast_sources(self, _sources: list[Source] | None = None) -> None:
        msg = {"type": "sources", "sources": self.sources_payload()}
        for q in self._clients:
            q.put_nowait(msg)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._clients.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._clients.discard(q)


async def _run_watcher(watch: Watcher, hub: Hub) -> None:
    try:
        await watch(hub.registry, hub.broadcast_sources)
    except FileNotFoundError:
        log.warning("pw-dump not found: no PipeWire sources")


def create_app(watch: Watcher = watch_sources) -> FastAPI:
    hub = Hub()

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        task = asyncio.create_task(_run_watcher(watch, hub))
        yield
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    app = FastAPI(title="live-transcribe-translate", version=__version__, lifespan=lifespan)
    app.state.hub = hub

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok", "version": __version__}

    @app.get("/api/sources")
    async def get_sources() -> list[dict]:
        return hub.sources_payload()

    @app.patch("/api/sources/{key:path}")
    async def patch_source(key: str, change: SourceUpdate) -> list[dict]:
        try:
            hub.update(key, change)
        except KeyError as e:
            raise HTTPException(404, f"unknown source: {key}") from e
        await hub.broadcast_sources()
        return hub.sources_payload()

    @app.websocket("/ws")
    async def ui_socket(ws: WebSocket) -> None:
        """Send hello, the Source list (again after each change), and a heartbeat."""
        await ws.accept()
        queue = hub.subscribe()
        try:
            await ws.send_json({"type": "hello", "version": __version__})
            await ws.send_json({"type": "sources", "sources": hub.sources_payload()})
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
