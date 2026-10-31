# rabblefish backend

FastAPI app that serves the WebSocket and REST API for the web UI, and the built frontend in production.

```sh
uv run rabblefish serve                      # the app, with the settings below
uv run uvicorn --factory rabblefish.app:create_app --reload   # development, port 8000
uv run pytest
uv run ruff check && uv run ruff format --check
```

The built UI: `RABBLEFISH_STATIC_DIR` if it is set, else `rabblefish/static` in the installed package (the wheel has it, see "Packaging"), else `../frontend/dist` of the checkout. With none of them, only the API is served (in development Vite serves the UI).

## The `rabblefish` command

`rabblefish` is the `[project.scripts]` entry `rabblefish.cli:main`.

| Command | Use |
| --- | --- |
| `rabblefish serve [--host H] [--port P]` | Start the UI and the API. It prints the URL, and a warning when the host is not a loopback address (there is no login). |
| `rabblefish sessions list` | The saved Sessions: ID, date, length, state, Speakers. `started` is a log with no stop line: the Session runs now, or the app ended without a stop (the next `rabblefish serve` marks it `interrupted`). |
| `rabblefish export SESSION_ID --format md\|json [-o FILE]` | The export of a saved Session (`rabblefish.export`), to stdout or to FILE. |
| `rabblefish config` | The effective settings, and where each value comes from. |
| `rabblefish --version`, `rabblefish --help` | |

`sessions list` and `export` only read the logs. A bad config file or a bad environment value stops each command with `rabblefish: bad setting: ...` and exit status 2.

## Packaging

`hatch_build.py` is a build hook of the wheel. It runs `pnpm install --frozen-lockfile` and `pnpm -C frontend build` at the repository root, and adds `frontend/dist` to the wheel as `rabblefish/static`. So `uv tool install ./backend` (from the repository root) needs Node.js and pnpm. To use a `frontend/dist` that is already built, set `RABBLEFISH_SKIP_UI_BUILD=1`. An editable install (`uv sync`, `uv run`) does not run the hook.

Build the wheel from a checkout of the whole repository: an sdist of `backend/` alone does not contain the UI.

## Sources and capture

- `rabblefish.sources`: the PipeWire Sources (microphones and sink monitors) from `pw-dump --monitor`.
- `rabblefish.capture`: one `pw-record` per Source, 16 kHz mono PCM16, timed on the monotonic clock.

```sh
uv run python -m rabblefish.capture list
uv run python -m rabblefish.capture record <key> <key> --seconds 10 --out captures
```

`record` writes one WAV per Source and reports the audio length, gaps and the largest lag behind the wall clock.

## Transcription

A Session opens one capture and one NeMo-Speech.cpp realtime connection for each selected Source (see ADR-0001 and the contract in issue #11).

- `rabblefish.nemo`: the thin realtime client (`session.update`, 80 ms PCM16 frames, `.delta` and `.completed`), and the endpoint check.
- `rabblefish.transcript`: the mapping from NeMo events to our `partial`, `segment` and `speaker` events, the language of each Segment, and the Session state for the `/ws` snapshot.
- `rabblefish.pipeline`: the Session, and for each Source the capture loop and the connection loop (automatic reconnect).
- `rabblefish.translation`: the translation of Segments (see [Translation](#translation)).
- `rabblefish.store` and `rabblefish.audio`: the saved Sessions and their audio (see [Saved sessions](#saved-sessions)).
- `rabblefish.export`: the Markdown and JSON export of a Session (see [Export](#export)).

### The ASR endpoint

The backend does not start the endpoint. Start NeMo-Speech.cpp next to the app (or on another machine) with these flags. The app cannot read them, so it cannot check them:

```sh
nemo-speech serve --port 8080 \
  --asr-model nemotron-3.5-asr-streaming-0.6b.q8_0.gguf \
  --diar-model Nemotron-3-Diarization.q8_0.gguf \
  --asr.endpointing.enable=true \
  --asr.batching.enabled=false \
  --asr.streaming.rnnt_right_context=6 \
  --threads 4
```

- `--asr.endpointing.enable=true`: the endpoint finalizes the text at each pause (the session sets `endpointing_ms: 800`).
- `--asr.batching.enabled=false`: with batching, two or more concurrent realtime sessions give no output or abort (NVIDIA/NeMo-Speech.cpp#89).
- `--asr.streaming.rnnt_right_context=6`: the endpoint decodes in chunks of 560 ms, not the 160 ms of the server default. See `docs/endpoint.md`.
- `--threads N`: N must be at least the number of selected Sources, because each Source holds one connection for the whole Session.

At the start of each connection, the backend checks `GET /ready` and `GET /v1/models`. It needs a `transcription` model, and also a `diarization` model for a Source in "diarize" mode. A failure is sent as `source_status` `error`, and the backend tries again.

### Settings

`rabblefish.settings` reads all settings. The file is `$XDG_CONFIG_HOME/rabblefish/config.toml` (by default `~/.config/rabblefish/config.toml`); the app works with no file. Precedence, from high to low: the `--host` and `--port` flags of `rabblefish serve`, the environment variable, the file, the default. An empty environment variable counts as not set. A file that is not valid TOML, an unknown key or a bad value is an error (`rabblefish config` shows the effective values and their sources).

| Key in `config.toml` | Environment variable | Default | Use |
| --- | --- | --- | --- |
| `asr_endpoint_url` | `RABBLEFISH_ASR_ENDPOINT_URL` | `"ws://127.0.0.1:8080"` | Base URL of the NeMo-Speech.cpp endpoint (`ws://` or `wss://`) |
| `translation_endpoint_url` | `RABBLEFISH_TRANSLATION_ENDPOINT_URL` | the `http://` form of `asr_endpoint_url` | Base URL of the translation endpoint (`http://` or `https://`) |
| `detect_languages` | `RABBLEFISH_LANGUAGES` (comma-separated) | `["en", "fr"]` | ISO 639-1 codes for the language identifier (lingua, CPU only) |
| `default_target_language` | `RABBLEFISH_DEFAULT_TARGET_LANGUAGE` | `"en"` | The first value of the "Translate to" selector of the UI |
| `data_dir` | `RABBLEFISH_DATA_DIR` | `$XDG_DATA_HOME/rabblefish` (`~/.local/share/...`) | The directory of the saved Sessions (`sessions/` in it). `~` is expanded. |
| `host` | `RABBLEFISH_HOST` | `"127.0.0.1"` | The address of the UI. Another address gives LAN access, with **no login**. |
| `port` | `RABBLEFISH_PORT` | `8000` | The port of the UI |
| `silent_after_s` | `RABBLEFISH_SILENT_AFTER_S` | `30` | Seconds of quiet audio before the `silent` warning of a Source |
| `silence_dbfs` | `RABBLEFISH_SILENCE_DBFS` | `-60` | A 100 ms chunk with a lower peak level (dBFS) is quiet |

`pnpm dev` always uses port 8000 for the backend (the Vite proxy expects it); `host` and `port` apply to `rabblefish serve`.

### Endpoint state

`rabblefish serve` checks the endpoint when it starts, but does not wait for the check: the app starts also when the endpoint is not reachable. It checks again at each Session start, and every 30 s while the endpoint is not ready. The check is `GET /ready` and `GET /v1/models` on the ASR endpoint, and `GET /v1/models` on the translation endpoint when it is another server. The log shows each change of state. The UI shows the "Endpoint" chip from the `endpoint_status` event (see `rabblefish.endpoint_status`):

```json
{"type": "endpoint_status", "state": "ready", "asr_url": "http://127.0.0.1:8080", "translation_url": "http://127.0.0.1:8080",
 "capabilities": ["transcription", "diarization", "translation"], "missing": [], "message": null, "checked_at": 1793356650.0}
```

`state` is `checking` (before the first result), `ready` (it can transcribe; `missing` names the capabilities that it does not have), `not_ready` (`/ready` is not true, or no transcription model) or `unreachable`. This event is not a Session event and is not saved.

### API

- `POST /api/session/start` with an optional body `{"target_language": "fr", "save_audio": true}` (defaults `en` and `true`), `POST /api/session/stop`. The `stopped` `session` event has `ended_at` (unix seconds). While a Session runs, `PATCH /api/sources/...` returns 409. An unsupported Target language returns 400.
- `PATCH /api/speakers/{id}` `{display_name}`. Encode the `#` of the ID as `%23`.
- `POST /api/speakers/merge` `{from_speaker_id, into_speaker_id}`.
- `GET /api/config`: `default_target_language`, `detect_languages`, the endpoint URLs and the last `endpoint_status`.
- `/ws`: `hello` (with `version` and `default_target_language`), `sources`, the last `endpoint_status`, then the snapshot of the current or last Session (`session`, `source_status`, `speaker`, `segment`, `merge`, `translation`, `translation_status`, `audio_file`, `partial`), then the live events. The `session` event has `target_lang`.

A `source_status` `live` event after a reconnect has `gap: {start, end}`, in seconds since the Session start. The audio of the gap is lost.

Each `sources` entry has `muted` (true when PipeWire reports the node as muted; see below).

### Silent or muted Source

The backend measures the peak level of each 100 ms chunk of each Source, also while the NeMo connection is down. A chunk with a peak below `silence_dbfs` (default -60 dBFS) is quiet. Each `source_status` event has `warning`:

- `"muted"`: the chunk is quiet and PipeWire reports the node as muted. It shows at once. For a microphone, this is the `mute` of the node (`pactl set-source-mute`). For a sink monitor, this is the `mute` of the sink (`pactl set-sink-mute`) when the sink has `monitor.channel-volumes` on (the usual setting: the monitor follows the sink volume, as in PulseAudio), or its `monitorMute`. The backend reads it from `info.params.Props` of the node in `pw-dump --monitor`. A mute that only the hardware or the application knows (for example the mute button of a call app) is not seen; it gives `"silent"`.
- `"silent"`: all chunks were quiet for `silent_after_s` seconds (default 30) of audio time.
- `null`: the Source has sound. The first chunk with sound clears the warning.

When the warning changes, the backend sends a `source_status` event with the current `state` and `message` and the new `warning` (without `gap`). `state` does not change. The event is saved in the event log like all `source_status` events.

```json
{"type": "source_status", "source_key": "monitor:ltt_test", "state": "live", "message": null, "warning": "muted"}
```

### Integration check

With the endpoint running, and a temporary null sink as the speech Source:

```sh
pactl load-module module-null-sink sink_name=ltt_test   # prints the module ID
pactl set-sink-mute ltt_test 0                          # a new null sink can start muted
RABBLEFISH_ASR_ENDPOINT_URL=ws://127.0.0.1:8080 uv run rabblefish serve
# select monitor:ltt_test (diarize), POST /api/session/start, then:
pw-play --target ltt_test speech.wav
pactl unload-module <module ID>
```

A muted sink gives silence on its monitor, so its Source gives no text. The Source then shows the `muted` warning.

## Saved sessions

Each Session is saved as it runs (decided in issue #29). Recording again always starts a new Session.

```
$RABBLEFISH_DATA_DIR/sessions/<YYYY-MM-DDTHH-MM-SS>/   # local time of the start; "-2" if two start in one second
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

`rabblefish.export` makes a Markdown or a JSON file of one Session from its event log (decided in issue #30). A past Session is the replay of its log. The live Session is a snapshot of the moment, marked "in progress", without Partial text. Merges (also chains of Merges) and display names are applied in both formats.

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
- The JSON Schema of the document is `src/rabblefish/export.schema.json`. The tests validate the exports against it.
- The golden files of the tests are in `tests/fixtures/export/`. To write them again after an intended change: `RABBLEFISH_UPDATE_GOLDEN=1 uv run pytest tests/test_export.py`.

## Translation

The backend translates each Segment once, after the Segment is finalized and its language is detected (decided in issue #12). It uses `POST /v1/translations` of NeMo-Speech.cpp with Riva-Translate-4B-Instruct-v2. Each Segment is translated alone, with no context. Partial text is not translated.

- **Target language:** one for each Session, `en` by default. The UI sends it at start. Riva-Translate has these languages: `en`, and `cs da de el es-ES es-US fi fr hu it lt lv nl no pl pt-PT pt-BR ro ru sk sv zh-CN zh-TW ja hi ko et sl bg uk hr ar vi tr id th`.
- **Source language:** the language of the Segment. If the Segment has no language (for example, it has fewer than 3 words), the backend uses the last language of the same Speaker, then the last language of the same Source. If there is no language, the Segment is not translated.
- **Skips:** the backend does not translate a Segment in the Target language. Each Riva-Translate pair has English on one side, so the backend does not translate a pair with no English side (for example `de` to `fr`).
- **No wait:** one background task sends one request at a time. The transcription does not wait for it. At stop, the backend waits up to 10 s for the queued Segments.
- **Events:** `translation` {segment_id, text, target_lang}, and `translation_status` {state: `ready` | `error`, target_lang, message}. At the start of a Session, the backend checks `GET /v1/models` for a `translation` model and sends `translation_status`. After an error, it sends `translation_status` `error` and continues the Session. It checks the endpoint again at the next Segment. It sends `translation_status` only when the state or the message changes.

### Make the Riva-Translate model

Convert the model to GGUF with `convert_model.py` from a NeMo-Speech.cpp v0.3.0 source checkout. The download is about 8 GB, and the Q8_0 file is about 4 GB:

```sh
git clone --branch v0.3.0 https://github.com/NVIDIA/NeMo-Speech.cpp
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
  --asr.streaming.rnnt_right_context=6 \
  --threads 4
```

The server loads the NMT model at start. Then `GET /v1/models` shows a model with `capability: "translation"`.

Speed (issue #25, Vulkan, on the laptop): with one Source, one translation takes about 0.7 s (p50). With more Sources on the same server, the ASR or the translation becomes slower. To move the translation to another machine, start a second server there with only `--nmt.model.path`, and set `RABBLEFISH_TRANSLATION_ENDPOINT_URL=http://<host>:<port>`.
