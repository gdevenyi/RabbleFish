# live-transcribe-translate

Live transcription of the audio on a Linux (PipeWire) desktop, with one timeline column for each speaker and optional translation. Models run behind configurable endpoints, on this machine or on a remote one (see `docs/adr/`).

![The timeline during a live Session: one column per Speaker, Partial text below the Live edge, French Segments with English Translations](docs/media/demo.gif)

A real Session, sped up 3×: 60 s of an English meeting (AMI corpus) followed by 28 s of French read speech (Multilingual LibriSpeech), played into a PipeWire sink and captured from its monitor. The local endpoint (NeMo-Speech.cpp with Nemotron 3.5 ASR Streaming, Nemotron 3 Diarization and Riva-Translate-4B on the laptop's Intel Arc iGPU) finds five Speakers, shows Partial text before a Speaker is known, marks the switch to French and adds English Translations. Midway, "Speaker 1" is renamed "Alice".

The audio is CC BY 4.0; see `NOTICE`. The plan and every design decision are in the [wayfinder map](https://github.com/gdevenyi/live-transcribe-translate/issues/1).

## Install and run

Needs `uv`, Node.js and `pnpm` (the install builds the UI), and PipeWire (`pw-dump`, `pw-record`). From the root of a checkout:

```sh
uv tool install ./backend    # puts the `ltt` command in ~/.local/bin
ltt serve                    # open http://127.0.0.1:8000
```

`uv tool install --force ./backend` installs a new version. The install runs `pnpm install` and `pnpm -C frontend build`, and puts the built UI into the Python package; to use a `frontend/dist` that you built before, set `LTT_SKIP_UI_BUILD=1`.

Other commands:

```sh
ltt sessions list                              # the saved Sessions: ID, date, length, state, Speakers
ltt export 2026-10-30T10-37-30 --format md     # Markdown (or --format json) to stdout; -o FILE to write a file
ltt config                                     # the effective settings and where each comes from
ltt --help
```

`ltt serve` starts also when the endpoint is not ready. The "Endpoint" chip in the UI shows its state, and the app checks it again every 30 s and at each Session start.

### Settings

The app works with no settings. To change them, write `~/.config/live-transcribe-translate/config.toml` (or `$XDG_CONFIG_HOME/...`):

```toml
asr_endpoint_url = "ws://127.0.0.1:8080"         # the NeMo-Speech.cpp endpoint
# translation_endpoint_url = "http://127.0.0.1:8080"   # default: the same server
detect_languages = ["en", "fr"]
default_target_language = "en"                   # the first value of "Translate to"
# data_dir = "~/.local/share/live-transcribe-translate"
host = "127.0.0.1"
port = 8000
```

Each key has an `LTT_*` environment variable, which overrides the file; `ltt serve --host/--port` override both. See the table in [`backend/README.md`](backend/README.md#settings). The choices for one Session (Sources, modes, Target language, "Save audio") stay in the UI.

**The app has no login.** With the default `host = "127.0.0.1"`, only this machine can open it. `host = "0.0.0.0"` gives access from the LAN to all persons who can reach the port: they can see the transcripts and start a Session. Use it only on a network that you trust; `ltt serve` shows a warning.

To start `ltt serve` with the desktop session, see the systemd user units in [`docs/endpoint.md`](docs/endpoint.md#systemd-user-units).

## Development

```sh
pnpm install
pnpm dev      # backend on :8000 and Vite on http://127.0.0.1:5173
pnpm test     # backend tests, frontend type check and frontend unit tests (vitest)
pnpm lint     # ruff
pnpm build    # build the frontend into frontend/dist
pnpm start    # `ltt serve` from the checkout, serving frontend/dist
```

Demo mode (development only): open http://127.0.0.1:5173/?demo to replay a recorded Session in the Timeline without the backend pipeline. `?demo&speed=4` plays it faster, and `?demo&history=0` starts it at the beginning. The production build does not contain the demo.

## Endpoint

The app needs a NeMo-Speech.cpp endpoint for transcription, diarization and translation. Set it up on this machine (or on a GPU machine on your network):

```sh
scripts/setup-endpoint.sh --backend vulkan   # or cuda (compute capability 7.5+) or cpu
```

The script downloads the server and the models (and converts the translation model) into `~/.local/share/live-transcribe-translate/endpoint`, and prints the `nemo-speech serve` command. It needs about 5.3 GB of disk, and about 11 GB more during the conversion. Run it again at any time: it skips the work that is done. For remote use, the required server flags and the systemd user units, see [`docs/endpoint.md`](docs/endpoint.md).

## Layout

- `backend/`: FastAPI app and the `ltt` command (`ltt` Python package, managed with `uv`).
- `frontend/`: React, Vite and TypeScript UI.
- `scripts/`: endpoint setup script and systemd user unit templates.
- `docs/adr/`: architecture decisions. `GLOSSARY.md`: domain terms.

## Licence

Apache-2.0. See `LICENSE`.
