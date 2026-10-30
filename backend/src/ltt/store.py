"""Saved Sessions: one append-only JSON Lines event log for each Session (issue #29).

Layout: `<base>/sessions/<YYYY-MM-DDTHH-MM-SS>/events.jsonl`, and the saved audio in
`audio/` next to it. The directory name is the local time of the Session start, with
`-2`, `-3`, ... when two Sessions start in the same second. `<base>` is `LTT_DATA_DIR`,
else `$XDG_DATA_HOME/live-transcribe-translate`, else
`~/.local/share/live-transcribe-translate`.

Each line is one event, exactly as on `/ws`. Only the event types in `SAVED_TYPES` are
saved. Each event is written and flushed when it happens, so an app crash loses nothing;
`fsync` runs at most every `FSYNC_INTERVAL_S` (and at stop), so a power failure loses at
most about that much.

A log with no `session` "stopped" or "interrupted" line is an Interrupted session (the
app ended without a stop). At start-up `SessionStore.recover()` closes each one with:

    {"type": "session", "state": "interrupted", "started_at": ..., "target_lang": ...,
     "ended_at": ...}

where `ended_at` is `started_at` plus the last known Session time (the end of the last
Segment, gap or audio file). An Interrupted session is never continued.

To open a saved Session, its log is replayed through `Transcript`, the same code that
builds the `/ws` snapshot.
"""

import json
import logging
import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from ltt.capture import BYTES_PER_SAMPLE, SAMPLE_RATE
from ltt.transcript import Transcript

log = logging.getLogger(__name__)

APP_DIR = "live-transcribe-translate"
LOG_NAME = "events.jsonl"
AUDIO_DIR = "audio"
FSYNC_INTERVAL_S = 2.0
SAVED_TYPES = frozenset(
    {
        "session",
        "speaker",
        "segment",
        "translation",
        "translation_status",
        "merge",
        "source_status",
        "audio_file",
    }
)
CLOSED_STATES = ("stopped", "interrupted")
SESSION_ID = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}(-\d+)?$")


def default_data_dir() -> Path:
    if env := os.environ.get("LTT_DATA_DIR"):
        return Path(env)
    xdg = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(xdg) / APP_DIR


class Syncer:
    """An append-only file that is flushed at each write and fsynced at most every
    `FSYNC_INTERVAL_S`. `sync()` fsyncs the writes that are not on the disk yet."""

    def __init__(self, path: Path) -> None:
        self.path = path
        # Unbuffered: each write goes to the kernel at once, so a crash loses nothing.
        self._fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        self._dirty = False
        self._last_sync = time.monotonic()

    def write(self, data: bytes) -> None:
        view = memoryview(data)
        while view:
            n = os.write(self._fd, view)
            view = view[n:]
        self._dirty = True
        if time.monotonic() - self._last_sync >= FSYNC_INTERVAL_S:
            self.sync()

    def sync(self) -> None:
        if self._dirty and self._fd >= 0:
            os.fsync(self._fd)
            self._dirty = False
        self._last_sync = time.monotonic()

    def close(self) -> None:
        if self._fd >= 0:
            self.sync()
            os.close(self._fd)
            self._fd = -1

    @property
    def closed(self) -> bool:
        return self._fd < 0


class SessionLog:
    """The event log of one Session; it writes only the saved event types."""

    def __init__(self, session_id: str, directory: Path) -> None:
        self.id = session_id
        self.dir = directory
        self._file = Syncer(directory / LOG_NAME)

    def append(self, event: dict) -> None:
        if event.get("type") not in SAVED_TYPES or self._file.closed:
            return
        self._file.write(_line(event))
        if event["type"] == "session" and event.get("state") in CLOSED_STATES:
            self._file.sync()

    def sync(self) -> None:
        self._file.sync()

    def close(self) -> None:
        self._file.close()


def _line(event: dict) -> bytes:
    return (json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n").encode()


def read_events(path: Path) -> list[dict]:
    """The events of a log. A line that is not valid JSON (a write cut by a crash) is
    left out."""
    events = []
    with path.open("rb") as f:
        for raw in f:
            try:
                event = json.loads(raw)
            except ValueError:
                continue
            if isinstance(event, dict) and "type" in event:
                events.append(event)
    return events


@dataclass
class SavedSession:
    id: str
    dir: Path
    events: list[dict]

    def transcript(self) -> Transcript:
        t = Transcript()
        for e in self.events:
            t.apply(e)
        return t

    def start_event(self) -> dict | None:
        return next((e for e in self.events if e["type"] == "session"), None)

    def end_event(self) -> dict | None:
        return next(
            (
                e
                for e in reversed(self.events)
                if e["type"] == "session" and e.get("state") in CLOSED_STATES
            ),
            None,
        )

    def last_time(self) -> float:
        """The last known Session time: the end of the last Segment, gap or audio file."""
        end = 0.0
        for e in self.events:
            kind = e["type"]
            if kind == "segment" and isinstance(e.get("end"), int | float):
                end = max(end, e["end"])
            elif kind == "source_status" and isinstance(e.get("gap"), dict):
                end = max(end, e["gap"].get("end") or 0.0)
            elif kind == "audio_file":
                path = self.dir / e.get("path", "")
                rate = e.get("sample_rate") or SAMPLE_RATE
                try:
                    seconds = path.stat().st_size / BYTES_PER_SAMPLE / rate
                except OSError:
                    seconds = 0.0
                end = max(end, (e.get("start") or 0.0) + seconds)
        return round(end, 3)

    def summary(self) -> dict:
        """Date, length, Speakers and the interrupted flag, for the past-sessions list."""
        start = self.start_event() or {}
        end = self.end_event()
        started_at = start.get("started_at")
        ended_at = end.get("ended_at") if end else None
        if started_at is not None and ended_at is not None:
            length = max(0.0, ended_at - started_at)
        else:
            length = self.last_time()
        t = self.transcript()
        speakers = [
            {"id": s["id"], "label": s["label"], "display_name": s.get("display_name")}
            for s in t.speakers.values()
            if not t.merged_away(s["id"])
        ]
        return {
            "id": self.id,
            "started_at": started_at,
            "ended_at": ended_at,
            "length": round(length, 3),
            "state": end["state"] if end else "started",
            "interrupted": bool(end and end["state"] == "interrupted"),
            "target_lang": start.get("target_lang"),
            "speakers": speakers,
            "segments": len(t.segments),
            "audio_files": len(t.audio_files),
        }


class SessionStore:
    """The saved Sessions under `<base>/sessions`. Nothing touches the disk until the
    first call that needs it."""

    def __init__(self, base: Path) -> None:
        self.base = Path(base)
        self.dir = self.base / "sessions"

    def create(self, started_at: float) -> SessionLog:
        """Make the directory of a new Session and open its log."""
        self.dir.mkdir(parents=True, exist_ok=True)
        name = time.strftime("%Y-%m-%dT%H-%M-%S", time.localtime(started_at))
        candidate, n = name, 1
        while True:
            try:
                (self.dir / candidate).mkdir()
                break
            except FileExistsError:
                n += 1
                candidate = f"{name}-{n}"
        return SessionLog(candidate, self.dir / candidate)

    def path(self, session_id: str) -> Path | None:
        """The directory of a saved Session, or None for an unknown or invalid ID."""
        if not SESSION_ID.match(session_id):
            return None
        d = self.dir / session_id
        if not (d / LOG_NAME).is_file():
            return None
        return d

    def ids(self) -> list[str]:
        if not self.dir.is_dir():
            return []
        return sorted(
            (d.name for d in self.dir.iterdir() if self.path(d.name) is not None), reverse=True
        )

    def load(self, session_id: str) -> SavedSession | None:
        d = self.path(session_id)
        if d is None:
            return None
        return SavedSession(session_id, d, read_events(d / LOG_NAME))

    def recover(self, skip: str | None = None) -> list[str]:
        """Close each log that has no "stopped" line as an Interrupted session.

        Call it at start-up, before any Session runs. Return the IDs it closed.
        """
        closed = []
        for sid in self.ids():
            if sid == skip:
                continue
            saved = self.load(sid)
            if saved is None or saved.end_event() is not None:
                continue
            start = saved.start_event() or {}
            started_at = start.get("started_at")
            marker = {
                "type": "session",
                "state": "interrupted",
                "started_at": started_at,
                "target_lang": start.get("target_lang"),
                "ended_at": None
                if started_at is None
                else round(started_at + saved.last_time(), 3),
            }
            self.append(sid, marker)
            log.warning("session %s was interrupted; closed it", sid)
            closed.append(sid)
        return closed

    def append(self, session_id: str, event: dict) -> None:
        """Append one event to a saved Session's log, and fsync it."""
        d = self.path(session_id)
        if d is None:
            raise KeyError(session_id)
        path = d / LOG_NAME
        f = Syncer(path)
        try:
            # A crash can leave a cut last line: start the new event on a new line.
            size = path.stat().st_size
            if size:
                with path.open("rb") as r:
                    r.seek(size - 1)
                    if r.read(1) != b"\n":
                        f.write(b"\n")
            f.write(_line(event))
        finally:
            f.close()

    def delete(self, session_id: str) -> bool:
        """Delete a saved Session: its log and its audio."""
        d = self.path(session_id)
        if d is None:
            return False
        shutil.rmtree(d)
        return True
