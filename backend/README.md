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
- `ltt.translation`: the translation of Segments (see [Translation](#translation)).

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
| `LTT_TRANSLATION_ENDPOINT_URL` | the `http://` form of `LTT_ASR_ENDPOINT_URL` | Base URL of the translation endpoint (`http://` or `https://`) |

### API

- `POST /api/session/start` with an optional body `{"target_language": "fr"}` (default `en`), `POST /api/session/stop`. While a Session runs, `PATCH /api/sources/...` returns 409. An unsupported Target language returns 400.
- `PATCH /api/speakers/{id}` `{display_name}`. Encode the `#` of the ID as `%23`.
- `POST /api/speakers/merge` `{from_speaker_id, into_speaker_id}`.
- `/ws`: `hello`, `sources`, then the snapshot of the current or last Session (`session`, `source_status`, `speaker`, `segment`, `merge`, `translation`, `translation_status`, `partial`), then the live events. The `session` event has `target_lang`.

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

## Translation

The backend translates each Segment once, after the Segment is finalized and its language is detected (decided in issue #12). It uses `POST /v1/translations` of NeMo-Speech.cpp with Riva-Translate-4B-Instruct-v2. Each Segment is translated alone, with no context. Partial text is not translated.

- **Target language:** one for each Session, `en` by default. The UI sends it at start. Riva-Translate has these languages: `en`, and `cs da de el es-ES es-US fi fr hu it lt lv nl no pl pt-PT pt-BR ro ru sk sv zh-CN zh-TW ja hi ko et sl bg uk hr ar vi tr id th`.
- **Source language:** the language of the Segment. If the Segment has no language (for example, it has fewer than 3 words), the backend uses the last language of the same Speaker, then the last language of the same Source. If there is no language, the Segment is not translated.
- **Skips:** the backend does not translate a Segment in the Target language. Each Riva-Translate pair has English on one side, so the backend does not translate a pair with no English side (for example `de` to `fr`).
- **No wait:** one background task sends one request at a time. The transcription does not wait for it. At stop, the backend waits up to 10 s for the queued Segments.
- **Events:** `translation` {segment_id, text, target_lang}, and `translation_status` {state: `ready` | `error`, target_lang, message}. At the start of a Session, the backend checks `GET /v1/models` for a `translation` model and sends `translation_status`. After an error, it sends `translation_status` `error` and continues the Session. It checks the endpoint again at the next Segment. It sends `translation_status` only when the state or the message changes.

### Make the Riva-Translate model

Convert the model to GGUF with `convert_model.py` from a NeMo-Speech.cpp v0.2.0 source checkout. The download is about 8 GB, and the Q8_0 file is about 4 GB:

```sh
git clone --branch v0.2.0 https://github.com/NVIDIA/NeMo-Speech.cpp
cd NeMo-Speech.cpp
pip install -r requirements.txt   # in a Python virtual environment
python convert_model.py nvidia/Riva-Translate-4B-Instruct-v2 \
  --outfile riva-translate-4b-instruct-v2.q8_0.gguf --outtype q8_0
```

### Start the server with translation

Add `--nmt.model.path` to the ASR server command. Then one server does the ASR, the diarization and the translation:

```sh
nemo-speech serve --port 8080 \
  --asr-model nemotron-3.5-asr-streaming-0.6b.q8_0.gguf \
  --diar-model Nemotron-3-Diarization.q8_0.gguf \
  --nmt.model.path riva-translate-4b-instruct-v2.q8_0.gguf \
  --asr.endpointing.enable=true \
  --asr.batching.enabled=false \
  --threads 4
```

The server loads the NMT model at start. Then `GET /v1/models` shows a model with `capability: "translation"`.

Speed (issue #25, Vulkan, on the laptop): with one Source, one translation takes about 0.7 s (p50). With more Sources on the same server, the ASR or the translation becomes slower. To move the translation to another machine, start a second server there with only `--nmt.model.path`, and set `LTT_TRANSLATION_ENDPOINT_URL=http://<host>:<port>`.
