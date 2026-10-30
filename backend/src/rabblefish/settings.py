"""The settings of the app: one TOML file, with environment overrides (issue #31).

The file is `$XDG_CONFIG_HOME/rabblefish/config.toml` (by default
`~/.config/rabblefish/config.toml`). The app works with no file.

Precedence, from high to low: a command-line flag of `rabblefish serve` (only `--host` and
`--port`), an environment variable, the file, the default. `translation_endpoint_url`
with no value is the `http://` form of `asr_endpoint_url` (the same server).

The choices for one Session (Sources, modes, Target language, "Save audio") stay in the
UI; `default_target_language` is only the first value of the "Translate to" selector.
"""

import math
import os
import tomllib
import urllib.parse
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any

from rabblefish.translation import DEFAULT_TARGET_LANGUAGE, TARGET_LANGUAGES, normalize_target

APP_DIR = "rabblefish"
CONFIG_NAME = "config.toml"

DEFAULT_ASR_ENDPOINT_URL = "ws://127.0.0.1:8080"
DEFAULT_DETECT_LANGUAGES = ("en", "fr")
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_SILENT_AFTER_S = 30.0
DEFAULT_SILENCE_DBFS = -60.0


class SettingsError(ValueError):
    """The config file or an environment variable has a value that the app cannot use."""


def config_path(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    xdg = env.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(xdg) / APP_DIR / CONFIG_NAME


def default_data_dir(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    xdg = env.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(xdg) / APP_DIR


def http_form(ws_url: str) -> str:
    """`ws://host:port/path` -> `http://host:port/path` (`wss` -> `https`)."""
    parts = urllib.parse.urlsplit(ws_url.rstrip("/"))
    scheme = "https" if parts.scheme == "wss" else "http"
    return urllib.parse.urlunsplit((scheme, parts.netloc, parts.path, "", ""))


@dataclass(frozen=True)
class Settings:
    asr_endpoint_url: str = DEFAULT_ASR_ENDPOINT_URL
    # None: the http:// form of asr_endpoint_url. See `translation_url`.
    translation_endpoint_url: str | None = None
    detect_languages: tuple[str, ...] = DEFAULT_DETECT_LANGUAGES
    default_target_language: str = DEFAULT_TARGET_LANGUAGE
    data_dir: Path = field(default_factory=default_data_dir)
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    silent_after_s: float = DEFAULT_SILENT_AFTER_S
    silence_dbfs: float = DEFAULT_SILENCE_DBFS
    # Where each value comes from: "default", "file", "env RABBLEFISH_...", "flag" or "derived".
    sources: dict[str, str] = field(default_factory=dict, compare=False, repr=False)

    @property
    def translation_url(self) -> str:
        return self.translation_endpoint_url or http_form(self.asr_endpoint_url)

    def source(self, key: str) -> str:
        if key == "translation_endpoint_url" and self.translation_endpoint_url is None:
            return "derived from asr_endpoint_url"
        return self.sources.get(key, "default")

    def with_overrides(self, source: str = "flag", **values: Any) -> "Settings":
        """A copy with some values replaced, for example `rabblefish serve --port`."""
        values = {k: v for k, v in values.items() if v is not None}
        checked = {k: _check(k, v, source) for k, v in values.items()}
        return replace(self, **checked, sources={**self.sources, **dict.fromkeys(values, source)})

    def effective(self) -> list[tuple[str, Any, str]]:
        """(key, value, source) for each setting, for `rabblefish config`."""
        out = []
        for f in fields(self):
            if f.name == "sources":
                continue
            value = getattr(self, f.name)
            if f.name == "translation_endpoint_url":
                value = self.translation_url
            out.append((f.name, value, self.source(f.name)))
        return out


KEYS = tuple(f.name for f in fields(Settings) if f.name != "sources")

# The environment variable of each key, and how to read its text.
ENV: dict[str, tuple[str, Callable[[str], Any]]] = {
    "asr_endpoint_url": ("RABBLEFISH_ASR_ENDPOINT_URL", str),
    "translation_endpoint_url": ("RABBLEFISH_TRANSLATION_ENDPOINT_URL", str),
    "detect_languages": ("RABBLEFISH_LANGUAGES", lambda s: [c.strip() for c in s.split(",")]),
    "default_target_language": ("RABBLEFISH_DEFAULT_TARGET_LANGUAGE", str),
    "data_dir": ("RABBLEFISH_DATA_DIR", str),
    "host": ("RABBLEFISH_HOST", str),
    "port": ("RABBLEFISH_PORT", int),
    "silent_after_s": ("RABBLEFISH_SILENT_AFTER_S", float),
    "silence_dbfs": ("RABBLEFISH_SILENCE_DBFS", float),
}


def _check(key: str, value: Any, where: str) -> Any:
    """Return the value in its stored form, or raise SettingsError."""

    def bad(why: str) -> SettingsError:
        return SettingsError(f"{where}: {key} {why} (got {value!r})")

    if key in ("asr_endpoint_url", "translation_endpoint_url", "host"):
        if not isinstance(value, str) or not value.strip():
            raise bad("must be a non-empty string")
        value = value.strip()
        if key == "asr_endpoint_url" and urllib.parse.urlsplit(value).scheme not in ("ws", "wss"):
            raise bad("must start with ws:// or wss://")
        if key == "translation_endpoint_url" and urllib.parse.urlsplit(value).scheme not in (
            "http",
            "https",
        ):
            raise bad("must start with http:// or https://")
        return value.rstrip("/") if key != "host" else value
    if key == "detect_languages":
        if not isinstance(value, list | tuple) or not all(isinstance(c, str) for c in value):
            raise bad('must be a list of language codes, for example ["en", "fr"]')
        codes = tuple(c.strip().lower() for c in value if c.strip())
        if not codes:
            raise bad("must have at least one language code")
        return codes
    if key == "default_target_language":
        target = normalize_target(value) if isinstance(value, str) else None
        if target is None:
            raise bad(
                "is not a supported Target language; use one of " + ", ".join(TARGET_LANGUAGES)
            )
        return target
    if key == "data_dir":
        if not isinstance(value, str | Path) or not str(value).strip():
            raise bad("must be a path")
        return Path(value).expanduser()
    if key == "port":
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
            raise bad("must be a whole number from 1 to 65535")
        return value
    if key in ("silent_after_s", "silence_dbfs"):
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
        ):
            raise bad("must be a number")
        value = float(value)
        if key == "silent_after_s" and value <= 0:
            raise bad("must be more than 0")
        return value
    raise SettingsError(f"{where}: unknown key {key!r}; the keys are: {', '.join(KEYS)}")


def read_file(path: Path) -> dict[str, Any]:
    """The checked values of the config file; {} when there is no file."""
    try:
        with path.open("rb") as f:
            raw = tomllib.load(f)
    except FileNotFoundError:
        return {}
    except tomllib.TOMLDecodeError as e:
        raise SettingsError(f"{path}: not valid TOML: {e}") from e
    except OSError as e:
        raise SettingsError(f"{path}: cannot read the file: {e}") from e
    return {key: _check(key, value, str(path)) for key, value in raw.items()}


def load_settings(env: Mapping[str, str] | None = None, path: Path | None = None) -> Settings:
    """The effective settings: the defaults, then the file, then the environment.

    Raise SettingsError for a bad file, an unknown key or a bad value.
    """
    env = os.environ if env is None else env
    path = config_path(env) if path is None else path
    values: dict[str, Any] = {"data_dir": default_data_dir(env)}
    sources: dict[str, str] = {}
    for key, value in read_file(path).items():
        values[key] = value
        sources[key] = "file"
    for key, (name, parse) in ENV.items():
        text = env.get(name)
        if text is None or text == "":
            continue
        try:
            parsed = parse(text)
        except ValueError as e:
            raise SettingsError(f"environment {name}: {key} has a bad value {text!r}") from e
        values[key] = _check(key, parsed, f"environment {name}")
        sources[key] = f"env {name}"
    return Settings(**values, sources=sources)


def static_dir(env: Mapping[str, str] | None = None) -> Path | None:
    """The directory of the built UI: `RABBLEFISH_STATIC_DIR`, else the copy in the installed
    package (`rabblefish/static`), else `frontend/dist` of the source checkout. None if no
    directory exists (in development Vite serves the UI)."""
    env = os.environ if env is None else env
    if override := env.get("RABBLEFISH_STATIC_DIR"):
        return Path(override)
    here = Path(__file__).resolve().parent
    for candidate in (here / "static", here.parents[2] / "frontend" / "dist"):
        if candidate.is_dir():
            return candidate
    return None
