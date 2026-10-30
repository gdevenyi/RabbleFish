"""The Markdown and JSON exports of one Session (decided in issue #30).

Both formats are built from a `Transcript`: the replay of a saved event log, or the state
of the live Session. Partial text is never exported, so an export of the live Session is
a snapshot of the moment, marked "in progress".

The rules match the Timeline of the UI (`frontend/src/timeline`), so both agree:

- **Merges** (`mergeTargets` in `state.ts`): a Segment goes to the end of the Merge chain
  of its Speaker. A Merge into the same Speaker, a repeated Merge and a Merge that closes a
  loop are ignored.
- **Language switch** (`language.ts`): a Segment starts a switch when its language is not
  the last language of the same Speaker (after Merges). A Segment with no language does
  not start or end a switch.
- **Silence fold** (`timeScale.ts`): a silence of all Speakers longer than
  `FOLD_AFTER_S`, also before the first Segment. There is no fold after the last Segment.
- **Times** (`formatTime`, `formatDuration` in `model.ts`): `mm:ss`, `h:mm:ss` after one
  hour; "45 s", "2 min 05 s".

All times in the JSON are seconds since the Session started.
"""

import json
from dataclasses import dataclass
from datetime import datetime, tzinfo

from ltt.transcript import Transcript

FOLD_AFTER_S = 20.0
JSON_VERSION = 1


@dataclass
class Fold:
    start: float
    end: float

    @property
    def length(self) -> float:
        return self.end - self.start


def merge_targets(merges: list[dict]) -> dict[str, str]:
    """Map from a merged Speaker to the Speaker that now holds its Segments."""
    direct: dict[str, str] = {}
    for m in merges:
        src, dst = m["from_speaker_id"], m["into_speaker_id"]
        if src == dst or direct.get(src) == dst:
            continue
        # A Merge that closes a loop would hide both Speakers: ignore it (as the UI does).
        if _resolve(direct, dst) == src:
            continue
        direct[src] = dst
    return {src: _resolve(direct, src) for src in direct}


def _resolve(direct: dict[str, str], speaker_id: str) -> str:
    seen = {speaker_id}
    while speaker_id in direct:
        nxt = direct[speaker_id]
        if nxt in seen:
            break
        seen.add(nxt)
        speaker_id = nxt
    return speaker_id


def language_switches(segments: list[dict], speaker_of: dict[str, str]) -> set[str]:
    """The IDs of the Segments that start a Language switch; `segments` sorted by start."""
    last: dict[str, str] = {}
    out = set()
    for s in segments:
        lang = s.get("lang")
        if not lang:
            continue
        sp = speaker_of[s["id"]]
        if sp in last and last[sp] != lang:
            out.add(s["id"])
        last[sp] = lang
    return out


def silence_folds(segments: list[dict], fold_after: float = FOLD_AFTER_S) -> list[Fold]:
    """The silences of all Speakers longer than `fold_after` seconds, before and between
    the Segments."""
    folds = []
    cursor = 0.0
    for s in sorted(segments, key=lambda s: s["start"]):
        if s["start"] - cursor > fold_after:
            folds.append(Fold(cursor, s["start"]))
        cursor = max(cursor, s["end"])
    return folds


def format_time(t: float) -> str:
    """ "mm:ss", or "h:mm:ss" after one hour."""
    s = max(0, int(t // 1))
    h, m, ss = s // 3600, s % 3600 // 60, s % 60
    return f"{h}:{m:02d}:{ss:02d}" if h else f"{m:02d}:{ss:02d}"


def format_duration(seconds: float) -> str:
    """ "45 s", "2 min 05 s" (as in the UI), and "1 h 02 min 05 s" after one hour."""
    s = _round_half_up(seconds)
    h, m = s // 3600, s % 3600 // 60
    if h:
        return f"{h} h {m:02d} min {s % 60:02d} s"
    return f"{m} min {s % 60:02d} s" if m else f"{s} s"


def _round_half_up(x: float) -> int:
    # The same rounding as Math.round in the UI.
    return int(x + 0.5) if x >= 0 else -int(-x + 0.5)


class SessionExport:
    """One Session, ready to export: Merges and display names applied.

    `now` is the Unix time of the export; it gives the length of a live Session. `tz` is
    the time zone of the dates (default: the local time zone).
    """

    def __init__(
        self, transcript: Transcript, session_id: str, *, now: float, tz: tzinfo | None = None
    ) -> None:
        t = transcript
        session = t.session or {}
        self.id = session_id
        self.state = session.get("state")
        self.in_progress = self.state == "started"
        self.interrupted = self.state == "interrupted"
        self.started_at = session.get("started_at")
        self.target_lang = session.get("target_lang")
        self.tz = tz
        self.speakers = t.speakers
        self.targets = merge_targets(t.merges)
        # Arrival order interleaves the Sources: sort by start (stable).
        self.segments = sorted(t.segments, key=lambda s: s["start"])
        self.speaker_of = {s["id"]: self.resolve(s["speaker_id"]) for s in self.segments}
        self.switches = language_switches(self.segments, self.speaker_of)
        self.folds = silence_folds(self.segments)
        self.translations = t.translations
        self.audio_files = t.audio_files
        self.duration = self._duration(session, now)
        self.sources = _sources(t)

    def _duration(self, session: dict, now: float) -> float:
        started_at, ended_at = session.get("started_at"), session.get("ended_at")
        if started_at is not None and ended_at is not None:
            return max(0.0, ended_at - started_at)
        if self.in_progress and started_at is not None:
            return max(0.0, now - started_at)
        ends = [s["end"] for s in self.segments] + [a["start"] for a in self.audio_files]
        return max(ends, default=0.0)

    def resolve(self, speaker_id: str) -> str:
        return self.targets.get(speaker_id, speaker_id)

    def name(self, speaker_id: str) -> str:
        """The display name, else the label, of the Speaker after Merges."""
        sp = self.speakers.get(self.resolve(speaker_id))
        if sp is None:
            return speaker_id
        return sp.get("display_name") or sp["label"]

    def _datetime(self) -> datetime | None:
        if self.started_at is None:
            return None
        d = datetime.fromtimestamp(self.started_at, self.tz)
        return d if self.tz else d.astimezone()  # the local time zone

    # --- Markdown -----------------------------------------------------------------

    def markdown(self) -> str:
        lines = [f"# Session {self.id}", ""]
        start = self._datetime()
        header = []
        if start is not None:
            header.append(f"- **Date:** {start:%Y-%m-%d}")
            header.append(f"- **Start:** {start:%H:%M:%S} (UTC{_offset(start)})")
        header.append(f"- **Length:** {format_duration(self.duration)}")
        if self.in_progress:
            header.append("- **State:** in progress (a snapshot; Partial text is left out)")
        elif self.interrupted:
            header.append("- **State:** interrupted (the app ended without a stop)")
        header.append(f"- **Sources:** {', '.join(self.sources) or '—'}")
        if self.target_lang:
            header.append(f"- **Target language:** {self.target_lang}")
        header.append(f"- **Speakers:** {self._speaker_list() or '—'}")
        lines += header
        lines.append("")
        lines += self._body()
        return "\n".join(lines).rstrip("\n") + "\n"

    def _speaker_list(self) -> str:
        out = []
        for sid, sp in self.speakers.items():
            if sid in self.targets:
                continue
            name = sp.get("display_name") or sp["label"]
            notes = []
            if sp.get("display_name") and sp["display_name"] != sp["label"]:
                notes.append(sp["label"])
            merged = [
                m.get("display_name") or m["label"]
                for mid, m in self.speakers.items()
                if self.targets.get(mid) == sid
            ]
            if merged:
                notes.append("merged: " + ", ".join(merged))
            out.append(f"{name} ({'; '.join(notes)})" if notes else name)
        return ", ".join(out)

    def _body(self) -> list[str]:
        lines = []
        folds = list(self.folds)
        for s in self.segments:
            while folds and folds[0].end <= s["start"]:
                fold = folds.pop(0)
                lines += [f"*— {format_duration(fold.length)} silence —*", ""]
            tag = f"[{s['lang']}] " if s["id"] in self.switches else ""
            line = f"**[{format_time(s['start'])}] {self.name(s['speaker_id'])}:** {tag}{s['text']}"
            translation = self.translations.get(s["id"])
            if translation and translation.get("text"):
                # A backslash at the end of a line is a hard line break (CommonMark).
                lines += [line + "\\", f"*{translation['text'].strip()}*"]
            else:
                lines.append(line)
            lines.append("")
        return lines

    # --- JSON ---------------------------------------------------------------------

    def document(self) -> dict:
        start = self._datetime()
        speakers = [
            {
                "id": sid,
                "label": sp["label"],
                "display_name": sp.get("display_name"),
                "source_key": sp.get("source_key"),
                "merged_into": self.targets.get(sid),
            }
            for sid, sp in self.speakers.items()
        ]
        segments = []
        for s in self.segments:
            seg = {
                "id": s["id"],
                "start": s["start"],
                "end": s["end"],
                "speaker_id": self.speaker_of[s["id"]],
            }
            if seg["speaker_id"] != s["speaker_id"]:
                seg["original_speaker_id"] = s["speaker_id"]
            translation = self.translations.get(s["id"])
            seg |= {
                "source_key": s.get("source_key"),
                "text": s["text"],
                "lang": s.get("lang"),
                "translation": translation["text"] if translation else None,
                "words": [
                    {"w": w["w"], "start": w["start"], "end": w["end"]} for w in s.get("words", [])
                ],
            }
            segments.append(seg)
        return {
            "version": JSON_VERSION,
            "session": {
                "id": self.id,
                "started_at": start.isoformat() if start else None,
                "duration_s": round(self.duration, 3),
                "sources": self.sources,
                "target_language": self.target_lang,
                "interrupted": self.interrupted,
                "in_progress": self.in_progress,
            },
            "speakers": speakers,
            "segments": segments,
            "audio_files": [
                {
                    "source_key": a["source_key"],
                    "path": a["path"],
                    "start": a["start"],
                    "sample_rate": a.get("sample_rate"),
                    "format": a.get("format"),
                }
                for a in self.audio_files
            ],
        }

    def json(self) -> str:
        return json.dumps(self.document(), ensure_ascii=False, indent=2) + "\n"


def _offset(d: datetime) -> str:
    off = d.utcoffset()
    if off is None:
        return ""
    minutes = int(off.total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    h, m = divmod(abs(minutes), 60)
    return f"{sign}{h:02d}:{m:02d}"


def _sources(t: Transcript) -> list[str]:
    """The keys of the Sources of the Session, in order of first appearance. The log has
    no Source descriptions, so the keys are used."""
    keys: dict[str, None] = {}
    for e in [*t.speakers.values(), *t.segments, *t.audio_files]:
        if e.get("source_key"):
            keys.setdefault(e["source_key"], None)
    return list(keys)
