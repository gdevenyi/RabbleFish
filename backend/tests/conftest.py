"""Test doubles: a fake NeMo-Speech.cpp endpoint that replays recorded events, and a fake
capture, so the API tests need no GPU and no PipeWire."""

import asyncio
import json
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from websockets.asyncio.server import serve

from ltt.capture import NS_PER_S, AudioChunk
from ltt.settings import ENV

FIXTURES = Path(__file__).parent / "fixtures"
DIARIZE_EVENTS = FIXTURES / "nemo_diarize_en_fr.jsonl"  # n1 benchmark, en_fr.wav, 5 speakers
SINGLE_EVENTS = FIXTURES / "nemo_single_en.jsonl"  # en_fr.wav, first 15 s, no diarization
ENV_NAMES = [name for name, _parse in ENV.values()] + ["LTT_STATIC_DIR"]
CONTROL = {"session.created", "session.updated", "input_audio_buffer.committed"}


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch) -> Path:
    """Saved Sessions go to a temporary directory, never to the user's data directory, and
    the settings never come from the user's config file or LTT_* environment."""
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    # Port 9 (discard): nothing listens, so the endpoint check of an app that has no
    # fake endpoint never reaches a real server on this machine.
    monkeypatch.setenv("LTT_ASR_ENDPOINT_URL", "ws://127.0.0.1:9")
    path = tmp_path / "data"
    monkeypatch.setenv("LTT_DATA_DIR", str(path))
    return path


def load_events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


class FakeNemo:
    """A local WebSocket server with the NeMo realtime protocol, `/ready` and `/v1/models`.

    It replays the recorded events of a diarized or a single-speaker session as the
    audio it receives reaches each event's `audio_processed`.
    """

    def __init__(self, capabilities=("transcription", "diarization"), drop_after=None):
        self.capabilities = list(capabilities)
        self.drop_after = drop_after  # close the first connection after N result events
        self.events = {
            True: [e for e in load_events(DIARIZE_EVENTS) if e["type"] not in CONTROL],
            False: [e for e in load_events(SINGLE_EVENTS) if e["type"] not in CONTROL],
        }
        self.updates: list[dict] = []
        self.frame_sizes: list[int] = []
        self.connections = 0
        self.port = 0
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    @property
    def url(self) -> str:
        return f"ws://127.0.0.1:{self.port}"

    def _process_request(self, connection, request):
        if request.path == "/ready":
            return connection.respond(HTTPStatus.OK, json.dumps({"ready": True}))
        if request.path == "/v1/models":
            data = [{"id": c, "capability": c} for c in self.capabilities]
            return connection.respond(HTTPStatus.OK, json.dumps({"data": data}))
        if request.path != "/v1/audio/transcriptions/realtime":
            return connection.respond(HTTPStatus.NOT_FOUND, "not found")
        return None

    async def _handler(self, ws) -> None:
        self.connections += 1
        first = self.connections == 1
        await ws.send(json.dumps({"type": "session.created", "session": {}}))
        update = json.loads(await ws.recv())
        self.updates.append(update)
        await ws.send(json.dumps({"type": "session.updated", "session": update["session"]}))
        events = self.events[update["session"]["speaker_diarization"]]
        audio_s, i = 0.0, 0
        async for msg in ws:
            if isinstance(msg, bytes):
                self.frame_sizes.append(len(msg))
                audio_s += len(msg) / 32000
                limit = audio_s
            elif json.loads(msg)["type"] == "input_audio_buffer.commit":
                limit = float("inf")
            else:
                continue
            while i < len(events) and events[i].get("audio_processed", 0) <= limit:
                await ws.send(json.dumps(events[i]))
                i += 1
                if first and self.drop_after is not None and i >= self.drop_after:
                    await ws.close()
                    return
            if limit == float("inf"):
                await ws.send(json.dumps({"type": "input_audio_buffer.committed"}))

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)

        async def main():
            async with serve(
                self._handler, "127.0.0.1", 0, process_request=self._process_request
            ) as server:
                self.port = server.sockets[0].getsockname()[1]
                self._stop = asyncio.Event()
                self._ready.set()
                await self._stop.wait()

        self._loop.run_until_complete(main())

    def start(self) -> "FakeNemo":
        self._thread.start()
        self._ready.wait(5)
        return self

    def close(self) -> None:
        self._loop.call_soon_threadsafe(self._stop.set)
        self._thread.join(5)


class FakeCapture:
    """Yields 100 ms chunks of silence, faster than real time, up to `max_seconds`."""

    max_seconds = 100.0
    instances: list["FakeCapture"] = []

    def __init__(self, source) -> None:
        self.source = source
        self._stopped = asyncio.Event()
        FakeCapture.instances.append(self)

    async def chunks(self):
        t0 = time.monotonic_ns()
        n = 0
        while not self._stopped.is_set() and n < self.max_seconds * 10:
            yield AudioChunk(self.source.key, t0 + n * NS_PER_S // 10, b"\0\0" * 1600)
            n += 1
            await asyncio.sleep(0.002)
        await self._stopped.wait()

    async def stop(self) -> None:
        self._stopped.set()


@pytest.fixture
def fake_nemo():
    servers: list[FakeNemo] = []

    def make(**kwargs) -> FakeNemo:
        servers.append(FakeNemo(**kwargs).start())
        return servers[-1]

    yield make
    for s in servers:
        s.close()


class FakeTranslator:
    """A local HTTP server with `GET /v1/models` and `POST /v1/translations`.

    It records each request and answers "[<target>] <input>", or HTTP 500 for the first
    `fail` requests.
    """

    def __init__(self, capabilities=("translation",), fail=0, delay=0.0):
        self.capabilities = list(capabilities)
        self.fail = fail
        self.delay = delay
        self.requests: list[dict] = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, status, body):
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path == "/v1/models":
                    data = [{"id": c, "capability": c} for c in fake.capabilities]
                    self._send(200, {"data": data})
                else:
                    self._send(404, {"error": "not found"})

            def do_POST(self):
                if self.path != "/v1/translations":
                    return self._send(404, {"error": "not found"})
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.requests.append(body)
                time.sleep(fake.delay)
                if fake.fail > 0:
                    fake.fail -= 1
                    return self._send(500, {"error": {"message": "no NMT model"}})
                text = f"[{body['target_language']}] {body['input']}"
                self._send(200, {"translations": [{"text": text}]})

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def start(self) -> "FakeTranslator":
        self._thread.start()
        return self

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture
def fake_translator():
    servers: list[FakeTranslator] = []

    def make(**kwargs) -> FakeTranslator:
        servers.append(FakeTranslator(**kwargs).start())
        return servers[-1]

    yield make
    for s in servers:
        s.close()
