from fastapi.testclient import TestClient

from ltt.app import app


def test_health():
    r = TestClient(app).get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_ws_sends_hello_then_heartbeats():
    with TestClient(app).websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] == "hello"
        first = ws.receive_json()
        second = ws.receive_json()
        assert first["type"] == second["type"] == "heartbeat"
        assert second["seq"] == first["seq"] + 1
