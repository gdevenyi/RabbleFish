"""Batch re-transcription of a saved Session (`rabblefish reprocess`).

The saved audio (`Save audio`, see `rabblefish.audio`) is transcribed again offline, with
speaker labels, and written to `<session dir>/reprocessed.jsonl` as `speaker` and
`segment` events in the same schema as the live log. The live log is not touched: the
IDs of the reprocessed Speakers and Segments carry an `r` (`<source>#r1`,
`<source>/r1`), so both versions can coexist and the export or the UI can pick one.

The transcription runs the `nemo-speech` binary of the endpoint installation (the same
models as the live endpoint, offline) with its Sortformer diarizer, which caps at 8
speakers per file. `--diarizer pyannote` instead runs the offline pyannote
speaker-diarization-community-1 pipeline (optional extra `pyannote`, gated model), which
has no speaker cap.

The audio of one Source is a sequence of `.pcm` files, one per contiguous capture run
(a gap starts a new file). Each file is transcribed on its own, so diarizer labels are
per file, like the per-connection speaker labels of the live pipeline; the merge action
of the UI joins speakers across files.
"""

import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
import wave
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from rabblefish.capture import SAMPLE_RATE
from rabblefish.store import LOG_NAME, read_events
from rabblefish.transcript import MIN_LANG_WORDS, LanguageIdentifier

log = logging.getLogger(__name__)

REPROCESSED_NAME = "reprocessed.jsonl"
# Split a Segment at a pause longer than this, like the live endpointing does
# (endpointing_ms: 800).
SPLIT_PAUSE_S = 0.8
PYANNOTE_MODEL = "pyannote/speaker-diarization-community-1"
# A run that produced no output would leave the old file in place without this marker.
EMPTY = object()
HF_MISSING_MODEL_HINT = (
    "the model is gated: accept it on huggingface.co/pyannote/speaker-diarization-community-1"
    " and run `hf auth login`"
)


class ReprocessError(RuntimeError):
    """The reprocess run cannot start, or the transcription failed."""


@dataclass
class SourceAudio:
    """One saved audio file: a contiguous run of one Source (see `rabblefish.audio`)."""

    source_key: str
    pcm: Path
    start: float  # Session time of the first sample
    sample_rate: int


@dataclass
class SourceCounters:
    """The IDs given so far for one Source. A Source can have many files, and its IDs are
    unique across them."""

    speakers: int = 0
    segments: int = 0


def load_audio_files(session_dir: Path) -> list[SourceAudio]:
    """The saved audio files of the Session, in log order."""
    out = []
    for e in read_events(session_dir / LOG_NAME):
        if e.get("type") != "audio_file":
            continue
        fmt = e.get("format")
        if fmt is not None and fmt != "s16le":
            raise ReprocessError(f"{e.get('path')}: unsupported audio format {fmt!r}")
        pcm = session_dir / e.get("path", "")
        if not pcm.is_file():
            raise ReprocessError(f"{pcm}: the saved audio file is missing")
        rate = e.get("sample_rate") or SAMPLE_RATE
        out.append(SourceAudio(e.get("source_key", ""), pcm, float(e.get("start") or 0.0), rate))
    if not out:
        raise ReprocessError("the Session has no saved audio (it was recorded without Save audio)")
    return out


def pcm_to_wav(pcm: Path, wav: Path, sample_rate: int) -> None:
    """Wrap raw s16le mono PCM in a WAV header, streaming (the files can be ~100 MB)."""
    with wave.open(str(wav), "wb") as wf, pcm.open("rb") as raw:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        while chunk := raw.read(1 << 20):
            wf.writeframes(chunk)


def resolve_binary(explicit: str | None, data_dir: Path) -> str:
    """The `nemo-speech` binary: the flag, the endpoint installation, or the PATH."""
    if explicit:
        return explicit
    installed = data_dir / "endpoint" / "bin" / "nemo-speech"
    if installed.is_file():
        return str(installed)
    on_path = shutil.which("nemo-speech")
    if on_path:
        return on_path
    raise ReprocessError(
        "cannot find the nemo-speech binary: install the endpoint"
        " (scripts/setup-endpoint.sh) or pass --nemo-speech PATH"
    )


def resolve_model(explicit: str | None, data_dir: Path, filename: str, hf_id: str) -> str:
    """The model file of the endpoint installation, or the Hugging Face ID."""
    if explicit:
        return explicit
    installed = data_dir / "endpoint" / "models" / filename
    if installed.is_file():
        return str(installed)
    return hf_id


def transcribe_file(
    binary: str,
    wav: Path,
    asr_model: str,
    diar_model: str | None,
    out_json: Path,
) -> dict:
    """One offline transcription with the endpoint binary; diarization when `diar_model`."""
    cmd = [binary, "transcribe", str(wav), "--model", asr_model, "-f", "json", "-o", str(out_json)]
    if diar_model is not None:
        cmd += ["--diarize", "--diar-model", diar_model]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True)
    except OSError as e:
        raise ReprocessError(f"{binary}: {e}") from e
    if r.returncode != 0:
        lines = (r.stderr or r.stdout).strip().splitlines()
        # The `[nemo-speech]` lines give the state of the run; the others give the cause.
        causes = [line for line in lines if not line.startswith("[nemo-speech]")] or lines
        detail = "; ".join(causes[-3:]) or "no output"
        raise ReprocessError(f"{binary} transcribe failed: {detail}")
    try:
        return json.loads(out_json.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ReprocessError(f"{out_json}: no usable transcription output ({e})") from e


def pyannote_turns(
    wav: Path, min_speakers: int | None, max_speakers: int | None
) -> list[tuple[float, float, object]]:
    """Speaker turns `(start, end, label)` from the offline pyannote pipeline."""
    try:
        import torch
        from pyannote.audio import Pipeline
    except ImportError as e:
        raise ReprocessError(
            "pyannote is not installed: install the optional extra"
            " (`uv tool install './backend[pyannote]'`)"
        ) from e
    try:
        pipe = Pipeline.from_pretrained(PYANNOTE_MODEL)
    except Exception as e:
        raise ReprocessError(f"{PYANNOTE_MODEL}: {e} ({HF_MISSING_MODEL_HINT})") from e
    pipe.to(torch.device("cuda" if torch.cuda.is_available() else "cpu"))
    kwargs: dict[str, int] = {}
    if min_speakers is not None:
        kwargs["min_speakers"] = min_speakers
    if max_speakers is not None:
        kwargs["max_speakers"] = max_speakers
    try:
        out = pipe(str(wav), **kwargs)
    except Exception as e:
        raise ReprocessError(f"{PYANNOTE_MODEL} failed: {e}") from e
    ann = out.speaker_diarization
    if isinstance(ann, dict):  # multi-task output: the diarization is its first entry
        ann = next(iter(ann.values()))
    return [(t.start, t.end, label) for t, _, label in ann.itertracks(yield_label=True)]


def label_words_with_turns(
    words: list[dict], turns: list[tuple[float, float, object]]
) -> list[dict]:
    """Give each word the label of the turn that overlaps it most (words keep their order).

    A word that overlaps no turn gets the label of the nearest turn: the ASR and the
    diarizer do not agree exactly on where speech stops, and such a word is not a new
    person. Without any turn, all words have the label None (one Speaker).
    """
    labeled = []
    for w in words:
        start, end = w.get("start") or 0.0, w.get("end") or 0.0
        best, best_overlap = None, 0.0
        for t_start, t_end, label in turns:
            overlap = min(end, t_end) - max(start, t_start)
            if overlap > best_overlap:
                best, best_overlap = label, overlap
        if best is None and turns:
            best = min(turns, key=lambda t: max(t[0] - end, start - t[1]))[2]
        labeled.append({**w, "speaker": best})
    return labeled


def words_to_events(
    words: list[dict],
    source_key: str,
    file_start: float,
    lang_id: LanguageIdentifier,
    counters: SourceCounters | None = None,
) -> tuple[list[dict], list[dict]]:
    """The `speaker` and `segment` events of one file's words, in the live event schema.

    Times are Session times (`file_start` is the Session time of the file's first
    sample). Consecutive words with the same speaker label form one Segment, split at
    every speaker change and at every pause longer than SPLIT_PAUSE_S, like the live
    pipeline splits at speaker changes and at the endpointing pause. Speaker and
    Segment IDs carry an `r`, so they never collide with the live ones. `counters` holds
    the numbers given so far for the Source, so that the IDs of its next file continue them.
    """
    counters = counters if counters is not None else SourceCounters()
    speakers: dict[object, dict] = {}
    speaker_events: list[dict] = []
    segment_events: list[dict] = []
    run: list[dict] = []
    run_label: object = EMPTY

    def flush() -> None:
        nonlocal run
        if not run:
            return
        if run_label not in speakers:
            counters.speakers += 1
            speaker = {
                "type": "speaker",
                "id": f"{source_key}#r{counters.speakers}",
                "source_key": source_key,
                "label": f"Speaker {counters.speakers}",
                "display_name": None,
            }
            speakers[run_label] = speaker
            speaker_events.append(speaker)
        mapped = [
            {
                "w": w["word"],
                "start": round(file_start + (w.get("start") or 0.0), 3),
                "end": round(file_start + (w.get("end") or 0.0), 3),
            }
            for w in run
        ]
        text = " ".join(m["w"] for m in mapped)
        counters.segments += 1
        segment_events.append(
            {
                "type": "segment",
                "id": f"{source_key}/r{counters.segments}",
                "source_key": source_key,
                "speaker_id": speakers[run_label]["id"],
                "start": mapped[0]["start"],
                "end": mapped[-1]["end"],
                "text": text,
                "words": mapped,
                "lang": lang_id(text) if len(mapped) >= MIN_LANG_WORDS else None,
            }
        )
        run = []

    for w in words:
        if not (w.get("word") or "").strip():
            continue
        label = w.get("speaker")
        if label != run_label:
            flush()
            run_label = label
        elif run and (w.get("start") or 0.0) - (run[-1].get("end") or 0.0) > SPLIT_PAUSE_S:
            flush()
        run.append(w)
    flush()
    return speaker_events, segment_events


def reprocess_session(
    session_dir: Path,
    *,
    binary: str,
    asr_model: str,
    diar_model: str,
    diarizer: str = "sortformer",
    output: Path | None = None,
    overwrite: bool = False,
    languages: tuple[str, ...] = ("en", "fr"),
    min_speakers: int | None = None,
    max_speakers: int | None = None,
    transcribe=None,
    diarize=None,
) -> dict:
    """Re-transcribe every saved audio file; write `reprocessed.jsonl`. Returns the summary.

    `transcribe` and `diarize` default to `transcribe_file` and `pyannote_turns`; tests
    pass their own and so run without the binary, the models or a GPU.
    """
    transcribe = transcribe or transcribe_file
    diarize = diarize or pyannote_turns
    audio = []
    for sa in load_audio_files(session_dir):
        if sa.pcm.stat().st_size == 0:
            log.warning("skipping %s: the file is empty", sa.pcm.name)
        else:
            audio.append(sa)
    if not audio:
        raise ReprocessError("all the saved audio files of the Session are empty")
    output = output or session_dir / REPROCESSED_NAME
    inputs = [session_dir / LOG_NAME, *(sa.pcm for sa in audio)]
    if any(output.resolve() == path.resolve() for path in inputs):
        raise ReprocessError(f"{output} is an input of the reprocess: choose another --output")
    if output.exists() and not overwrite:
        raise ReprocessError(f"{output} exists (pass --overwrite to replace it)")
    # Before the transcription, which can take a long time: do not lose it at the end.
    if not output.parent.is_dir():
        raise ReprocessError(f"{output.parent}: the output directory does not exist")
    if not os.access(output.parent, os.W_OK):
        raise ReprocessError(f"{output.parent}: the output directory is not writable")
    lang_id = LanguageIdentifier(list(languages))
    total_seconds = 0.0
    speaker_events: list[dict] = []
    segment_events: list[dict] = []
    counters: defaultdict[str, SourceCounters] = defaultdict(SourceCounters)
    with tempfile.TemporaryDirectory(dir=session_dir, prefix=".reprocess-") as work:
        work = Path(work)
        for i, sa in enumerate(audio):
            wav = work / f"{i:03d}.wav"
            pcm_to_wav(sa.pcm, wav, sa.sample_rate)
            seconds = sa.pcm.stat().st_size / 2 / sa.sample_rate  # s16le: 2 bytes per sample
            total_seconds += seconds
            log.info("transcribing %s (%.0f s of %s)", sa.pcm.name, seconds, sa.source_key)
            if diarizer == "sortformer":
                result = transcribe(binary, wav, asr_model, diar_model, work / f"{i:03d}.json")
                words = result.get("words") or []
            elif diarizer == "pyannote":
                result = transcribe(binary, wav, asr_model, None, work / f"{i:03d}.json")
                turns = diarize(wav, min_speakers, max_speakers)
                words = label_words_with_turns(result.get("words") or [], turns)
            else:
                raise ReprocessError(f"unknown diarizer {diarizer!r} (sortformer, pyannote)")
            spk, seg = words_to_events(
                words, sa.source_key, sa.start, lang_id, counters[sa.source_key]
            )
            speaker_events += spk
            segment_events += seg
    tmp = output.with_name(output.name + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            header = {
                "type": "reprocess",
                "session": session_dir.name,
                "created_at": round(time.time(), 3),
                "asr_model": asr_model,
                "diarizer": diarizer,
                "files": len(audio),
            }
            f.write(json.dumps(header, ensure_ascii=False, separators=(",", ":")) + "\n")
            for event in [*speaker_events, *segment_events]:
                f.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
            f.write(
                json.dumps(
                    {
                        "type": "reprocess",
                        "state": "finished",
                        "segments": len(segment_events),
                        "speakers": len({s["id"] for s in speaker_events}),
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                + "\n"
            )
        os.replace(tmp, output)
    except OSError as e:
        raise ReprocessError(f"{output}: cannot write the output: {e}") from e
    finally:
        tmp.unlink(missing_ok=True)
    return {
        "output": output,
        "files": len(audio),
        "seconds": round(total_seconds, 1),
        "segments": len(segment_events),
        "speakers": len({s["id"] for s in speaker_events}),
    }
