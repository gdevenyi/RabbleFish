# live-transcribe-translate

Live transcription of the audio on a Linux (PipeWire) desktop, with one timeline column for each speaker and optional translation. Models run behind configurable endpoints, on this machine or on a remote one (see `docs/adr/`).

Work in progress. The plan lives in the [wayfinder map](https://github.com/gdevenyi/live-transcribe-translate/issues/1).

## Development

Needs `uv`, Node.js and `pnpm`.

```sh
pnpm install
pnpm dev      # backend on :8000 and Vite on http://127.0.0.1:5173
pnpm test     # backend tests, frontend type check and frontend unit tests (vitest)
pnpm lint     # ruff
pnpm build    # build the frontend into frontend/dist
pnpm start    # backend only, serving frontend/dist on http://127.0.0.1:8000
```

Demo mode (development only): open http://127.0.0.1:5173/?demo to replay a recorded Session in the Timeline without the backend pipeline. `?demo&speed=4` plays it faster, and `?demo&history=0` starts it at the beginning. The production build does not contain the demo.

## Endpoint

The app needs a NeMo-Speech.cpp endpoint for transcription, diarization and translation. Set it up on this machine (or on a GPU machine on your network):

```sh
scripts/setup-endpoint.sh --backend vulkan   # or cuda (compute capability 7.5+) or cpu
```

The script downloads the server and the models (and converts the translation model) into `~/.local/share/live-transcribe-translate/endpoint`, and prints the `nemo-speech serve` command. It needs about 5.3 GB of disk, and about 11 GB more during the conversion. Run it again at any time: it skips the work that is done. For remote use, the required server flags and the systemd user units, see [`docs/endpoint.md`](docs/endpoint.md).

## Layout

- `backend/`: FastAPI app (`ltt` Python package, managed with `uv`).
- `frontend/`: React, Vite and TypeScript UI.
- `scripts/`: endpoint setup script and systemd user unit templates.
- `docs/adr/`: architecture decisions. `GLOSSARY.md`: domain terms.

## Licence

Apache-2.0. See `LICENSE`.
