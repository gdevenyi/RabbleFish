"""FastAPI application: REST, the UI WebSocket, and the built frontend."""

import asyncio
import os
import time
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from ltt import __version__

HEARTBEAT_INTERVAL_S = 1.0

app = FastAPI(title="live-transcribe-translate", version=__version__)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "version": __version__}


@app.websocket("/ws")
async def ui_socket(ws: WebSocket) -> None:
    """Send a heartbeat to the UI every HEARTBEAT_INTERVAL_S seconds."""
    await ws.accept()
    await ws.send_json({"type": "hello", "version": __version__})
    seq = 0
    try:
        while True:
            seq += 1
            await ws.send_json({"type": "heartbeat", "seq": seq, "server_time": time.time()})
            await asyncio.sleep(HEARTBEAT_INTERVAL_S)
    except WebSocketDisconnect:
        pass


def _static_dir() -> Path:
    default = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    return Path(os.environ.get("LTT_STATIC_DIR", default))


# Mounted last so that /api and /ws take precedence. In development Vite serves
# the frontend, so the directory may not exist.
if _static_dir().is_dir():
    app.mount("/", StaticFiles(directory=_static_dir(), html=True), name="frontend")
