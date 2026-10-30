"""A thin client for the NeMo-Speech.cpp realtime transcription endpoint (see ADR-0001).

One connection per Source: `/v1/audio/transcriptions/realtime`, one `session.update`,
then the capture's 16 kHz mono PCM16 as binary frames of 80 ms. The server must run with
`--asr.endpointing.enable=true --asr.batching.enabled=false` and `--threads` at least
equal to the number of Sources (see README.md).
"""

import asyncio
import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import AsyncIterator

import websockets

from ltt.capture import BYTES_PER_SAMPLE, SAMPLE_RATE

REALTIME_PATH = "/v1/audio/transcriptions/realtime"
FRAME_MS = 80
FRAME_BYTES = SAMPLE_RATE * BYTES_PER_SAMPLE * FRAME_MS // 1000
ENDPOINTING_MS = 800
HTTP_TIMEOUT_S = 5.0
OPEN_TIMEOUT_S = 10.0


class EndpointError(RuntimeError):
    """The endpoint is not reachable, not ready, or cannot serve the Source."""


class NemoEndpoint:
    def __init__(self, url: str) -> None:
        self.url = url.rstrip("/")
        parts = urllib.parse.urlsplit(self.url)
        if parts.scheme not in ("ws", "wss"):
            raise ValueError(f"asr_endpoint_url must be ws:// or wss://: {url}")
        http_scheme = "https" if parts.scheme == "wss" else "http"
        self.http_url = urllib.parse.urlunsplit((http_scheme, parts.netloc, parts.path, "", ""))
        self.realtime_url = self.url + REALTIME_PATH

    def _get_json(self, path: str) -> dict:
        url = self.http_url + path
        try:
            with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT_S) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise EndpointError(f"{url}: HTTP {e.code}") from e
        except (OSError, ValueError) as e:
            reason = getattr(e, "reason", e)
            raise EndpointError(f"{url}: {reason}") from e

    def _check(self, diarize: bool) -> None:
        if not self._get_json("/ready").get("ready"):
            raise EndpointError(f"{self.http_url}/ready: the endpoint is not ready")
        models = self._get_json("/v1/models").get("data") or []
        capabilities = {m.get("capability") for m in models}
        needed = ["transcription"] + (["diarization"] if diarize else [])
        missing = [c for c in needed if c not in capabilities]
        if missing:
            raise EndpointError(f"{self.http_url}/v1/models: no {' or '.join(missing)} model")

    async def check(self, diarize: bool) -> None:
        """Raise EndpointError unless `/ready` is true and `/v1/models` has what we need."""
        await asyncio.to_thread(self._check, diarize)

    async def connect(self, diarize: bool) -> "NemoConnection":
        """Open a realtime session; return when the server confirms `session.update`."""
        try:
            ws = await websockets.connect(
                self.realtime_url, max_size=None, open_timeout=OPEN_TIMEOUT_S
            )
        except (OSError, TimeoutError, websockets.InvalidHandshake) as e:
            raise EndpointError(f"{self.realtime_url}: {e}") from e
        conn = NemoConnection(ws)
        try:
            async with asyncio.timeout(OPEN_TIMEOUT_S):
                await conn.configure(diarize)
        except BaseException:
            await ws.close()
            raise
        return conn


def session_update(diarize: bool) -> dict:
    return {
        "type": "session.update",
        "session": {
            "word_timestamps": True,
            "speaker_diarization": diarize,
            "language": "auto",
            "endpointing_ms": ENDPOINTING_MS,
        },
    }


class NemoConnection:
    def __init__(self, ws: websockets.ClientConnection) -> None:
        self.ws = ws
        self._buf = bytearray()
        self.last_error: str | None = None

    async def _recv_event(self) -> dict:
        while True:
            msg = await self.ws.recv()
            if isinstance(msg, str):
                return json.loads(msg)

    async def configure(self, diarize: bool) -> None:
        await self.ws.send(json.dumps(session_update(diarize)))
        try:
            while True:
                event = await self._recv_event()
                if event.get("type") == "session.updated":
                    return
                if event.get("type") == "error":
                    raise EndpointError(f"session.update refused: {_error_text(event)}")
        except websockets.ConnectionClosed as e:
            raise EndpointError(f"the endpoint closed the session: {e}") from e

    async def send_audio(self, pcm: bytes) -> None:
        """Queue PCM16 and send each complete 80 ms frame."""
        self._buf += pcm
        while len(self._buf) >= FRAME_BYTES:
            frame = bytes(self._buf[:FRAME_BYTES])
            del self._buf[:FRAME_BYTES]
            await self.ws.send(frame)

    async def commit(self) -> None:
        """Send the rest of the audio and ask the server to finalize it."""
        if self._buf:
            await self.ws.send(bytes(self._buf))
            self._buf.clear()
        await self.ws.send(json.dumps({"type": "input_audio_buffer.commit"}))

    async def events(self) -> AsyncIterator[dict]:
        """Yield server events until the connection closes."""
        try:
            async for msg in self.ws:
                if isinstance(msg, str):
                    event = json.loads(msg)
                    if event.get("type") == "error":
                        self.last_error = _error_text(event)
                    yield event
        except websockets.ConnectionClosedError as e:
            self.last_error = self.last_error or f"connection lost: {e}"

    async def close(self) -> None:
        await self.ws.close()


def _error_text(event: dict) -> str:
    err = event.get("error") if isinstance(event.get("error"), dict) else event
    return str(err.get("message") or err.get("code") or event)
