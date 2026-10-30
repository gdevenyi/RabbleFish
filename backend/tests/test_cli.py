"""The `ltt` command: help, `sessions list`, `export`, `config` and the `serve` warning."""

import json
import shutil
import time
from pathlib import Path

import jsonschema
import pytest
import uvicorn

import ltt
from ltt import cli
from ltt.store import LOG_NAME

FIXTURES = Path(__file__).parent / "fixtures" / "export"
SCHEMA = json.loads((Path(ltt.__file__).parent / "export.schema.json").read_text())
SESSION_ID = "2026-10-30T10-37-30"


@pytest.fixture
def utc(monkeypatch):
    """The local time zone is UTC (the time zone of the golden files)."""
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.fixture
def recorded(data_dir) -> Path:
    """A saved Session (the export fixture) and a second Session with no stop line."""
    d = data_dir / "sessions" / SESSION_ID
    d.mkdir(parents=True)
    shutil.copy(FIXTURES / "events.jsonl", d / LOG_NAME)
    open_one = data_dir / "sessions" / "2026-10-30T12-00-00"
    open_one.mkdir()
    (open_one / LOG_NAME).write_text(
        '{"type":"session","state":"started","started_at":1793361600.0,"target_lang":"fr"}\n'
    )
    return data_dir


def run(capsys, *argv: str) -> tuple[int, str, str]:
    code = cli.main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


def test_help_and_version(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["--help"])
    assert e.value.code == 0
    out = capsys.readouterr().out
    for command in ("serve", "sessions", "export", "config"):
        assert command in out
    with pytest.raises(SystemExit):
        cli.main(["--version"])
    assert capsys.readouterr().out.strip() == f"ltt {ltt.__version__}"
    with pytest.raises(SystemExit) as e:
        cli.main([])
    assert e.value.code == 2


def test_sessions_list(capsys, recorded, utc):
    code, out, _ = run(capsys, "sessions", "list")
    assert code == 0
    header, newest, oldest = out.splitlines()
    assert header.split() == ["ID", "DATE", "LENGTH", "STATE", "SPEAKERS"]
    assert newest.startswith("2026-10-30T12-00-00") and "started" in newest
    assert oldest.split()[:6] == [SESSION_ID, "2026-10-30", "10:37", "1", "h", "01"]
    assert "interrupted" in oldest
    assert oldest.endswith("Gabriel, Alice, Bertrand")


def test_sessions_list_does_not_change_the_logs(capsys, recorded):
    log = recorded / "sessions" / "2026-10-30T12-00-00" / LOG_NAME
    before = log.read_bytes()
    run(capsys, "sessions", "list")
    assert log.read_bytes() == before


def test_sessions_list_with_no_sessions(capsys, data_dir):
    code, out, err = run(capsys, "sessions", "list")
    assert code == 0 and out == "" and "No saved sessions" in err


def test_export_markdown_to_stdout(capsys, recorded, utc):
    code, out, _ = run(capsys, "export", SESSION_ID, "--format", "md")
    assert code == 0
    assert out == (FIXTURES / "expected.md").read_text(encoding="utf-8")


def test_export_json_to_a_file(capsys, recorded, tmp_path):
    target = tmp_path / "out.json"
    code, out, err = run(capsys, "export", SESSION_ID, "--format", "json", "-o", str(target))
    assert code == 0 and out == "" and str(target) in err
    data = json.loads(target.read_text())
    jsonschema.validate(data, SCHEMA)
    assert data["session"]["id"] == SESSION_ID


def test_export_unknown_session(capsys, recorded):
    code, out, err = run(capsys, "export", "2020-01-01T00-00-00")
    assert code == 1 and out == "" and "unknown session" in err
    code, _, err = run(capsys, "export", "../../etc")
    assert code == 1 and "unknown session" in err


def test_config_shows_the_sources(capsys, monkeypatch, tmp_path):
    path = tmp_path / "config" / "live-transcribe-translate" / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_text("port = 8123\n")
    monkeypatch.setenv("LTT_HOST", "0.0.0.0")
    code, out, _ = run(capsys, "config")
    assert code == 0
    assert f"# config file: {path}" in out
    lines = {line.split()[0]: line for line in out.splitlines()[1:]}
    assert lines["port"].split() == ["port", "8123", "#", "file"]
    assert lines["host"].endswith("# env LTT_HOST")
    assert lines["default_target_language"].endswith("# default")


def test_a_bad_config_file_is_a_clear_error(capsys, tmp_path):
    path = tmp_path / "config" / "live-transcribe-translate" / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_text("colour = 'blue'\n")
    code, out, err = run(capsys, "sessions", "list")
    assert code == 2 and out == ""
    assert err.startswith("ltt: bad setting: ") and "unknown key 'colour'" in err


@pytest.fixture
def no_server(monkeypatch) -> list:
    """`uvicorn.run` records its arguments and returns at once."""
    calls = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: calls.append((app, kw)))
    return calls


def test_serve_on_loopback_has_no_warning(capsys, no_server):
    code, out, err = run(capsys, "serve", "--port", "8765")
    assert code == 0
    assert "open http://127.0.0.1:8765" in out
    assert "WARNING" not in err
    ((app, kw),) = no_server
    assert kw["host"] == "127.0.0.1" and kw["port"] == 8765
    assert app.state.settings.source("port") == "flag"


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.20", "::"])
def test_serve_warns_when_the_host_is_not_loopback(capsys, no_server, monkeypatch, host):
    monkeypatch.setenv("LTT_HOST", host)
    code, out, err = run(capsys, "serve")
    assert code == 0
    assert "WARNING" in err and "no login" in err
    assert no_server[0][1]["host"] == host


@pytest.mark.parametrize(
    ("host", "loopback"),
    [("127.0.0.1", True), ("127.0.1.1", True), ("::1", True), ("localhost", True)]
    + [("0.0.0.0", False), ("::", False), ("myhost.lan", False)],
)
def test_is_loopback(host, loopback):
    assert cli.is_loopback(host) is loopback
