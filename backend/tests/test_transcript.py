"""The mapping from recorded NeMo-Speech.cpp events to our events."""

import pytest
from conftest import DIARIZE_EVENTS, SINGLE_EVENTS, load_events

from rabblefish.capture import NS_PER_S, SAMPLE_RATE
from rabblefish.transcript import (
    COMPLETED,
    LanguageIdentifier,
    SourceMapper,
    TimeMap,
    Transcript,
)

SESSION_START = 1_000 * NS_PER_S
CAPTURE_START = SESSION_START + NS_PER_S // 2  # the first sample is 0.5 s after the start


@pytest.fixture(scope="module")
def detect():
    return LanguageIdentifier(["en", "fr"])


def run(path, diarize, detect=lambda _t: None):
    """Map a recording, with all its audio sent as one contiguous run."""
    mapper = SourceMapper("monitor:spk", "Monitor of Speaker", diarize, SESSION_START, detect)
    mapper.new_connection()
    mapper.audio(CAPTURE_START, 120 * SAMPLE_RATE)
    events = load_events(path)
    out = [(e, mapper.handle(e)) for e in events]
    return mapper, out


def test_time_map_follows_capture_gaps():
    tm = TimeMap()
    tm.add(10 * NS_PER_S, SAMPLE_RATE)  # 1 s of audio at t=10 s
    tm.add(11 * NS_PER_S, SAMPLE_RATE)  # contiguous
    tm.add(15 * NS_PER_S, SAMPLE_RATE)  # after a 3 s capture gap
    assert tm.to_ns(0.5) == 10.5 * NS_PER_S
    assert tm.to_ns(1.5) == 11.5 * NS_PER_S
    assert tm.to_ns(2.25) == 15.25 * NS_PER_S
    assert TimeMap().to_ns(1.0) is None


def test_every_final_splits_at_each_speaker_change():
    _, out = run(DIARIZE_EVENTS, diarize=True)
    finals = [(e, o) for e, o in out if e["type"] == COMPLETED and e["words"]]
    assert len(finals) == 20
    for event, ours in finals:
        segments = [o for o in ours if o["type"] == "segment"]
        labels = [w["speaker"] for w in event["words"]]
        changes = sum(1 for a, b in zip(labels, labels[1:], strict=False) if a != b)
        assert len(segments) == changes + 1
        # The Segments of one final keep all its words, in order.
        assert " ".join(s["text"] for s in segments) == event["transcript"]
        for seg in segments:
            assert seg["text"] == " ".join(w["w"] for w in seg["words"])


def test_diarized_speakers_are_numbered_per_source_in_order_of_first_appearance():
    _, out = run(DIARIZE_EVENTS, diarize=True)
    ours = [o for _, os in out for o in os]
    speakers = [o for o in ours if o["type"] == "speaker"]
    assert [s["id"] for s in speakers] == [f"monitor:spk#{n}" for n in range(1, 6)]
    assert [s["label"] for s in speakers] == [f"Speaker {n}" for n in range(1, 6)]
    assert all(s["display_name"] is None for s in speakers)
    # A Speaker is announced before its first Segment.
    seen = set()
    for o in ours:
        if o["type"] == "speaker":
            seen.add(o["id"])
        elif o["type"] == "segment":
            assert o["speaker_id"] in seen


def test_segment_times_are_seconds_since_session_start():
    _, out = run(DIARIZE_EVENTS, diarize=True)
    event, ours = next((e, o) for e, o in out if e["type"] == COMPLETED)
    seg = ours[-1]
    first = event["words"][0]
    assert seg["start"] == pytest.approx(first["start"] + 0.5, abs=1e-3)
    assert seg["end"] == pytest.approx(event["words"][-1]["end"] + 0.5, abs=1e-3)
    assert seg["words"][0] == {"w": "From", "start": 1.94, "end": 2.02}
    assert seg["id"] == "monitor:spk/1"


def test_languages_are_english_then_french(detect):
    _, out = run(DIARIZE_EVENTS, diarize=True, detect=detect)
    segments = [o for _, os in out for o in os if o["type"] == "segment"]
    long = [s for s in segments if len(s["words"]) >= 3]
    assert all(s["lang"] is None for s in segments if len(s["words"]) < 3)
    assert long[0]["lang"] == "en"
    assert long[-1]["lang"] == "fr"
    assert {s["lang"] for s in long} == {"en", "fr"}


def test_partial_accumulates_deltas_and_a_segment_follows():
    _, out = run(DIARIZE_EVENTS, diarize=True)
    partials = [o for _, os in out for o in os if o["type"] == "partial"]
    assert partials[0]["text"] == "From a"
    assert partials[0]["audio_time"] == pytest.approx(1.68 + 0.5, abs=1e-3)
    first_final = next(i for i, (e, _) in enumerate(out) if e["type"] == COMPLETED)
    last_partial = [o for _, os in out[:first_final] for o in os if o["type"] == "partial"][-1]
    assert last_partial["text"] == "From a plain text file"


def test_single_speaker_source_has_one_speaker_with_the_description():
    _, out = run(SINGLE_EVENTS, diarize=False)
    ours = [o for _, os in out for o in os]
    speakers = [o for o in ours if o["type"] == "speaker"]
    assert speakers == [
        {
            "type": "speaker",
            "id": "monitor:spk#0",
            "source_key": "monitor:spk",
            "label": "Monitor of Speaker",
            "display_name": None,
        }
    ]
    segments = [o for o in ours if o["type"] == "segment"]
    assert len(segments) == 3  # the empty final after the commit gives no Segment
    assert {s["speaker_id"] for s in segments} == {"monitor:spk#0"}


def test_reconnect_gives_new_speaker_ids_but_keeps_the_single_speaker():
    words = [{"word": "hello", "start": 0.1, "end": 0.2, "speaker": 1}]
    final = {"type": COMPLETED, "transcript": "hello", "words": words}
    diar = SourceMapper("monitor:spk", "M", True, SESSION_START)
    single = SourceMapper("microphone:mic", "Mic", False, SESSION_START)
    ids = []
    for _ in range(2):
        for m in (diar, single):
            m.new_connection()
            m.audio(CAPTURE_START, SAMPLE_RATE)
            ids.append([o["speaker_id"] for o in m.handle(final) if o["type"] == "segment"])
    assert ids == [["monitor:spk#1"], ["microphone:mic#0"], ["monitor:spk#2"], ["microphone:mic#0"]]


def test_missing_speaker_label_takes_the_neighbour():
    words = [
        {"word": "a", "start": 0.1, "end": 0.2},
        {"word": "b", "start": 0.2, "end": 0.3, "speaker": 2},
        {"word": "c", "start": 0.3, "end": 0.4},
    ]
    m = SourceMapper("monitor:spk", "M", True, SESSION_START)
    m.new_connection()
    m.audio(SESSION_START, SAMPLE_RATE)
    segs = [o for o in m.handle({"type": COMPLETED, "words": words}) if o["type"] == "segment"]
    assert [s["text"] for s in segs] == ["a b c"]


def test_a_final_with_no_words_clears_the_partial():
    m = SourceMapper("monitor:spk", "M", True, SESSION_START)
    m.new_connection()
    m.audio(SESSION_START, SAMPLE_RATE)
    delta = "conversation.item.input_audio_transcription.delta"
    assert m.handle({"type": delta, "delta": "uh", "audio_processed": 0.5})[0]["text"] == "uh"
    out = m.handle({"type": COMPLETED, "transcript": "", "words": [], "audio_processed": 1.0})
    assert [(o["type"], o["text"]) for o in out] == [("partial", "")]


def test_transcript_snapshot():
    t = Transcript()
    assert t.snapshot() == []
    session = {"type": "session", "state": "started", "started_at": 1.0}
    status = {"type": "source_status", "source_key": "k", "state": "live", "message": None}
    speaker = {"type": "speaker", "id": "k#1", "source_key": "k", "label": "Speaker 1"}
    partial = {"type": "partial", "source_key": "k", "text": "hel", "audio_time": 1.0}
    segment = {"type": "segment", "id": "k/1", "source_key": "k", "speaker_id": "k#1"}
    for e in (session, status, speaker, partial):
        t.apply(e)
    assert t.snapshot() == [session, status, speaker, partial]
    t.apply(segment)  # a Segment clears the Partial text of its Source
    t.apply({**speaker, "display_name": "Alice"})
    assert t.snapshot() == [session, status, {**speaker, "display_name": "Alice"}, segment]
