## Agent skills

### Issue tracker

Issues are tracked in GitHub Issues for gdevenyi/live-transcribe-translate, through the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

The default vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

## Commands

- `pnpm dev`: backend (`uvicorn`, port 8000) and frontend (Vite, port 5173) together.
- `pnpm test`, `pnpm lint`, `pnpm build`, `pnpm start`: see `README.md`.
- Backend only: `uv run --project backend pytest backend`, `uv run --project backend ruff check backend`.
- Sources: `uv run --project backend python -m ltt.capture list`; record together with `... record <key> <key> --seconds 10 --out <dir>` (reports gaps and lag).
