import asyncio

from fastapi.testclient import TestClient

from rabblefish.app import create_app
from rabblefish.sources import NODE_TYPE

MIC = {
    "id": 58,
    "type": NODE_TYPE,
    "info": {
        "props": {
            "media.class": "Audio/Source",
            "node.name": "mic",
            "object.serial": 58,
            "node.description": "Mic",
        }
    },
}
SPEAKER = {
    "id": 54,
    "type": NODE_TYPE,
    "info": {
        "props": {"media.class": "Audio/Sink", "node.name": "spk", "object.serial": 54},
    },
}


def fake_watcher(objects):
    async def watch(registry, on_change):
        registry.apply(objects)
        await on_change(registry.sources())
        await asyncio.Event().wait()  # run until cancelled

    return watch


def client(objects=(MIC, SPEAKER)):
    return TestClient(create_app(watch=fake_watcher(list(objects))))


def test_health():
    with client() as c:
        r = c.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_ws_sends_hello_sources_endpoint_then_heartbeats():
    with client() as c, c.websocket_connect("/ws") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello" and hello["default_target_language"] == "en"
        assert ws.receive_json()["type"] == "sources"
        assert ws.receive_json()["type"] == "endpoint_status"
        beats = [m for m in (ws.receive_json() for _ in range(4)) if m["type"] == "heartbeat"]
        assert len(beats) >= 2
        assert beats[1]["seq"] == beats[0]["seq"] + 1


def test_sources_have_default_modes():
    with client() as c:
        sources = {s["key"]: s for s in c.get("/api/sources").json()}
    assert sources["microphone:mic"]["mode"] == "single"
    assert sources["monitor:spk"]["mode"] == "diarize"
    assert not any(s["selected"] for s in sources.values())


def test_select_and_change_mode_is_broadcast():
    with client() as c, c.websocket_connect("/ws") as ws:
        ws.receive_json()  # hello
        ws.receive_json()  # sources
        r = c.patch("/api/sources/microphone:mic", json={"selected": True, "mode": "diarize"})
        assert r.status_code == 200
        msg = ws.receive_json()
        while msg["type"] != "sources":
            msg = ws.receive_json()
        mic = next(s for s in msg["sources"] if s["key"] == "microphone:mic")
        assert mic["selected"] is True and mic["mode"] == "diarize"


def test_unknown_source_is_404():
    with client() as c:
        assert c.patch("/api/sources/microphone:nope", json={"selected": True}).status_code == 404
