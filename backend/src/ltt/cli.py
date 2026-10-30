"""The `ltt` command (issue #31): `serve`, `sessions list`, `export` and `config`.

All commands read the settings (`ltt.settings`): the config file, then the LTT_*
environment variables. `sessions list` and `export` only read the saved Sessions; they
never change a log.
"""

import argparse
import ipaddress
import sys
import time
from datetime import datetime
from pathlib import Path

from ltt import __version__
from ltt.export import SessionExport, format_duration
from ltt.settings import Settings, SettingsError, config_path, load_settings
from ltt.store import SessionStore

EXIT_USAGE = 2
EXIT_NOT_FOUND = 1


def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def _url(host: str, port: int) -> str:
    shown = "127.0.0.1" if host in ("0.0.0.0", "") else "[::1]" if host == "::" else host
    if ":" in shown and not shown.startswith("["):
        shown = f"[{shown}]"
    return f"http://{shown}:{port}"


def cmd_serve(args: argparse.Namespace, settings: Settings) -> int:
    import uvicorn

    from ltt.app import create_app

    settings = settings.with_overrides(host=args.host, port=args.port)
    host, port = settings.host, settings.port
    print(f"live-transcribe-translate {__version__}: open {_url(host, port)}", flush=True)
    if host in ("0.0.0.0", "::"):
        print(f"  (listening on all network interfaces, port {port})", flush=True)
    if not is_loopback(host):
        print(
            f"WARNING: host is {host!r}, not 127.0.0.1. The app has no login: all persons "
            "who can reach this port can see the transcripts and start a Session. Use it "
            "only on a network that you trust.",
            file=sys.stderr,
            flush=True,
        )
    print(f"  endpoint: {settings.asr_endpoint_url} (the UI shows its state)", flush=True)
    print(f"  data: {settings.data_dir}", flush=True)
    uvicorn.run(create_app(settings=settings), host=host, port=port, log_level=args.log_level)
    return 0


def _date(started_at: float | None) -> str:
    if started_at is None:
        return "-"
    return datetime.fromtimestamp(started_at).strftime("%Y-%m-%d %H:%M")


def _speakers(summary: dict) -> str:
    names = [s.get("display_name") or s.get("label") or s["id"] for s in summary["speakers"]]
    return ", ".join(names) or "-"


def cmd_sessions_list(_args: argparse.Namespace, settings: Settings) -> int:
    store = SessionStore(settings.data_dir)
    rows = []
    for sid in store.ids():
        saved = store.load(sid)
        if saved is None:
            continue
        s = saved.summary()
        # "started": the log has no stop line. The Session runs now, or the app ended
        # without a stop and `ltt serve` marks it "interrupted" at its next start.
        rows.append(
            (
                s["id"],
                _date(s["started_at"]),
                format_duration(s["length"]),
                s["state"],
                _speakers(s),
            )
        )
    if not rows:
        print(f"No saved sessions in {store.dir}", file=sys.stderr)
        return 0
    header = ("ID", "DATE", "LENGTH", "STATE", "SPEAKERS")
    widths = [max(len(r[i]) for r in [header, *rows]) for i in range(4)]
    for r in [header, *rows]:
        print("  ".join(c.ljust(w) for c, w in zip(r[:4], widths, strict=True)) + "  " + r[4])
    return 0


def cmd_export(args: argparse.Namespace, settings: Settings) -> int:
    store = SessionStore(settings.data_dir)
    saved = store.load(args.session_id)
    if saved is None:
        print(f"ltt: unknown session: {args.session_id} (see `ltt sessions list`)", file=sys.stderr)
        return EXIT_NOT_FOUND
    export = SessionExport(saved.transcript(), args.session_id, now=time.time())
    body = export.json() if args.format == "json" else export.markdown()
    if args.output in (None, "-"):
        sys.stdout.write(body)
        if not body.endswith("\n"):
            sys.stdout.write("\n")
    else:
        Path(args.output).write_text(body, encoding="utf-8")
        print(f"Wrote {args.output}", file=sys.stderr)
    return 0


def cmd_config(_args: argparse.Namespace, settings: Settings) -> int:
    path = config_path()
    print(f"# config file: {path}{'' if path.is_file() else ' (not found: defaults)'}")
    rows = [
        (k, str(list(v) if isinstance(v, tuple) else v), src) for k, v, src in settings.effective()
    ]
    kw = max(len(r[0]) for r in rows)
    vw = max(len(r[1]) for r in rows)
    for k, v, src in rows:
        print(f"{k.ljust(kw)}  {v.ljust(vw)}  # {src}")
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ltt",
        description="Live transcription and translation of PipeWire sources.",
        epilog=f"Settings: {config_path()} and the LTT_* environment variables (see `ltt config`).",
    )
    p.add_argument("--version", action="version", version=f"ltt {__version__}")
    sub = p.add_subparsers(dest="command", metavar="COMMAND", required=True)

    serve = sub.add_parser("serve", help="start the web UI and the API")
    serve.add_argument("--host", help="the address to listen on (default: setting host)")
    serve.add_argument("--port", type=int, help="the port to listen on (default: setting port)")
    serve.add_argument(
        "--log-level",
        default="info",
        choices=["critical", "error", "warning", "info", "debug"],
        help="default: info",
    )
    serve.set_defaults(func=cmd_serve)

    sessions = sub.add_parser("sessions", help="the saved Sessions")
    sessions_sub = sessions.add_subparsers(
        dest="sessions_command", metavar="COMMAND", required=True
    )
    listing = sessions_sub.add_parser(
        "list", help="list the saved Sessions (ID, date, length, state, Speakers)"
    )
    listing.set_defaults(func=cmd_sessions_list)

    export = sub.add_parser("export", help="export one saved Session as Markdown or JSON")
    export.add_argument("session_id", metavar="SESSION_ID", help="an ID from `ltt sessions list`")
    export.add_argument("--format", "-f", choices=["md", "json"], default="md", help="default: md")
    export.add_argument("--output", "-o", metavar="FILE", help="write to FILE (default: stdout)")
    export.set_defaults(func=cmd_export)

    config = sub.add_parser("config", help="show the effective settings and their sources")
    config.set_defaults(func=cmd_config)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        settings = load_settings()
        return args.func(args, settings)
    except SettingsError as e:
        print(f"ltt: bad setting: {e}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
