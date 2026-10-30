"""From NeMo-Speech.cpp realtime events to our UI events, and the Session state.

Terms follow GLOSSARY.md. The event contract is in gdevenyi/live-transcribe-translate#11:

- `partial` {source_key, text, audio_time}: the Partial text of a Source.
- `segment` {id, source_key, speaker_id, start, end, text, words[{w, start, end}], lang}:
  one finalized piece of speech of one Speaker. Each NeMo final is split at every change
  of speaker.
- `speaker` {id, source_key, label, display_name}: when it first appears and after a rename.

All times are seconds since the Session started: the monotonic time of the captured
sample that NeMo's audio time points to, minus the Session start. NeMo counts audio time
from the first sample sent on one connection, so each connection has its own TimeMap.
"""

from bisect import bisect_right
from collections.abc import Callable
from dataclasses import dataclass, field

from ltt.capture import NS_PER_S, SAMPLE_RATE

MIN_LANG_WORDS = 3  # shorter Segments get no language
CONTINUITY_TOLERANCE_NS = 1_000_000

DELTA = "conversation.item.input_audio_transcription.delta"
COMPLETED = "conversation.item.input_audio_transcription.completed"

LanguageDetector = Callable[[str], str | None]


class TimeMap:
    """Maps the audio time of one NeMo connection to the monotonic clock.

    It keeps one entry for each run of contiguous audio, so a capture gap (the capture
    moves its anchor) does not shift the times of later words.
    """

    def __init__(self) -> None:
        self._offsets: list[int] = []  # sample offset on the connection where a run starts
        self._starts_ns: list[int] = []  # monotonic time of that sample
        self.samples = 0  # samples given to the connection so far

    def add(self, start_ns: int, n_samples: int) -> None:
        """Record `n_samples` that start at `start_ns`, in the order they are sent."""
        if self._offsets:
            expected = self.to_ns_samples(self.samples)
            contiguous = abs(start_ns - expected) <= CONTINUITY_TOLERANCE_NS
        else:
            contiguous = False
        if not contiguous:
            self._offsets.append(self.samples)
            self._starts_ns.append(start_ns)
        self.samples += n_samples

    def to_ns_samples(self, sample: int) -> int:
        i = max(0, bisect_right(self._offsets, sample) - 1)
        return self._starts_ns[i] + (sample - self._offsets[i]) * NS_PER_S // SAMPLE_RATE

    def to_ns(self, seconds: float) -> int | None:
        """Return the monotonic time of NeMo audio time `seconds`, or None with no audio."""
        if not self._offsets:
            return None
        return self.to_ns_samples(round(seconds * SAMPLE_RATE))


@dataclass
class Speaker:
    id: str
    source_key: str
    label: str
    display_name: str | None = None

    def event(self) -> dict:
        return {
            "type": "speaker",
            "id": self.id,
            "source_key": self.source_key,
            "label": self.label,
            "display_name": self.display_name,
        }


@dataclass
class SourceMapper:
    """Turns the NeMo events of one Source into our events.

    A "single speaker" Source has one Speaker, `<key>#0`, labelled with the Source
    description. In a "diarize" Source, each NeMo speaker label of one connection gets the
    next number of the Source (`<key>#1`, "Speaker 1", ...), in order of first appearance.
    NeMo labels belong to one connection, so after a reconnect they get new Speakers.
    """

    source_key: str
    description: str
    diarize: bool
    session_start_ns: int
    detect_language: LanguageDetector = lambda _text: None
    time_map: TimeMap = field(default_factory=TimeMap)
    _labels: dict[object, Speaker] = field(default_factory=dict)  # NeMo label -> Speaker
    _single: Speaker | None = None
    _speaker_count: int = 0
    _segment_count: int = 0
    _partial: str = ""

    def new_connection(self) -> None:
        """Start a new NeMo connection: new audio time, new speaker labels."""
        self.time_map = TimeMap()
        self._labels = {}
        self._partial = ""

    def audio(self, start_ns: int, n_samples: int) -> None:
        """Record audio sent to the current connection."""
        self.time_map.add(start_ns, n_samples)

    def seconds(self, nemo_time: float) -> float | None:
        ns = self.time_map.to_ns(nemo_time)
        if ns is None:
            return None
        return round((ns - self.session_start_ns) / NS_PER_S, 3)

    def handle(self, event: dict) -> list[dict]:
        """Return our events for one NeMo server event."""
        kind = event.get("type")
        if kind == DELTA:
            delta = event.get("delta") or ""
            if not delta:
                return []
            self._partial += delta
            text = self._partial.strip()
            if not text:
                return []
            return [self._partial_event(text, event.get("audio_processed"))]
        if kind == COMPLETED:
            had_partial = bool(self._partial.strip())
            self._partial = ""
            out = self._segments(event.get("words") or [])
            if not any(e["type"] == "segment" for e in out) and had_partial:
                # A final with no words: clear the Partial text with an empty one.
                out.append(self._partial_event("", event.get("audio_processed")))
            return out
        return []

    def _partial_event(self, text: str, audio_processed: float | None) -> dict:
        audio_time = None if audio_processed is None else self.seconds(audio_processed)
        return {
            "type": "partial",
            "source_key": self.source_key,
            "text": text,
            "audio_time": audio_time,
        }

    def _speaker(self, label: object) -> tuple[Speaker, bool]:
        """Return the Speaker for a NeMo label, and whether it is new."""
        if not self.diarize:
            if self._single is None:
                self._single = Speaker(f"{self.source_key}#0", self.source_key, self.description)
                return self._single, True
            return self._single, False
        if label in self._labels:
            return self._labels[label], False
        self._speaker_count += 1
        n = self._speaker_count
        speaker = Speaker(f"{self.source_key}#{n}", self.source_key, f"Speaker {n}")
        self._labels[label] = speaker
        return speaker, True

    def _segments(self, words: list[dict]) -> list[dict]:
        words = [w for w in words if (w.get("word") or "").strip()]
        if not words:
            return []
        labels = _fill_labels([w.get("speaker") for w in words])
        runs: list[tuple[object, list[dict]]] = []
        for word, label in zip(words, labels, strict=True):
            if runs and runs[-1][0] == label:
                runs[-1][1].append(word)
            else:
                runs.append((label, [word]))
        out: list[dict] = []
        for label, run in runs:
            speaker, new = self._speaker(label)
            if new:
                out.append(speaker.event())
            out.append(self._segment(speaker, run))
        return out

    def _segment(self, speaker: Speaker, run: list[dict]) -> dict:
        self._segment_count += 1
        words = [
            {"w": w["word"], "start": self.seconds(w["start"]), "end": self.seconds(w["end"])}
            for w in run
        ]
        text = " ".join(w["w"] for w in words)
        lang = self.detect_language(text) if len(words) >= MIN_LANG_WORDS else None
        return {
            "type": "segment",
            "id": f"{self.source_key}/{self._segment_count}",
            "source_key": self.source_key,
            "speaker_id": speaker.id,
            "start": words[0]["start"],
            "end": words[-1]["end"],
            "text": text,
            "words": words,
            "lang": lang,
        }


def _fill_labels(labels: list[object]) -> list[object]:
    """Give a word with no speaker label the label of the word before (or after) it."""
    out = list(labels)
    for i in range(1, len(out)):
        if out[i] is None:
            out[i] = out[i - 1]
    for i in range(len(out) - 2, -1, -1):
        if out[i] is None:
            out[i] = out[i + 1]
    return out


class LanguageIdentifier:
    """CPU-only text language identifier (lingua n-gram models), limited to `languages`."""

    def __init__(self, languages: list[str]) -> None:
        from lingua import IsoCode639_1, Language, LanguageDetectorBuilder

        langs = [Language.from_iso_code_639_1(IsoCode639_1.from_str(c)) for c in languages]
        if len(langs) == 1:
            self._only = languages[0].lower()
            self._detector = None
        else:
            self._only = None
            self._detector = LanguageDetectorBuilder.from_languages(*langs).build()

    def __call__(self, text: str) -> str | None:
        if self._detector is None:
            return self._only
        lang = self._detector.detect_language_of(text)
        return lang.iso_code_639_1.name.lower() if lang is not None else None


class Transcript:
    """The state of the current (or last) Session, kept for the /ws snapshot."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.session: dict | None = None
        self.statuses: dict[str, dict] = {}
        self.speakers: dict[str, dict] = {}
        self.segments: list[dict] = []
        self.merges: list[dict] = []
        self.partials: dict[str, dict] = {}

    def apply(self, event: dict) -> None:
        kind = event["type"]
        if kind == "session":
            self.session = event
            if event["state"] == "stopped":
                self.partials.clear()
        elif kind == "source_status":
            self.statuses[event["source_key"]] = event
        elif kind == "speaker":
            self.speakers[event["id"]] = event
        elif kind == "segment":
            self.segments.append(event)
            self.partials.pop(event["source_key"], None)
        elif kind == "partial":
            if event["text"]:
                self.partials[event["source_key"]] = event
            else:
                self.partials.pop(event["source_key"], None)
        elif kind == "merge":
            self.merges.append(event)

    def merged_away(self, speaker_id: str) -> bool:
        return any(m["from_speaker_id"] == speaker_id for m in self.merges)

    def snapshot(self) -> list[dict]:
        """The events that bring a new UI to the current state; empty before any Session."""
        if self.session is None:
            return []
        return [
            self.session,
            *self.statuses.values(),
            *self.speakers.values(),
            *self.segments,
            *self.merges,
            *self.partials.values(),
        ]
