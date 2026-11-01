# Reprocessing a saved Session

`rabblefish reprocess SESSION_ID` re-transcribes the audio that a Session saved with
**Save audio** (`docs/endpoint.md`, issue #29). It runs the ASR and the diarization
offline, with full context, and writes the result to
`<session dir>/reprocessed.jsonl`. The live log `events.jsonl` is never touched.

Offline transcription recovers what live streaming truncates or drops: on a saved call
of 43 minutes, the reprocess produced the same number of words as the live pass but with
whole sentences where the live segments were cut, and the offline diarization of a
recording with more than eight voices found ten speakers where the live Sortformer cap
of eight had merged them.

```sh
rabblefish sessions list                       # find the ID
rabblefish reprocess 2026-10-30T10-30-10       # writes <session>/reprocessed.jsonl
```

A reprocess runs the `nemo-speech` binary of the endpoint installation, on the machine
that holds the Session directory (not against a remote endpoint). It needs no running
endpoint. On a mid-range GPU it runs at roughly 50× real time; a Session of one hour
takes a few minutes. `--nemo-speech`, `--asr-model` and `--diar-model` override the
binary and the models (the defaults are the files that `scripts/setup-endpoint.sh`
installed; without them, the Hugging Face IDs are used and downloaded on first use).

## The two diarizers

| | `--diarizer sortformer` (default) | `--diarizer pyannote` |
| --- | --- | --- |
| Model | `nvidia/Nemotron-3-Diarization`, already installed | [pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1) |
| Speakers | at most 8 per audio file | no cap |
| Install | nothing (the endpoint has the model) | optional extra: `uv tool install ./backend --extras pyannote` (pulls in PyTorch) |
| Access | none | the model is gated: accept it once on Hugging Face and run `hf auth login` |
| Hints | none | `--min-speakers` / `--max-speakers` |

Both label the words of the new transcription; the reprocess then splits the words into
Segments at every speaker change, like the live pipeline does.

## What the output is

`reprocessed.jsonl` is an event log in the same schema as `events.jsonl`, with three
differences:

- a `reprocess` event first (model, diarizer, file count) and one at the end
  (`state: "finished"`),
- the Speaker and Segment IDs carry an `r` (`<source>#r1`, `<source>/r1`), so they
  never collide with the live ones,
- it is a separate file. `rabblefish export` reads the live log; to build a Transcript
  from the reprocess, apply its events:

```python
from rabblefish.store import read_events
from rabblefish.transcript import Transcript

t = Transcript()
for event in read_events(session_dir / "reprocessed.jsonl"):
    t.apply(event)
```

Renames and speaker merges recorded during the live Session do not carry over: they
refer to live IDs. Speaker labels of a reprocess are per audio file, like the live
labels are per connection; the same two persons in two files get two Speakers, and a
consumer merges them by ID as the UI does.
