"""Session API and /ws events against a fake NeMo endpoint and a fake capture."""

import pytest
from conftest import FakeCapture
from fastapi.testclient import TestClient
from test_app import MIC, SPEAKER, fake_watcher

from ltt import pipeline
from ltt.app import create_app
from ltt.nemo import FRAME_BYTES


@pytest.fixture(autouse=True)
def fast_retry(monkeypatch):
    monkeypatch.setattr(pipeline, "RETRY_MIN_S", 0.05)


def make_client(url, translation_url=None, detect_language=None):
    app = create_app(
        watch=fake_watcher([MIC, SPEAKER]),
        asr_endpoint_url=url,
        capture_factory=FakeCapture,
        detect_language=detect_language or (lambda text: "fr" if "prière" in text else "en"),
        translation_endpoint_url=translation_url,
    )
    return TestClient(app)


def select_both(c):
    c.patch("/api/sources/microphone:mic", json={"selected": True})
    c.patch("/api/sources/monitor:spk", json={"selected": True})


def receive_until(ws, done, limit=20000):
    """Receive events (heartbeats left out) until `done(events)` is true."""
    events = []
    for _ in range(limit):
        msg = ws.receive_json()
        if msg["type"] != "heartbeat":
            events.append(msg)
            if done(events):
                return events
    raise AssertionError(f"condition not met; last events: {events[-5:]}")


def count(events, kind, **match):
    return sum(
        1 for e in events if e["type"] == kind and all(e.get(k) == v for k, v in match.items())
    )


def test_session_with_mic_and_monitor(fake_nemo):
    nemo = fake_nemo()
    with make_client(nemo.url) as c, c.websocket_connect("/ws") as ws:
        receive_until(ws, lambda ev: ev[-1]["type"] == "sources")
        select_both(c)
        r = c.post("/api/session/start")
        assert r.status_code == 200 and r.json()["state"] == "started"
        events = receive_until(
            ws,
            lambda ev: (
                any(e["type"] == "segment" and "prière" in e["text"] for e in ev)
                and count(ev, "segment", source_key="microphone:mic") >= 3
            ),
        )
        assert c.post("/api/session/stop").json()["state"] == "stopped"

    assert count(events, "session", state="started") == 1
    for key in ("microphone:mic", "monitor:spk"):
        states = [e["state"] for e in events if e["type"] == "source_status"]
        states = [
            e["state"] for e in events if e["type"] == "source_status" and e["source_key"] == key
        ]
        assert states[:2] == ["connecting", "live"], key
    speakers = {e["id"]: e for e in events if e["type"] == "speaker"}
    assert speakers["microphone:mic#0"]["label"] == "Mic"
    assert {f"monitor:spk#{n}" for n in range(1, 6)} <= speakers.keys()
    segments = [e for e in events if e["type"] == "segment"]
    assert all(s["speaker_id"] in speakers for s in segments)
    assert count(events, "partial") > 0
    langs = [s["lang"] for s in segments if s["source_key"] == "monitor:spk" and s["lang"]]
    assert langs[0] == "en" and langs[-1] == "fr"
    # The session.update follows the Source mode, and audio goes in 80 ms frames.
    modes = sorted(u["session"]["speaker_diarization"] for u in nemo.updates)
    assert modes == [False, True]
    assert all(
        u["session"] | {"speaker_diarization": None}
        == {
            "word_timestamps": True,
            "speaker_diarization": None,
            "language": "auto",
            "endpointing_ms": 800,
        }
        for u in nemo.updates
    )
    assert set(nemo.frame_sizes[:-2]) == {FRAME_BYTES}


def test_selection_is_locked_during_a_session(fake_nemo):
    nemo = fake_nemo()
    with make_client(nemo.url) as c:
        assert c.post("/api/session/start").status_code == 400  # nothing selected
        assert c.post("/api/session/stop").status_code == 409
        select_both(c)
        assert c.post("/api/session/start").status_code == 200
        assert c.post("/api/session/start").status_code == 409
        r = c.patch("/api/sources/microphone:mic", json={"mode": "diarize"})
        assert r.status_code == 409
        assert c.post("/api/session/stop").status_code == 200
        assert c.patch("/api/sources/microphone:mic", json={"mode": "diarize"}).status_code == 200


def test_snapshot_rename_and_merge(fake_nemo):
    nemo = fake_nemo()
    with make_client(nemo.url) as c:
        select_both(c)
        with c.websocket_connect("/ws") as ws:
            c.post("/api/session/start")
            receive_until(ws, lambda ev: count(ev, "segment", source_key="monitor:spk") >= 5)
        r = c.patch("/api/speakers/monitor:spk%231", json={"display_name": " Alice "})
        assert r.status_code == 200 and r.json()["display_name"] == "Alice"
        merge = {"from_speaker_id": "monitor:spk#2", "into_speaker_id": "monitor:spk#1"}
        assert c.post("/api/speakers/merge", json=merge).status_code == 200
        assert c.post("/api/speakers/merge", json=merge).status_code == 409
        bad = {"from_speaker_id": "monitor:spk#1", "into_speaker_id": "monitor:spk#1"}
        assert c.post("/api/speakers/merge", json=bad).status_code == 400
        unknown = {"from_speaker_id": "nope#1", "into_speaker_id": "monitor:spk#1"}
        assert c.post("/api/speakers/merge", json=unknown).status_code == 404
        assert c.patch("/api/speakers/nope%231", json={"display_name": "X"}).status_code == 404

        # A UI that connects now gets the state first, in a usable order.
        with c.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "hello"
            assert ws.receive_json()["type"] == "sources"
            snap = receive_until(ws, lambda ev: ev[-1]["type"] in ("segment", "merge"))
            assert snap[0] == {
                "type": "session",
                "state": "started",
                "started_at": snap[0]["started_at"],
                "target_lang": "en",
            }
            kinds = [e["type"] for e in snap]
            assert kinds.index("source_status") < kinds.index("speaker") < kinds.index("segment")
            alice = next(e for e in snap if e["type"] == "speaker" and e["id"] == "monitor:spk#1")
            assert alice["display_name"] == "Alice"
            rest = receive_until(ws, lambda ev: any(e["type"] == "merge" for e in ev))
            assert rest[-1] == {"type": "merge", **merge}
        c.post("/api/session/stop")

        # After the Session, the snapshot is still there: stopped, with no Source status
        # and no Partial text.
        with c.websocket_connect("/ws") as ws:
            ws.receive_json()
            ws.receive_json()
            assert ws.receive_json()["state"] == "stopped"
            after = receive_until(ws, lambda ev: ev[-1]["type"] == "merge")
            assert {e["type"] for e in after} == {"speaker", "segment", "merge"}


def test_reconnect_marks_the_gap_and_gives_new_speakers(fake_nemo):
    nemo = fake_nemo(drop_after=200)  # the first connection drops after 200 events
    with make_client(nemo.url) as c, c.websocket_connect("/ws") as ws:
        c.patch("/api/sources/monitor:spk", json={"selected": True})
        c.post("/api/session/start")
        events = receive_until(
            ws,
            lambda ev: (
                any(e["type"] == "source_status" and "gap" in e for e in ev)
                and count(ev, "segment") >= 8
            ),
        )
        c.post("/api/session/stop")
    # A change of the silent warning also sends "live" again, without a gap.
    lives = [e for e in events if e["type"] == "source_status" and e["state"] == "live"]
    assert "gap" not in lives[0]
    lives = [lives[0], next(e for e in lives if "gap" in e)]
    gap = lives[1]["gap"]
    assert 0 <= gap["start"] <= gap["end"]
    # The second connection replays from the start: its speaker 1 is a new Speaker.
    ids = [e["id"] for e in events if e["type"] == "speaker"]
    assert len(ids) == len(set(ids))
    assert nemo.connections == 2
    second = events.index(lives[1])
    new = [e for e in events[second:] if e["type"] == "speaker"]
    assert new and all(int(e["id"].split("#")[1]) > 1 for e in new)


def test_endpoint_errors_are_source_status(fake_nemo):
    nemo = fake_nemo(capabilities=["transcription"])  # no diarization model
    with make_client(nemo.url) as c, c.websocket_connect("/ws") as ws:
        select_both(c)
        c.post("/api/session/start")
        events = receive_until(
            ws,
            lambda ev: (
                count(ev, "source_status", source_key="monitor:spk", state="error")
                and count(ev, "source_status", source_key="microphone:mic", state="live")
            ),
        )
        c.post("/api/session/stop")
    err = next(e for e in events if e["type"] == "source_status" and e["state"] == "error")
    assert "no diarization model" in err["message"]


def test_unreachable_endpoint_is_source_status():
    with make_client("ws://127.0.0.1:9") as c, c.websocket_connect("/ws") as ws:
        c.patch("/api/sources/microphone:mic", json={"selected": True})
        c.post("/api/session/start")
        events = receive_until(ws, lambda ev: count(ev, "source_status", state="error"))
        assert c.post("/api/session/stop").status_code == 200
    err = next(e for e in events if e["type"] == "source_status" and e["state"] == "error")
    assert err["source_key"] == "microphone:mic" and "127.0.0.1:9" in err["message"]
