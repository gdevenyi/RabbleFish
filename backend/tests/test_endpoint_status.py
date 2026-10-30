"""The endpoint check at start-up and the `endpoint_status` event; `GET /api/config`."""

import time

from conftest import FakeCapture
from fastapi.testclient import TestClient
from test_app import MIC, fake_watcher

from rabblefish.app import create_app
from rabblefish.endpoint_status import check_endpoint
from rabblefish.settings import load_settings

DEAD = "http://127.0.0.1:9"  # nothing listens on the discard port


def http(url: str) -> str:
    return url.replace("ws://", "http://")


def test_ready_with_all_capabilities(fake_nemo):
    nemo = fake_nemo(capabilities=("transcription", "diarization", "translation"))
    s = check_endpoint(http(nemo.url), http(nemo.url))
    assert s["state"] == "ready" and s["message"] is None and s["missing"] == []
    assert s["capabilities"] == ["transcription", "diarization", "translation"]
    assert s["checked_at"] > 0


def test_ready_but_missing_capabilities(fake_nemo):
    nemo = fake_nemo(capabilities=("transcription",))
    s = check_endpoint(http(nemo.url), http(nemo.url))
    assert s["state"] == "ready"
    assert s["missing"] == ["diarization", "translation"]
    assert s["message"] == "no diarization or translation model"


def test_no_transcription_model_is_not_ready(fake_nemo):
    nemo = fake_nemo(capabilities=("translation",))
    s = check_endpoint(http(nemo.url), http(nemo.url))
    assert s["state"] == "not_ready" and "no transcription model" in s["message"]


def test_unreachable():
    s = check_endpoint(DEAD, DEAD)
    assert s["state"] == "unreachable" and s["capabilities"] == []
    assert s["message"].startswith(DEAD + "/ready")


def test_separate_translation_server(fake_nemo, fake_translator):
    nemo = fake_nemo(capabilities=("transcription", "diarization", "translation"))
    tr = fake_translator()
    s = check_endpoint(http(nemo.url), tr.url)
    assert s["state"] == "ready" and "translation" in s["capabilities"]
    # Only the translation server counts for translation.
    s = check_endpoint(http(nemo.url), DEAD)
    assert s["state"] == "ready" and s["missing"] == ["translation"]
    assert s["message"].startswith("translation endpoint: ")


def wait_for_check(c: TestClient) -> dict:
    for _ in range(100):
        status = c.get("/api/config").json()["endpoint_status"]
        if status["state"] != "checking":
            return status
        time.sleep(0.05)
    raise AssertionError("the endpoint check did not end")


def test_the_app_starts_with_no_endpoint_and_shows_the_state():
    app = create_app(fake_watcher([]))
    with TestClient(app) as c:
        assert c.get("/api/health").status_code == 200
        status = wait_for_check(c)
        assert status["state"] == "unreachable"
        with c.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "hello"
            assert ws.receive_json()["type"] == "sources"
            assert ws.receive_json() == status


def test_the_app_shows_a_ready_endpoint(fake_nemo):
    nemo = fake_nemo()
    app = create_app(fake_watcher([]), asr_endpoint_url=nemo.url)
    with TestClient(app) as c:
        status = wait_for_check(c)
        assert status["state"] == "ready"
        assert status["capabilities"] == ["transcription", "diarization"]
        assert status["missing"] == ["translation"]


def test_a_session_start_checks_the_endpoint_again(fake_nemo):
    nemo = fake_nemo()
    app = create_app(
        fake_watcher([MIC]),
        asr_endpoint_url=nemo.url,
        capture_factory=FakeCapture,
        detect_language=lambda _text: None,
    )
    with TestClient(app) as c:
        first = wait_for_check(c)
        c.patch("/api/sources/microphone:mic", json={"selected": True})
        assert c.post("/api/session/start").status_code == 200
        for _ in range(100):
            again = c.get("/api/config").json()["endpoint_status"]
            if again["checked_at"] != first["checked_at"]:
                break
            time.sleep(0.05)
        assert again["checked_at"] > first["checked_at"] and again["state"] == "ready"
        assert c.post("/api/session/stop").status_code == 200


def test_config_gives_the_default_target_language(monkeypatch):
    monkeypatch.setenv("RABBLEFISH_DEFAULT_TARGET_LANGUAGE", "fr")
    monkeypatch.setenv("RABBLEFISH_LANGUAGES", "en,de")
    app = create_app(fake_watcher([]), settings=load_settings())
    with TestClient(app) as c:
        config = c.get("/api/config").json()
        assert config["default_target_language"] == "fr"
        assert config["detect_languages"] == ["en", "de"]
        assert config["asr_endpoint_url"] == "ws://127.0.0.1:9"
        assert config["translation_endpoint_url"] == "http://127.0.0.1:9"
        with c.websocket_connect("/ws") as ws:
            assert ws.receive_json()["default_target_language"] == "fr"
