"""The Markdown and JSON exports (issue #30): golden files from a fixture event log, the
rules shared with the UI, and the export API for past and live Sessions.

To write the golden files again after an intended change: `LTT_UPDATE_GOLDEN=1 pytest`.
"""

import json
import os
import shutil
import time
from datetime import UTC
from pathlib import Path

import jsonschema
import pytest
from test_persistence import make_client, run_session, session_dirs
from test_session import count, receive_until, select_both

import ltt
from ltt import pipeline
from ltt.export import (
    SessionExport,
    format_duration,
    format_time,
    language_switches,
    merge_targets,
    silence_folds,
)
from ltt.store import read_events
from ltt.transcript import Transcript

FIXTURES = Path(__file__).parent / "fixtures" / "export"
SCHEMA = json.loads((Path(ltt.__file__).parent / "export.schema.json").read_text())
SESSION_ID = "2026-10-30T10-37-30"
# The time of the export; it does not change the export of a closed Session.
NOW = 1793360000.0


@pytest.fixture(autouse=True)
def fast_retry(monkeypatch):
    monkeypatch.setattr(pipeline, "RETRY_MIN_S", 0.05)


def replay(path: Path) -> Transcript:
    t = Transcript()
    for e in read_events(path):
        t.apply(e)
    return t


def golden(name: str, actual: str) -> None:
    path = FIXTURES / name
    if os.environ.get("LTT_UPDATE_GOLDEN"):
        path.write_text(actual, encoding="utf-8")
    assert actual == path.read_text(encoding="utf-8")


@pytest.fixture
def fixture_export() -> SessionExport:
    return SessionExport(replay(FIXTURES / "events.jsonl"), SESSION_ID, now=NOW, tz=UTC)


def test_markdown_matches_the_golden_file(fixture_export):
    golden("expected.md", fixture_export.markdown())


def test_json_matches_the_golden_file(fixture_export):
    golden("expected.json", fixture_export.json())


def validate(doc: dict) -> None:
    jsonschema.validate(doc, SCHEMA, format_checker=jsonschema.FormatChecker())


def test_json_validates_against_the_schema(fixture_export):
    validate(fixture_export.document())


def test_markdown_has_the_decided_parts(fixture_export):
    md = fixture_export.markdown()
    assert "- **Date:** 2026-10-30" in md
    assert "- **Start:** 10:37:30 (UTC+00:00)" in md
    assert "- **Length:** 1 h 01 min 44 s" in md
    assert "- **State:** interrupted" in md
    assert "Bertrand (Speaker 2; merged: Speaker 3, Speaker 4)" in md
    # Merges and renames: the merged Speakers have no line of their own.
    assert "Speaker 3" not in md.split("- **Speakers:**")[1].split("\n\n", 1)[1]
    assert "**[02:16] Bertrand:** Oui" in md
    # The rename after the interrupted line is applied.
    assert "**[00:02] Gabriel:** Good morning to all." in md
    # The language tag only at a Language switch of the Speaker (after Merges).
    assert "**[00:10] Alice:** [fr] Alors" in md
    assert "**[00:04] Bertrand:** Bonjour" in md
    assert "**[02:08] Bertrand:** [en] Sorry" in md
    assert "**[02:12] Bertrand:** [fr] Merci" in md
    assert "*So, we start the meeting now.*" in md
    # 92 s of silence folds; 19 s does not.
    assert md.count("silence —*") == 2
    assert "*— 1 min 32 s silence —*" in md
    # h:mm:ss after one hour.
    assert "**[1:01:40] Gabriel:**" in md
    assert "partial" not in md


def test_json_document(fixture_export):
    doc = json.loads(fixture_export.json())
    assert doc["session"] == {
        "id": SESSION_ID,
        "started_at": "2026-10-30T10:37:30+00:00",
        "duration_s": 3703.5,
        "sources": ["mic:alsa_input.usb-desk", "monitor:alsa_output.pci-speakers"],
        "target_language": "en",
        "interrupted": True,
        "in_progress": False,
    }
    segs = {s["id"]: s for s in doc["segments"]}
    mon = "monitor:alsa_output.pci-speakers"
    # A Merge chain: #4 into #3, then #3 into #2.
    assert segs[f"{mon}/7"]["speaker_id"] == f"{mon}#2"
    assert segs[f"{mon}/7"]["original_speaker_id"] == f"{mon}#4"
    assert "original_speaker_id" not in segs[f"{mon}/2"]
    assert segs[f"{mon}/2"]["translation"] == "Hello, I'm late, sorry."
    assert segs[f"{mon}/1"]["translation"] is None
    starts = [s["start"] for s in doc["segments"]]
    assert starts == sorted(starts)
    speakers = {s["id"]: s for s in doc["speakers"]}
    assert speakers[f"{mon}#2"]["display_name"] == "Bertrand"
    assert speakers[f"{mon}#4"]["merged_into"] == f"{mon}#2"
    assert [a["start"] for a in doc["audio_files"]] == [0.02, 0.03, 100.0]


def test_merge_rules_match_the_ui():
    m = [
        {"from_speaker_id": "a", "into_speaker_id": "b"},
        {"from_speaker_id": "b", "into_speaker_id": "c"},
        {"from_speaker_id": "c", "into_speaker_id": "a"},  # closes a loop: ignored
        {"from_speaker_id": "d", "into_speaker_id": "d"},  # into itself: ignored
    ]
    assert merge_targets(m) == {"a": "c", "b": "c"}


def test_language_switch_ignores_segments_with_no_language():
    segs = [
        {"id": "1", "lang": "en"},
        {"id": "2", "lang": None},
        {"id": "3", "lang": "en"},
        {"id": "4", "lang": "fr"},
        {"id": "5", "lang": "fr"},
    ]
    assert language_switches(segs, dict.fromkeys("12345", "s")) == {"4"}


def test_silence_folds_after_20_s_of_silence_of_all_speakers():
    segs = [
        {"start": 25.0, "end": 30.0},
        {"start": 28.0, "end": 40.0},  # overlaps the one before
        {"start": 60.0, "end": 61.0},  # 20 s: no fold
        {"start": 81.5, "end": 82.0},
    ]
    folds = silence_folds(segs)
    assert [(f.start, f.end) for f in folds] == [(0.0, 25.0), (61.0, 81.5)]


def test_time_formats():
    assert format_time(59.9) == "00:59"
    assert format_time(3725) == "1:02:05"
    assert format_duration(92) == "1 min 32 s"
    assert format_duration(125) == "2 min 05 s"
    assert format_duration(44.5) == "45 s"
    assert format_duration(3725) == "1 h 02 min 05 s"


def test_export_api_for_a_past_session(data_dir, fake_nemo):
    d = data_dir / "sessions" / SESSION_ID
    d.mkdir(parents=True)
    shutil.copy(FIXTURES / "events.jsonl", d / "events.jsonl")
    with make_client(fake_nemo().url, data_dir=data_dir) as c:
        r = c.get(f"/api/sessions/{SESSION_ID}/export?format=md")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/markdown")
        assert r.headers["content-disposition"] == f'attachment; filename="{SESSION_ID}.md"'
        assert "**[02:16] Bertrand:** Oui" in r.text
        r = c.get(f"/api/sessions/{SESSION_ID}/export", params={"format": "json"})
        assert r.headers["content-type"] == "application/json"
        assert r.headers["content-disposition"] == f'attachment; filename="{SESSION_ID}.json"'
        assert r.json()["session"]["interrupted"] is True
        assert c.get(f"/api/sessions/{SESSION_ID}/export?format=pdf").status_code == 422
        assert c.get("/api/sessions/2020-01-01T00-00-00/export").status_code == 404
        assert c.get("/api/session/export").status_code == 404  # no live Session yet


def test_export_of_the_live_session_is_a_snapshot_in_progress(data_dir, fake_nemo, fake_translator):
    nemo, tr = fake_nemo(), fake_translator()
    with make_client(nemo.url, tr.url, data_dir=data_dir) as c:
        select_both(c)
        with c.websocket_connect("/ws") as ws:
            c.post("/api/session/start", json={})
            events = receive_until(ws, lambda ev: count(ev, "segment") >= 2)
            (d,) = session_dirs(data_dir)
            r = c.get("/api/session/export?format=json")
            assert r.headers["content-disposition"] == f'attachment; filename="{d.name}.json"'
            doc = r.json()
            validate(doc)
            assert doc["session"]["in_progress"] is True
            assert doc["session"]["interrupted"] is False
            assert len(doc["segments"]) >= 2
            assert doc["session"]["duration_s"] > 0
            md = c.get("/api/session/export").text
            assert "in progress" in md
            # The running Session through the past-sessions route too.
            assert c.get(f"/api/sessions/{d.name}/export?format=json").status_code == 200
            # Partial text is left out.
            partial = {"type": "partial", "source_key": "x", "text": "NOT FINAL", "audio_time": 1}
            c.app.state.hub.publish(partial)
            assert "NOT FINAL" not in c.get("/api/session/export").text
            assert "NOT FINAL" not in c.get("/api/session/export?format=json").text
            assert events
            c.post("/api/session/stop")
        time.sleep(0.05)
        doc = c.get("/api/session/export?format=json").json()
        assert doc["session"]["in_progress"] is False
        assert c.get(f"/api/sessions/{d.name}/export").status_code == 200


def test_the_last_session_is_listed_after_stop(data_dir, fake_nemo, fake_translator):
    nemo, tr = fake_nemo(), fake_translator()
    with make_client(nemo.url, tr.url, data_dir=data_dir) as c:
        select_both(c)
        with c.websocket_connect("/ws") as ws:
            run_session(c, ws, lambda ev: count(ev, "segment") >= 1)
        (d,) = session_dirs(data_dir)
        live = c.get("/api/session/export").text
        past = c.get(f"/api/sessions/{d.name}/export").text
        assert live == past
