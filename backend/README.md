# ltt backend

FastAPI app that serves the WebSocket and REST API for the web UI, and the built frontend in production.

```sh
uv run uvicorn ltt.app:app --reload   # development, port 8000
uv run pytest
uv run ruff check && uv run ruff format --check
```

`LTT_STATIC_DIR` sets the directory of the built frontend (default: `../frontend/dist`, relative to this directory).

## Sources and capture

- `ltt.sources`: the PipeWire Sources (microphones and sink monitors) from `pw-dump --monitor`.
- `ltt.capture`: one `pw-record` per Source, 16 kHz mono PCM16, timed on the monotonic clock.

```sh
uv run python -m ltt.capture list
uv run python -m ltt.capture record <key> <key> --seconds 10 --out captures
```

`record` writes one WAV per Source and reports the audio length, gaps and the largest lag behind the wall clock.

## Transcription

A Session opens one capture and one NeMo-Speech.cpp realtime connection for each selected Source (see ADR-0001 and the contract in issue #11).

- `ltt.nemo`: the thin realtime client (`session.update`, 80 ms PCM16 frames, `.delta` and `.completed`), and the endpoint check.
- `ltt.transcript`: the mapping from NeMo events to our `partial`, `segment` and `speaker` events, the language of each Segment, and the Session state for the `/ws` snapshot.
- `ltt.pipeline`: the Session, and for each Source the capture loop and the connection loop (automatic reconnect).

### The ASR endpoint

The backend does not start the endpoint. Start NeMo-Speech.cpp next to the app (or on another machine) with these flags. The app cannot read them, so it cannot check them:

```sh
nemo-speech serve --port 8080 \
  --asr-model nemotron-3.5-asr-streaming-0.6b.q8_0.gguf \
  --diar-model Nemotron-3-Diarization.q8_0.gguf \
  --asr.endpointing.enable=true \
  --asr.batching.enabled=false \
  --threads 4
```

- `--asr.endpointing.enable=true`: the endpoint finalizes the text at each pause (the session sets `endpointing_ms: 800`).
- `--asr.batching.enabled=false`: with batching, two or more concurrent realtime sessions give no output or abort (NVIDIA/NeMo-Speech.cpp#89).
- `--threads N`: N must be at least the number of selected Sources, because each Source holds one connection for the whole Session.

At the start of each connection, the backend checks `GET /ready` and `GET /v1/models`. It needs a `transcription` model, and also a `diarization` model for a Source in "diarize" mode. A failure is sent as `source_status` `error`, and the backend tries again.

### Settings

| Environment variable | Default | Use |
| --- | --- | --- |
| `LTT_ASR_ENDPOINT_URL` | `ws://127.0.0.1:8080` | Base URL of the NeMo-Speech.cpp endpoint (`ws://` or `wss://`) |
| `LTT_LANGUAGES` | `en,fr` | ISO 639-1 codes for the language identifier (lingua, CPU only) |

### API

- `POST /api/session/start`, `POST /api/session/stop`. While a Session runs, `PATCH /api/sources/...` returns 409.
- `PATCH /api/speakers/{id}` `{display_name}`. Encode the `#` of the ID as `%23`.
- `POST /api/speakers/merge` `{from_speaker_id, into_speaker_id}`.
- `/ws`: `hello`, `sources`, then the snapshot of the current or last Session (`session`, `source_status`, `speaker`, `segment`, `merge`, `partial`), then the live events.

A `source_status` `live` event after a reconnect has `gap: {start, end}`, in seconds since the Session start. The audio of the gap is lost.

### Integration check

With the endpoint running, and a temporary null sink as the speech Source:

```sh
pactl load-module module-null-sink sink_name=ltt_test   # prints the module ID
pactl set-sink-mute ltt_test 0                          # a new null sink can start muted
LTT_ASR_ENDPOINT_URL=ws://127.0.0.1:8080 uv run uvicorn ltt.app:app
# select monitor:ltt_test (diarize), POST /api/session/start, then:
pw-play --target ltt_test speech.wav
pactl unload-module <module ID>
```

A muted sink gives silence on its monitor, so its Source gives no text.
