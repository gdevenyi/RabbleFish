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
- `ltt.store` and `ltt.audio`: the saved Sessions and their audio (see [Saved sessions](#saved-sessions)).
- `ltt.export`: the Markdown and JSON export of a Session (see [Export](#export)).

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
| `LTT_DATA_DIR` | `$XDG_DATA_HOME/live-transcribe-translate` (`~/.local/share/...`) | The directory of the saved Sessions (`sessions/` in it) |

### API

- `POST /api/session/start` with an optional body `{"target_language": "fr", "save_audio": true}` (defaults `en` and `true`), `POST /api/session/stop`. The `stopped` `session` event has `ended_at` (unix seconds). While a Session runs, `PATCH /api/sources/...` returns 409. An unsupported Target language returns 400.
- `PATCH /api/speakers/{id}` `{display_name}`. Encode the `#` of the ID as `%23`.
- `POST /api/speakers/merge` `{from_speaker_id, into_speaker_id}`.
- `/ws`: `hello`, `sources`, then the snapshot of the current or last Session (`session`, `source_status`, `speaker`, `segment`, `merge`, `translation`, `translation_status`, `audio_file`, `partial`), then the live events. The `session` event has `target_lang`.

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

## Saved sessions

Each Session is saved as it runs (decided in issue #29). Recording again always starts a new Session.

```
$LTT_DATA_DIR/sessions/<YYYY-MM-DDTHH-MM-SS>/   # local time of the start; "-2" if two start in one second
  events.jsonl                                 # the event log
  audio/<source key>-001.pcm                   # the saved audio, one file per Source and capture run
```

- **Event log:** one JSON line for each event, exactly as on `/ws`. Saved: `session`, `speaker` (also each rename), `segment`, `translation`, `translation_status`, `merge`, `source_status`, `audio_file`. Not saved: `partial`, `heartbeat`, `hello`, `sources`.
- **Durability:** each event is written and flushed to the kernel when it happens, so a crash of the app loses nothing. `fsync` runs at most every 2 s (also every 2 s in the background, and at stop), so a power failure loses at most about 2 s.
- **The last Session:** its log stays open after the stop, so a rename or a merge (`PATCH /api/speakers/...`, `POST /api/speakers/merge`) is saved too, until the next start.
- **Interrupted session:** at start-up, the backend closes each log that has no `session` `stopped` line with this line, and lists the Session as a past Session. It is never continued.

  ```json
  {"type": "session", "state": "interrupted", "started_at": 1761830000.0, "target_lang": "en", "ended_at": 1761830421.5}
  ```

  `ended_at` is `started_at` plus the last known Session time: the end of the last Segment, gap or audio file.
- **Audio:** with "Save audio" on (the default), the backend saves all captured audio of each Source as raw PCM16 little-endian, 16 kHz mono (about 115 MB per hour per Source). It saves the audio also while the NeMo connection is down, so a gap can be transcribed again later. A new file starts after each break in the capture (a capture restart, or lost audio that moved the capture's time anchor). Each file has an `audio_file` event {source_key, path (relative to the Session directory), start (Session time of the first sample), sample_rate, format: `s16le`}. To listen to a file: `play -t raw -r 16000 -e signed -b 16 -c 1 file.pcm`.
- **Retention:** nothing is deleted automatically.

### Past sessions API

The running Session is not a past Session: these return 409 for it, and the list leaves it out. An unknown ID returns 404.

- `GET /api/sessions`: newest first, each {id, started_at, ended_at, length (s), state (`stopped` or `interrupted`), interrupted, target_lang, speakers [{id, label, display_name}] (merged Speakers left out), segments, audio_files}.
- `GET /api/sessions/{id}`: the same summary and `events`, the replay of the log through the code that builds the `/ws` snapshot. The UI gives these events to its reducer. It is read-only: no new Segments.
- `PATCH /api/sessions/{id}/speakers/{speaker_id}` `{display_name}` and `POST /api/sessions/{id}/speakers/merge` `{from_speaker_id, into_speaker_id}`: append the `speaker` or `merge` event to the Session's log and return it. Encode the `#` as `%23`. For the last Session, the event also goes to `/ws`.
- `DELETE /api/sessions/{id}`: delete the log and the audio (204). If it is the last Session, the backend clears its `/ws` snapshot and sends `hello` again on `/ws`, so each UI clears its state.

## Export

`ltt.export` makes a Markdown or a JSON file of one Session from its event log (decided in issue #30). A past Session is the replay of its log. The live Session is a snapshot of the moment, marked "in progress", without Partial text. Merges (also chains of Merges) and display names are applied in both formats.

- `GET /api/sessions/{id}/export?format=md|json` (default `md`): a saved Session. The running Session is exported too. An unknown ID returns 404, another format 422.
- `GET /api/session/export?format=md|json`: the current or last Session, as on `/ws`. 404 before the first Session, and after a restart of the backend until the next Session starts (the last Session is then a past Session).
- The response is a download: `Content-Disposition: attachment; filename="<session id>.md"` (or `.json`).
- The UI has an Export control (Markdown, JSON) in the bar for the live or last Session, and in the banner of an open past Session.

The rules are the same as in the Timeline of the UI:

- **Language switch:** a Segment starts a switch when its language is not the last language of the same Speaker (after Merges). A Segment with no language does not start or end a switch.
- **Silence fold:** a silence of all Speakers longer than 20 s, also before the first Segment. There is no fold after the last Segment.
- **Times:** `mm:ss`, `h:mm:ss` after one hour. Lengths: `45 s`, `2 min 05 s`, `1 h 02 min 05 s`.

### Markdown

```markdown
# Session 2026-10-30T10-37-30

- **Date:** 2026-10-30
- **Start:** 10:37:30 (UTC+00:00)
- **Length:** 2 min 18 s
- **State:** interrupted (the app ended without a stop)
- **Sources:** mic:alsa_input.usb-desk, monitor:alsa_output.pci-speakers
- **Target language:** en
- **Speakers:** Gabriel (Desk microphone), Alice (Speaker 1), Bertrand (Speaker 2; merged: Speaker 3)

**[00:04] Bertrand:** Bonjour, je suis en retard, désolé.\
*Hello, I'm late, sorry.*

**[00:10] Alice:** [fr] Alors, on commence la réunion maintenant.\
*So, we start the meeting now.*

*— 1 min 32 s silence —*

**[02:08] Bertrand:** [en] Sorry, my connection dropped out.
```

- The header has the date and the start time in the local time zone of the backend, the length, the state (only "in progress" or "interrupted"), the Source keys, the Target language and the Speakers. A Speaker shows its display name, else its label; the label and the merged Speakers follow in parentheses.
- One paragraph for each Segment, by start time. `[fr]` marks a Language switch. The Translation is in italics on the next line (a `\` at the end of a line is a line break in CommonMark).
- The text is not escaped: the Markdown characters in the text stay as they are.

### JSON

```json
{
  "version": 1,
  "session": {"id": "...", "started_at": "2026-10-30T10:37:30+00:00", "duration_s": 3703.5,
              "sources": ["mic:...", "monitor:..."], "target_language": "en",
              "interrupted": true, "in_progress": false},
  "speakers": [{"id": "monitor:...#3", "label": "Speaker 3", "display_name": null,
                "source_key": "monitor:...", "merged_into": "monitor:...#2"}],
  "segments": [{"id": "monitor:.../5", "start": 128.0, "end": 131.5,
                "speaker_id": "monitor:...#2", "original_speaker_id": "monitor:...#3",
                "source_key": "monitor:...", "text": "...", "lang": "en",
                "translation": null, "words": [{"w": "Sorry,", "start": 128.0, "end": 128.56}]}],
  "audio_files": [{"source_key": "monitor:...", "path": "audio/monitor_...-002.pcm",
                   "start": 100.0, "sample_rate": 16000, "format": "s16le"}]
}
```

- All times are seconds since the Session started. `started_at` is ISO 8601 with the offset of the local time zone. `duration_s` of the live Session is the time up to the export.
- `speakers` has all Speakers, also the merged ones (`merged_into` is the Speaker that now has their Segments; else `null`).
- `segments` are sorted by start. `speaker_id` is the Speaker after Merges; `original_speaker_id` is there only for a merged Segment. `translation` is `null` when the Segment has no Translation.
- `audio_files[].path` is relative to the Session directory (raw PCM16, see [Saved sessions](#saved-sessions)).
- The JSON Schema of the document is `src/ltt/export.schema.json`. The tests validate the exports against it.
- The golden files of the tests are in `tests/fixtures/export/`. To write them again after an intended change: `LTT_UPDATE_GOLDEN=1 uv run pytest tests/test_export.py`.

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
