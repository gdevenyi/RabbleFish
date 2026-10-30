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
