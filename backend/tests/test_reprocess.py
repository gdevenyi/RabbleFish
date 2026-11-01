"""The `rabblefish reprocess` command: the audio-file mapping, the word-to-Segment
events, the reprocessed log, and the failure cases. The offline transcription runs
against fakes: no GPU, no nemo-speech binary, no pyannote."""

import json
import sys
import wave
from pathlib import Path

import pytest

from rabblefish import cli, reprocess
from rabblefish.reprocess import (
    ReprocessError,
    label_words_with_turns,
    load_audio_files,
    pcm_to_wav,
    reprocess_session,
    words_to_events,
)
from rabblefish.store import LOG_NAME, read_events
from rabblefish.transcript import LanguageIdentifier, Transcript

LANGS = ("en", "fr")


def make_pcm(path: Path, seconds: float = 0.5, rate: int = 16000) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"\x00\x00" * int(rate * seconds))


def make_session(data_dir: Path, files=("mic-001",)) -> tuple[str, Path]:
    """One saved Session with saved audio; returns (id, session dir)."""
    sid = "2026-11-01T10-00-00"
    directory = data_dir / "sessions" / sid
    (directory / "audio").mkdir(parents=True)
    lines = []
    for i, name in enumerate(files):
        pcm = directory / "audio" / f"{name}.pcm"
        make_pcm(pcm)
        lines.append(
            {
                "type": "audio_file",
                "source_key": f"microphone:{name}",
                "path": f"audio/{name}.pcm",
                "start": 1.5 * i,
                "sample_rate": 16000,
                "format": "s16le",
            }
        )
    (directory / LOG_NAME).write_text(
        "".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8"
    )
    return sid, directory


def fake_transcribe_result(words):
    """A `transcribe_file` stand-in that writes the given words to the output path."""

    def transcribe(binary, wav, asr_model, diar_model, out_json):
        Path(out_json).write_text(json.dumps({"words": words}), encoding="utf-8")
        return {"words": words}

    return transcribe


def test_pcm_to_wav_round_trips_the_samples(tmp_path):
    pcm = tmp_path / "a.pcm"
    pcm.write_bytes(b"\x01\x00\x02\x00\x03\x00\x04\x00")
    wav = tmp_path / "a.wav"
    pcm_to_wav(pcm, wav, 16000)
    with wave.open(str(wav), "rb") as wf:
        assert wf.getframerate() == 16000 and wf.getnchannels() == 1 and wf.getsampwidth() == 2
        assert wf.readframes(10) == b"\x01\x00\x02\x00\x03\x00\x04\x00"


def test_load_audio_files_maps_the_log_entries(tmp_path):
    sid, directory = make_session(tmp_path, files=("a", "b"))
    audio = load_audio_files(directory)
    got = [(a.source_key, a.start) for a in audio]
    assert got == [("microphone:a", 0.0), ("microphone:b", 1.5)]


def test_load_audio_files_reports_a_missing_file(tmp_path):
    sid, directory = make_session(tmp_path)
    (directory / "audio" / "mic-001.pcm").unlink()
    with pytest.raises(ReprocessError, match="missing"):
        load_audio_files(directory)


def test_load_audio_files_rejects_an_unknown_format(tmp_path):
    sid, directory = make_session(tmp_path)
    log = directory / LOG_NAME
    log.write_text(log.read_text(encoding="utf-8").replace('"s16le"', '"flac"'), encoding="utf-8")
    with pytest.raises(ReprocessError, match="unsupported audio format"):
        load_audio_files(directory)


def test_words_to_events_splits_at_speaker_changes_and_maps_the_times(tmp_path):
    lang = LanguageIdentifier(list(LANGS))
    words = [
        {"word": "bonjour", "start": 0.2, "end": 0.5, "speaker": 1},
        {"word": "à", "start": 0.5, "end": 0.6, "speaker": 1},
        {"word": "tous", "start": 0.6, "end": 0.9, "speaker": 1},
        {"word": "hello", "start": 1.2, "end": 1.4, "speaker": 2},
        {"word": "my", "start": 1.4, "end": 1.5, "speaker": 2},
        {"word": "friends", "start": 1.5, "end": 1.8, "speaker": 2},
    ]
    speakers, segments = words_to_events(words, "microphone:m", 3.25, lang)
    assert [s["label"] for s in speakers] == ["Speaker 1", "Speaker 2"]
    assert speakers[0]["id"] == "microphone:m#r1"
    assert [(s["id"], s["start"], s["end"], s["lang"]) for s in segments] == [
        ("microphone:m/r1", 3.45, 4.15, "fr"),
        ("microphone:m/r2", 4.45, 5.05, "en"),
    ]
    assert segments[0]["speaker_id"] == "microphone:m#r1"
    assert segments[0]["text"] == "bonjour à tous"


def test_words_to_events_gives_no_language_to_short_segments(tmp_path):
    lang = LanguageIdentifier(list(LANGS))
    speakers, segments = words_to_events(
        [{"word": "ok", "start": 0.0, "end": 0.3, "speaker": 1}], "s", 0.0, lang
    )
    assert len(speakers) == 1 and segments[0]["lang"] is None


def test_words_to_events_splits_one_speaker_at_a_long_pause(tmp_path):
    lang = LanguageIdentifier(list(LANGS))
    words = [
        {"word": "bonjour", "start": 0.2, "end": 0.5, "speaker": 1},
        {"word": "à", "start": 0.5, "end": 0.6, "speaker": 1},
        {"word": "tous", "start": 0.6, "end": 0.9, "speaker": 1},
        # 2 s of silence, same speaker: the live endpointing would have finalized.
        {"word": "alors", "start": 2.9, "end": 3.2, "speaker": 1},
        {"word": "on", "start": 3.2, "end": 3.3, "speaker": 1},
        {"word": "commence", "start": 3.3, "end": 3.7, "speaker": 1},
    ]
    speakers, segments = words_to_events(words, "s", 0.0, lang)
    assert len(speakers) == 1
    assert [(s["id"], s["start"], s["end"]) for s in segments] == [
        ("s/r1", 0.2, 0.9),
        ("s/r2", 2.9, 3.7),
    ]


def test_label_words_with_turns_takes_the_largest_overlap():
    words = [{"word": "a", "start": 0.2, "end": 0.8}, {"word": "b", "start": 0.8, "end": 1.2}]
    turns = [(0.0, 0.55, "A"), (0.55, 2.0, "B")]
    labeled = label_words_with_turns(words, turns)
    assert [w["speaker"] for w in labeled] == ["A", "B"]


def test_reprocess_session_writes_the_reprocessed_log(tmp_path, monkeypatch):
    sid, directory = make_session(tmp_path, files=("a", "b"))
    words = [
        {"word": "bonjour", "start": 0.2, "end": 0.5, "speaker": 1},
        {"word": "à", "start": 0.5, "end": 0.6, "speaker": 1},
        {"word": "tous", "start": 0.6, "end": 0.9, "speaker": 1},
    ]
    monkeypatch.setattr(reprocess, "transcribe_file", fake_transcribe_result(words))
    summary = reprocess_session(
        directory, binary="/bin/true", asr_model="m.gguf", diar_model="d.gguf", languages=LANGS
    )
    assert summary["files"] == 2 and summary["segments"] == 2 and summary["speakers"] == 2
    out = [json.loads(line) for line in (directory / "reprocessed.jsonl").read_text().splitlines()]
    assert out[0]["type"] == "reprocess" and out[0]["asr_model"] == "m.gguf"
    assert [e["type"] for e in out[1:-1]] == ["speaker", "speaker", "segment", "segment"]
    assert out[-1] == {"type": "reprocess", "state": "finished", "segments": 2, "speakers": 2}
    # The second file starts at Session time 1.5 s: the same words land later.
    second = [e for e in out[1:-1] if e.get("start") == 1.7]
    assert len(second) == 1


def test_reprocess_session_refuses_an_existing_output(tmp_path, monkeypatch):
    sid, directory = make_session(tmp_path)
    monkeypatch.setattr(reprocess, "transcribe_file", fake_transcribe_result([]))
    output = directory / "reprocessed.jsonl"
    output.write_text("{}", encoding="utf-8")
    with pytest.raises(ReprocessError, match="--overwrite"):
        reprocess_session(directory, binary="b", asr_model="m", diar_model="d", languages=LANGS)
    reprocess_session(
        directory,
        binary="b",
        asr_model="m",
        diar_model="d",
        languages=LANGS,
        overwrite=True,
        output=output,
    )
    assert "reprocess" in output.read_text(encoding="utf-8")


def test_reprocess_session_rejects_an_unknown_diarizer(tmp_path):
    sid, directory = make_session(tmp_path)
    with pytest.raises(ReprocessError, match="unknown diarizer"):
        reprocess_session(
            directory,
            binary="b",
            asr_model="m",
            diar_model="d",
            diarizer="vosk",
            languages=LANGS,
        )


def test_reprocess_session_pyannote_labels_the_words(tmp_path, monkeypatch):
    sid, directory = make_session(tmp_path)
    seen = {}
    words = [
        {"word": "bonjour", "start": 0.2, "end": 0.9},
        {"word": "à", "start": 0.9, "end": 1.1},
        {"word": "tous", "start": 1.1, "end": 1.4},
    ]

    def transcribe(binary, wav, asr_model, diar_model, out_json):
        seen["diar_model"] = diar_model
        Path(out_json).write_text(json.dumps({"words": words}), encoding="utf-8")
        return {"words": words}

    def diarize(wav, min_speakers, max_speakers):
        seen["speakers"] = (min_speakers, max_speakers)
        return [(0.0, 1.0, "SPEAKER_00"), (1.0, 2.0, "SPEAKER_01")]

    monkeypatch.setattr(reprocess, "transcribe_file", transcribe)
    monkeypatch.setattr(reprocess, "pyannote_turns", diarize)
    summary = reprocess_session(
        directory,
        binary="b",
        asr_model="m",
        diar_model="d",
        diarizer="pyannote",
        min_speakers=2,
        max_speakers=4,
        languages=LANGS,
    )
    assert seen["diar_model"] is None and seen["speakers"] == (2, 4)
    assert summary["speakers"] == 2
    lines = (directory / "reprocessed.jsonl").read_text().splitlines()
    assert json.loads(lines[1])["id"].endswith("#r1")


def test_cli_reprocess_unknown_session(capsys, tmp_path):
    code = cli.main(["reprocess", "2020-01-01T00-00-00"])
    out, err = capsys.readouterr()
    assert code == cli.EXIT_NOT_FOUND and "unknown session" in err


def test_cli_reprocess_writes_the_log(capsys, tmp_path, monkeypatch):
    sid, directory = make_session(tmp_path / "data")
    monkeypatch.setattr(reprocess, "transcribe_file", fake_transcribe_result([]))
    code = cli.main(["reprocess", sid, "--nemo-speech", "/bin/true"])
    out, err = capsys.readouterr()
    assert code == 0 and "Wrote" in err and (directory / "reprocessed.jsonl").is_file()


def test_cli_reprocess_reports_a_failure(capsys, tmp_path, monkeypatch):
    sid, directory = make_session(tmp_path / "data")

    def fail(*args, **kwargs):
        raise ReprocessError("no such binary")

    monkeypatch.setattr(reprocess, "reprocess_session", fail)
    code = cli.main(["reprocess", sid, "--nemo-speech", "/bin/true"])
    out, err = capsys.readouterr()
    assert code == cli.EXIT_USAGE and "reprocess: no such binary" in err


def test_cli_reprocess_session_store_loads_what_the_command_wrote(tmp_path, monkeypatch):
    sid, directory = make_session(tmp_path / "data")
    words = [
        {"word": "bonjour", "start": 0.2, "end": 0.5, "speaker": 1},
        {"word": "à", "start": 0.5, "end": 0.6, "speaker": 1},
        {"word": "tous", "start": 0.6, "end": 0.9, "speaker": 1},
    ]
    monkeypatch.setattr(reprocess, "transcribe_file", fake_transcribe_result(words))
    assert cli.main(["reprocess", sid, "--nemo-speech", "/bin/true"]) == 0
    # The reprocessed log is a separate file: the consumer applies it explicitly. Its
    # events must build the same Transcript as the live schema does.
    transcript = Transcript()
    for event in read_events(directory / "reprocessed.jsonl"):
        transcript.apply(event)
    assert [s["text"] for s in transcript.segments] == ["bonjour à tous"]
    assert "microphone:mic-001#r1" in transcript.speakers


def two_files_on_one_source(data_dir: Path) -> tuple[str, Path]:
    """One Source with two files: the capture broke, so the recorder started a new file."""
    sid, directory = make_session(data_dir, files=("mic-001", "mic-002"))
    log = directory / LOG_NAME
    text = log.read_text(encoding="utf-8")
    log.write_text(
        text.replace("microphone:mic-001", "microphone:m").replace(
            "microphone:mic-002", "microphone:m"
        ),
        encoding="utf-8",
    )
    return sid, directory


def test_reprocess_session_ids_are_unique_across_the_files_of_one_source(tmp_path, monkeypatch):
    sid, directory = two_files_on_one_source(tmp_path)
    words = [
        {"word": "bonjour", "start": 0.2, "end": 0.5, "speaker": 1},
        {"word": "à", "start": 0.5, "end": 0.6, "speaker": 1},
        {"word": "hello", "start": 1.2, "end": 1.4, "speaker": 2},
    ]
    monkeypatch.setattr(reprocess, "transcribe_file", fake_transcribe_result(words))
    summary = reprocess_session(
        directory, binary="b", asr_model="m", diar_model="d", languages=LANGS
    )
    events = list(read_events(directory / "reprocessed.jsonl"))
    speakers = [e for e in events if e["type"] == "speaker"]
    segments = [e for e in events if e["type"] == "segment"]
    assert [s["id"] for s in speakers] == [f"microphone:m#r{n}" for n in (1, 2, 3, 4)]
    assert [s["label"] for s in speakers] == [f"Speaker {n}" for n in (1, 2, 3, 4)]
    assert [s["id"] for s in segments] == [f"microphone:m/r{n}" for n in (1, 2, 3, 4)]
    # Labels are per file: the same label in the second file is another Speaker.
    assert [s["speaker_id"] for s in segments] == [s["id"] for s in speakers]
    assert summary["speakers"] == 4 and summary["segments"] == 4


def test_label_words_with_turns_gives_a_word_outside_all_turns_the_nearest_turn():
    words = [
        {"word": "a", "start": 0.5, "end": 0.7},
        {"word": "after", "start": 6.8, "end": 6.9},  # touches the end of A, no overlap
        {"word": "before", "start": 8.5, "end": 8.8},  # nearer to the start of B
        {"word": "b", "start": 9.5, "end": 9.7},
    ]
    turns = [(0.0, 6.8, "A"), (9.0, 10.0, "B")]
    labeled = label_words_with_turns(words, turns)
    assert [w["speaker"] for w in labeled] == ["A", "A", "B", "B"]


def test_label_words_with_turns_handles_a_zero_length_word():
    labeled = label_words_with_turns([{"word": "a", "start": 1.0, "end": 1.0}], [(0.0, 2.0, "A")])
    assert labeled[0]["speaker"] == "A"


def test_label_words_with_turns_without_turns_gives_one_speaker():
    lang = LanguageIdentifier(list(LANGS))
    words = [{"word": "a", "start": 0.0, "end": 0.2}, {"word": "b", "start": 0.2, "end": 0.4}]
    speakers, segments = words_to_events(label_words_with_turns(words, []), "s", 0.0, lang)
    assert len(speakers) == 1 and len(segments) == 1


def test_reprocess_session_refuses_a_missing_output_directory_before_transcribing(
    tmp_path, monkeypatch
):
    sid, directory = make_session(tmp_path)

    def must_not_run(*args, **kwargs):
        raise AssertionError("the transcription started")

    monkeypatch.setattr(reprocess, "transcribe_file", must_not_run)
    with pytest.raises(ReprocessError, match="output directory"):
        reprocess_session(
            directory,
            binary="b",
            asr_model="m",
            diar_model="d",
            languages=LANGS,
            output=tmp_path / "none" / "out.jsonl",
        )


def test_transcribe_file_reports_the_cause_of_a_failure(tmp_path):
    binary = tmp_path / "nemo-speech"
    binary.write_text(
        "#!/bin/sh\n"
        "echo '[nemo-speech] transcribe session started' >&2\n"
        "echo 'nemo-speech transcribe: ASR model file does not exist: /m.gguf' >&2\n"
        "echo '[nemo-speech] transcribe session failed (exit code 3)' >&2\n"
        "exit 3\n",
        encoding="utf-8",
    )
    binary.chmod(0o755)
    with pytest.raises(ReprocessError, match="ASR model file does not exist: /m.gguf"):
        reprocess.transcribe_file(
            str(binary), tmp_path / "a.wav", "/m.gguf", None, tmp_path / "a.json"
        )


def test_pyannote_install_hint_is_a_command_that_exists(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "pyannote.audio", None)
    with pytest.raises(ReprocessError) as e:
        reprocess.pyannote_turns(tmp_path / "a.wav", None, None)
    assert "uv tool install './backend[pyannote]'" in str(e.value)
    assert "--extras" not in str(e.value) and "pip install" not in str(e.value)


@pytest.mark.parametrize("flag", ["--min-speakers", "--max-speakers"])
def test_cli_reprocess_refuses_speaker_hints_with_sortformer(capsys, tmp_path, monkeypatch, flag):
    sid, directory = make_session(tmp_path / "data")

    def must_not_run(*args, **kwargs):
        raise AssertionError("the reprocess started")

    monkeypatch.setattr(reprocess, "reprocess_session", must_not_run)
    code = cli.main(["reprocess", sid, "--nemo-speech", "/bin/true", flag, "3"])
    out, err = capsys.readouterr()
    assert code == cli.EXIT_USAGE and flag in err and "pyannote" in err


def test_reprocess_session_skips_an_empty_audio_file(tmp_path, monkeypatch, caplog):
    sid, directory = make_session(tmp_path, files=("a", "b"))
    (directory / "audio" / "a.pcm").write_bytes(b"")
    seen = []
    words = [{"word": "ok", "start": 0.0, "end": 0.3, "speaker": 1}]

    def transcribe(binary, wav, asr_model, diar_model, out_json):
        seen.append(wav)
        return {"words": words}

    monkeypatch.setattr(reprocess, "transcribe_file", transcribe)
    with caplog.at_level("WARNING", logger="rabblefish.reprocess"):
        summary = reprocess_session(
            directory, binary="b", asr_model="m", diar_model="d", languages=LANGS
        )
    assert len(seen) == 1 and summary["files"] == 1 and summary["segments"] == 1
    assert "a.pcm" in caplog.text


def test_reprocess_session_refuses_a_session_with_only_empty_audio(tmp_path):
    sid, directory = make_session(tmp_path)
    (directory / "audio" / "mic-001.pcm").write_bytes(b"")
    with pytest.raises(ReprocessError, match="empty"):
        reprocess_session(directory, binary="b", asr_model="m", diar_model="d", languages=LANGS)


@pytest.mark.parametrize("target", [LOG_NAME, "audio/mic-001.pcm"])
def test_reprocess_session_never_writes_over_the_session_inputs(tmp_path, monkeypatch, target):
    sid, directory = make_session(tmp_path)
    before = (directory / target).read_bytes()

    def must_not_run(*args, **kwargs):
        raise AssertionError("the transcription started")

    monkeypatch.setattr(reprocess, "transcribe_file", must_not_run)
    with pytest.raises(ReprocessError, match="input of the reprocess"):
        reprocess_session(
            directory,
            binary="b",
            asr_model="m",
            diar_model="d",
            languages=LANGS,
            output=directory / target,
            overwrite=True,
        )
    assert (directory / target).read_bytes() == before
