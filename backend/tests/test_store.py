"""The event log, interrupted-session recovery, delete, and the audio files."""

import json

from rabblefish.audio import AudioRecorder
from rabblefish.capture import NS_PER_S, AudioChunk
from rabblefish.store import LOG_NAME, SessionStore, read_events

STARTED = {"type": "session", "state": "started", "started_at": 1000.0, "target_lang": "en"}
SPEAKER = {
    "type": "speaker",
    "id": "mon#1",
    "source_key": "mon",
    "label": "Speaker 1",
    "display_name": None,
}
SEGMENT = {
    "type": "segment",
    "id": "mon/1",
    "source_key": "mon",
    "speaker_id": "mon#1",
    "start": 1.0,
    "end": 4.5,
    "text": "bonjour à tous",
    "words": [],
    "lang": "fr",
}


def lines(path):
    return [json.loads(raw) for raw in path.read_text().splitlines()]


def test_log_saves_only_the_saved_event_types(tmp_path):
    store = SessionStore(tmp_path)
    log = store.create(1000.0)
    events = [
        {"type": "hello", "version": "x"},
        {"type": "sources", "sources": []},
        STARTED,
        {"type": "source_status", "source_key": "mon", "state": "live", "message": None},
        {"type": "partial", "source_key": "mon", "text": "bon", "audio_time": 1.0},
        SPEAKER,
        SEGMENT,
        {"type": "translation", "segment_id": "mon/1", "text": "hello all", "target_lang": "en"},
        {"type": "translation_status", "state": "ready", "target_lang": "en", "message": None},
        {"type": "merge", "from_speaker_id": "mon#2", "into_speaker_id": "mon#1"},
        {"type": "heartbeat", "seq": 1, "server_time": 1.0},
        {"type": "audio_file", "source_key": "mon", "path": "audio/mon-001.pcm", "start": 0.0},
    ]
    for e in events:
        log.append(e)
    # Each event is on the disk at once (flushed), before the log is closed.
    saved = [e["type"] for e in lines(log.dir / LOG_NAME)]
    assert saved == [
        "session",
        "source_status",
        "speaker",
        "segment",
        "translation",
        "translation_status",
        "merge",
        "audio_file",
    ]
    log.close()
    log.append(SEGMENT)  # a closed log writes nothing
    assert len(lines(log.dir / LOG_NAME)) == len(saved)


def test_session_ids_follow_the_start_time(tmp_path):
    store = SessionStore(tmp_path)
    a, b = store.create(1000.0), store.create(1000.0)
    assert a.id != b.id and b.id == a.id + "-2"
    assert store.dir == tmp_path / "sessions"


def test_recover_closes_logs_with_no_stop_as_interrupted(tmp_path):
    store = SessionStore(tmp_path)
    crashed = store.create(1000.0)
    for e in (STARTED, SPEAKER, SEGMENT):
        crashed.append(e)
    # The crash cut the last write in the middle of a line.
    with (crashed.dir / LOG_NAME).open("a") as f:
        f.write('{"type":"segment","id":"mon/2","te')
    stopped = store.create(2000.0)
    stopped.append({**STARTED, "started_at": 2000.0})
    stopped.append({**STARTED, "state": "stopped", "started_at": 2000.0, "ended_at": 2010.0})
    for log in (crashed, stopped):
        log.close()

    assert store.recover() == [crashed.id]
    assert store.recover() == []  # closed once only
    events = read_events(crashed.dir / LOG_NAME)
    assert [e["type"] for e in events] == ["session", "speaker", "segment", "session"]
    assert events[-1] == {
        "type": "session",
        "state": "interrupted",
        "started_at": 1000.0,
        "target_lang": "en",
        "ended_at": 1004.5,  # the end of the last Segment
    }
    summary = store.load(crashed.id).summary()
    assert summary["interrupted"] and summary["state"] == "interrupted"
    assert summary["length"] == 4.5
    assert summary["speakers"] == [{"id": "mon#1", "label": "Speaker 1", "display_name": None}]
    other = store.load(stopped.id).summary()
    assert not other["interrupted"] and other["length"] == 10.0


def test_replay_gives_the_snapshot_of_a_stopped_session(tmp_path):
    store = SessionStore(tmp_path)
    log = store.create(1000.0)
    for e in (STARTED, SPEAKER, SEGMENT, {**STARTED, "state": "stopped", "ended_at": 1005.0}):
        log.append(e)
    log.close()
    snap = store.load(log.id).transcript().snapshot()
    assert snap[0]["state"] == "stopped"
    assert [e["type"] for e in snap] == ["session", "speaker", "segment"]


def test_delete_removes_log_and_audio_and_rejects_bad_ids(tmp_path):
    store = SessionStore(tmp_path)
    log = store.create(1000.0)
    log.append(STARTED)
    log.close()
    (log.dir / "audio").mkdir()
    (log.dir / "audio" / "mon-001.pcm").write_bytes(b"\0\0")
    for bad in ("..", "../sessions", "x", "", log.id + "/../.."):
        assert store.load(bad) is None
        assert not store.delete(bad)
    assert store.ids() == [log.id]
    assert store.delete(log.id)
    assert not log.dir.exists() and store.ids() == []
    assert store.dir.is_dir()


def chunk(start_s: float, value: int = 1, n: int = 1600) -> AudioChunk:
    sample = value.to_bytes(2, "little", signed=True)
    return AudioChunk("monitor:spk", round(start_s * NS_PER_S), sample * n)


def test_audio_recorder_starts_a_new_file_after_each_break(tmp_path):
    events = []
    rec = AudioRecorder(tmp_path, "monitor:spk", 0, events.append)
    rec.write(chunk(0.5))
    rec.write(chunk(0.6))  # contiguous
    rec.write(chunk(2.0, 2))  # the capture moved its anchor: a gap of 1.3 s
    rec.capture_break()  # the capture restarted
    rec.write(chunk(3.0, 3))
    rec.close()
    assert [e["path"] for e in events] == [
        "audio/monitor_spk-001.pcm",
        "audio/monitor_spk-002.pcm",
        "audio/monitor_spk-003.pcm",
    ]
    assert [e["start"] for e in events] == [0.5, 2.0, 3.0]
    assert all(
        e["type"] == "audio_file"
        and e["source_key"] == "monitor:spk"
        and e["sample_rate"] == 16000
        and e["format"] == "s16le"
        for e in events
    )
    sizes = [(tmp_path / e["path"]).stat().st_size for e in events]
    assert sizes == [6400, 3200, 3200]
    assert (tmp_path / events[1]["path"]).read_bytes()[:2] == b"\x02\x00"
