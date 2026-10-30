# ltt backend

FastAPI app that serves the WebSocket and REST API for the web UI, and the built frontend in production.

```sh
uv run uvicorn ltt.app:app --reload   # development, port 8000
uv run pytest
uv run ruff check && uv run ruff format --check
```

`LTT_STATIC_DIR` sets the directory of the built frontend (default: `../frontend/dist`, relative to this directory).
