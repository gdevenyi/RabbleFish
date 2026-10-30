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

## Layout

- `backend/`: FastAPI app (`ltt` Python package, managed with `uv`).
- `frontend/`: React, Vite and TypeScript UI.
- `docs/adr/`: architecture decisions. `GLOSSARY.md`: domain terms.

## Licence

Apache-2.0. See `LICENSE`.
