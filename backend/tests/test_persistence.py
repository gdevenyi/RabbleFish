"""Saved Sessions through the API: the log of a live Session, replay, interrupted Sessions,
the saved audio, and rename, merge and delete of a past Session."""

import asyncio
import json
import shutil

import pytest
from conftest import FakeCapture
from fastapi.testclient import TestClient
from test_app import MIC, SPEAKER, fake_watcher
from test_session import count, receive_until, select_both
from test_translation import detect

from ltt import pipeline
from ltt.app import create_app
from ltt.capture import NS_PER_S, AudioChunk, CaptureError
from ltt.store import LOG_NAME, SAVED_TYPES, read_events


@pytest.fixture(autouse=True)
def fast_retry(monkeypatch):
    monkeypatch.setattr(pipeline, "RETRY_MIN_S", 0.05)


def make_client(url, translation_url=None, capture=FakeCapture, data_dir=None):
    app = create_app(
        watch=fake_watcher([MIC, SPEAKER]),
        asr_endpoint_url=url,
        capture_factory=capture,
        detect_language=detect,
        translation_endpoint_url=translation_url or "http://127.0.0.1:9",
        data_dir=data_dir,
    )
    return TestClient(app)


def session_dirs(data_dir):
    return sorted((data_dir / "sessions").iterdir())


def run_session(c, ws, done, **start):
    c.post("/api/session/start", json=start)
    events = receive_until(ws, done)
    c.post("/api/session/stop")
    return events


def test_live_session_is_saved_and_replays_as_the_snapshot(fake_nemo, fake_translator, data_dir):
    nemo, tr = fake_nemo(), fake_translator()
    with make_client(nemo.url, tr.url) as c:
        select_both(c)
        with c.websocket_connect("/ws") as ws:
            run_session(c, ws, lambda ev: count(ev, "translation") >= 2)
        (d,) = session_dirs(data_dir)
        saved = read_events(d / LOG_NAME)
        kinds = {e["type"] for e in saved}
        assert kinds <= SAVED_TYPES
        assert {"session", "source_status", "speaker", "segment", "translation"} <= kinds
        assert {"translation_status", "audio_file"} <= kinds
        assert saved[0]["state"] == "started" and saved[-1]["state"] == "stopped"
        assert saved[-1]["ended_at"] >= saved[-1]["started_at"]

        # The /ws snapshot after the stop, and the replay of the log, are the same.
        with c.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "hello"
            assert ws.receive_json()["type"] == "sources"
            live = []
            n = len(c.app.state.hub.transcript.snapshot())
            while len(live) < n:
                msg = ws.receive_json()
                if msg["type"] != "heartbeat":
                    live.append(msg)
        opened = c.get(f"/api/sessions/{d.name}").json()
        assert opened["events"] == live
        assert opened["id"] == d.name and not opened["interrupted"]

        (listed,) = c.get("/api/sessions").json()
        assert listed["id"] == d.name and listed["state"] == "stopped"
        assert listed["segments"] == count(live, "segment") > 0
        assert listed["audio_files"] == 2  # one for each Source
        assert {s["id"] for s in listed["speakers"]} >= {"microphone:mic#0", "monitor:spk#1"}


def test_running_session_is_not_a_past_session(fake_nemo, data_dir):
    with make_client(fake_nemo().url) as c:
        select_both(c)
        c.post("/api/session/start")
        (d,) = session_dirs(data_dir)
        assert c.get("/api/sessions").json() == []
        assert c.get(f"/api/sessions/{d.name}").status_code == 409
        assert c.delete(f"/api/sessions/{d.name}").status_code == 409
        c.post("/api/session/stop")
        assert [s["id"] for s in c.get("/api/sessions").json()] == [d.name]


def test_crashed_session_is_listed_as_interrupted(fake_nemo, fake_translator, tmp_path):
    nemo, tr = fake_nemo(), fake_translator()
    first, crashed = tmp_path / "first", tmp_path / "crashed"
    with make_client(nemo.url, tr.url, data_dir=first) as c:
        select_both(c)
        with c.websocket_connect("/ws") as ws:
            c.post("/api/session/start")
            receive_until(ws, lambda ev: count(ev, "translation") >= 1)
            # The state of the disk at a crash: the files as they are now, with no stop.
            shutil.copytree(first, crashed)
        c.post("/api/session/stop")

    (d,) = session_dirs(crashed)
    before = read_events(d / LOG_NAME)
    assert not any(e["type"] == "session" and e["state"] == "stopped" for e in before)

    with make_client(nemo.url, tr.url, data_dir=crashed) as c:
        (listed,) = c.get("/api/sessions").json()
        assert listed["interrupted"] and listed["state"] == "interrupted"
        assert listed["length"] > 0
        opened = c.get(f"/api/sessions/{d.name}").json()
        ids = [e["id"] for e in opened["events"] if e["type"] == "segment"]
        assert ids == [e["id"] for e in before if e["type"] == "segment"]
        assert count(opened["events"], "translation") == count(before, "translation") >= 1
        assert opened["events"][0]["state"] == "interrupted"
        # No Source status and no live state in a closed Session.
        assert count(opened["events"], "source_status") == 0
        # A new Session is a new log; the interrupted one is not continued.
        select_both(c)
        c.post("/api/session/start")
        c.post("/api/session/stop")
        assert len(session_dirs(crashed)) == 2
    after = read_events(d / LOG_NAME)
    assert after[len(before) :] == [after[-1]] and after[-1]["state"] == "interrupted"


def test_rename_and_merge_of_a_past_session_are_appended(fake_nemo, data_dir):
    nemo = fake_nemo()
    with make_client(nemo.url) as c:
        select_both(c)
        with c.websocket_connect("/ws") as ws:
            run_session(c, ws, lambda ev: count(ev, "segment", source_key="monitor:spk") >= 5)
        old = session_dirs(data_dir)[0].name
        # A second Session: the first is now a past Session that is not the last one.
        c.post("/api/session/start")
        c.post("/api/session/stop")

        url = f"/api/sessions/{old}"
        r = c.patch(f"{url}/speakers/monitor:spk%231", json={"display_name": " Alice "})
        assert r.status_code == 200 and r.json()["display_name"] == "Alice"
        merge = {"from_speaker_id": "monitor:spk#2", "into_speaker_id": "monitor:spk#1"}
        assert c.post(f"{url}/speakers/merge", json=merge).status_code == 200
        assert c.post(f"{url}/speakers/merge", json=merge).status_code == 409
        bad = {"from_speaker_id": "monitor:spk#1", "into_speaker_id": "monitor:spk#1"}
        assert c.post(f"{url}/speakers/merge", json=bad).status_code == 400
        assert c.patch(f"{url}/speakers/nope%231", json={"display_name": "X"}).status_code == 404
        assert c.patch("/api/sessions/nope/speakers/x%231", json={}).status_code == 404

        tail = read_events(data_dir / "sessions" / old / LOG_NAME)[-2:]
        assert tail[0]["type"] == "speaker" and tail[0]["display_name"] == "Alice"
        assert tail[1] == {"type": "merge", **merge}
        opened = c.get(url).json()
        alice = next(e for e in opened["events"] if e.get("id") == "monitor:spk#1")
        assert alice["display_name"] == "Alice"
        assert "monitor:spk#2" not in {s["id"] for s in opened["speakers"]}
        # The live snapshot (the second Session) does not change.
        assert "monitor:spk#1" not in c.app.state.hub.transcript.speakers


def test_changes_to_the_last_session_after_stop_are_saved(fake_nemo, data_dir):
    with make_client(fake_nemo().url) as c:
        select_both(c)
        with c.websocket_connect("/ws") as ws:
            run_session(c, ws, lambda ev: count(ev, "segment", source_key="monitor:spk") >= 3)
        (d,) = session_dirs(data_dir)
        # The live API after the stop, as before.
        c.patch("/api/speakers/monitor:spk%231", json={"display_name": "Bob"})
        # The past-session API for the same Session also updates the live snapshot.
        c.patch(f"/api/sessions/{d.name}/speakers/microphone:mic%230", json={"display_name": "Me"})
        names = {
            e["id"]: e["display_name"]
            for e in read_events(d / LOG_NAME)
            if e["type"] == "speaker" and e["display_name"]
        }
        assert names == {"monitor:spk#1": "Bob", "microphone:mic#0": "Me"}
        assert c.app.state.hub.transcript.speakers["microphone:mic#0"]["display_name"] == "Me"


def test_delete_a_past_session(fake_nemo, data_dir):
    with make_client(fake_nemo().url) as c:
        select_both(c)
        c.post("/api/session/start")
        c.post("/api/session/stop")
        (d,) = session_dirs(data_dir)
        assert (d / "audio").is_dir()
        assert c.delete("/api/sessions/nope").status_code == 404
        assert c.delete("/api/sessions/..").status_code == 404
        assert c.delete(f"/api/sessions/{d.name}").status_code == 204
        assert not d.exists() and (data_dir / "sessions").is_dir()
        assert c.get("/api/sessions").json() == []
        assert c.get(f"/api/sessions/{d.name}").status_code == 404
        # The deleted Session was the last one: rename has nothing to save to now.
        assert c.patch("/api/speakers/microphone:mic%230", json={}).status_code == 404


class BreakingCapture:
    """The first capture gives 1 s of audio, jumps 2 s ahead (lost audio), gives 0.5 s,
    then fails. The next one (the restart) gives audio until it is stopped."""

    instances = 0

    def __init__(self, source) -> None:
        self.source = source
        self.n = BreakingCapture.instances
        BreakingCapture.instances += 1
        self._stopped = asyncio.Event()

    async def chunks(self):
        import time

        t0 = time.monotonic_ns()
        pcm = (1000 + self.n).to_bytes(2, "little") * 1600
        if self.n == 0:
            for i in range(10):
                yield AudioChunk(self.source.key, t0 + i * NS_PER_S // 10, pcm)
            for i in range(5):
                yield AudioChunk(self.source.key, t0 + (30 + i) * NS_PER_S // 10, pcm)
            raise CaptureError("device gone")
        for i in range(8):
            yield AudioChunk(self.source.key, t0 + i * NS_PER_S // 10, pcm)
        await self._stopped.wait()

    async def stop(self) -> None:
        self._stopped.set()


def test_audio_is_saved_with_a_new_file_after_each_break(data_dir):
    BreakingCapture.instances = 0
    # The endpoint is unreachable: the audio is saved all the same.
    with make_client("ws://127.0.0.1:9", capture=BreakingCapture) as c:
        c.patch("/api/sources/monitor:spk", json={"selected": True})
        with c.websocket_connect("/ws") as ws:
            c.post("/api/session/start")
            events = receive_until(ws, lambda ev: count(ev, "audio_file") >= 3)
            c.post("/api/session/stop")
    files = [e for e in events if e["type"] == "audio_file"]
    (d,) = session_dirs(data_dir)
    assert [f["path"] for f in files] == [f"audio/monitor_spk-00{i}.pcm" for i in (1, 2, 3)]
    sizes = [(d / f["path"]).stat().st_size for f in files]
    assert sizes == [10 * 3200, 5 * 3200, 8 * 3200]
    assert files[1]["start"] - files[0]["start"] > 2.9
    assert count(events, "source_status", state="error") >= 1
    logged = [e for e in read_events(d / LOG_NAME) if e["type"] == "audio_file"]
    assert logged == files


def test_save_audio_off_saves_no_audio(fake_nemo, data_dir):
    with make_client(fake_nemo().url) as c:
        select_both(c)
        with c.websocket_connect("/ws") as ws:
            run_session(c, ws, lambda ev: count(ev, "segment") >= 2, save_audio=False)
    (d,) = session_dirs(data_dir)
    assert not (d / "audio").exists()
    assert not any(e["type"] == "audio_file" for e in read_events(d / LOG_NAME))
    assert json.loads((d / LOG_NAME).read_text().splitlines()[0])["type"] == "session"
