"""The settings: defaults, the TOML file, the environment overrides and the errors."""

from pathlib import Path

import pytest

from ltt.settings import SettingsError, config_path, load_settings, static_dir


def write_config(env: dict, text: str) -> Path:
    path = config_path(env)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


@pytest.fixture
def env(tmp_path) -> dict:
    """A clean environment: only the XDG directories, in tmp_path."""
    return {"XDG_CONFIG_HOME": str(tmp_path / "config"), "XDG_DATA_HOME": str(tmp_path / "data")}


def test_defaults_with_no_file(env, tmp_path):
    s = load_settings(env)
    assert config_path(env) == tmp_path / "config" / "live-transcribe-translate" / "config.toml"
    assert s.asr_endpoint_url == "ws://127.0.0.1:8080"
    assert s.translation_endpoint_url is None
    assert s.translation_url == "http://127.0.0.1:8080"
    assert s.detect_languages == ("en", "fr")
    assert s.default_target_language == "en"
    assert s.data_dir == tmp_path / "data" / "live-transcribe-translate"
    assert (s.host, s.port) == ("127.0.0.1", 8000)
    assert (s.silent_after_s, s.silence_dbfs) == (30.0, -60.0)
    assert s.source("port") == "default"
    assert s.source("translation_endpoint_url") == "derived from asr_endpoint_url"


def test_file_values(env, tmp_path):
    write_config(
        env,
        """
asr_endpoint_url = "wss://gpu.lan:8443/"
translation_endpoint_url = "http://other:9000"
detect_languages = ["EN", "de", "fr"]
default_target_language = "es-es"
data_dir = "~/ltt-data"
host = "0.0.0.0"
port = 8123
silent_after_s = 10
silence_dbfs = -50.5
""",
    )
    s = load_settings(env)
    assert s.asr_endpoint_url == "wss://gpu.lan:8443"
    assert s.translation_url == "http://other:9000"
    assert s.detect_languages == ("en", "de", "fr")
    assert s.default_target_language == "es-ES"
    assert s.data_dir == Path("~/ltt-data").expanduser()
    assert (s.host, s.port) == ("0.0.0.0", 8123)
    assert (s.silent_after_s, s.silence_dbfs) == (10.0, -50.5)
    assert s.source("port") == "file"


def test_translation_url_follows_a_wss_asr_url(env):
    write_config(env, 'asr_endpoint_url = "wss://gpu.lan:8443"\n')
    assert load_settings(env).translation_url == "https://gpu.lan:8443"


def test_environment_overrides_the_file(env, tmp_path):
    write_config(env, 'port = 8123\nasr_endpoint_url = "ws://file:1"\ndata_dir = "/from/file"\n')
    env |= {
        "LTT_PORT": "9001",
        "LTT_ASR_ENDPOINT_URL": "ws://env:2",
        "LTT_LANGUAGES": "en, de",
        "LTT_DATA_DIR": str(tmp_path / "env-data"),
        "LTT_DEFAULT_TARGET_LANGUAGE": "fr",
        "LTT_HOST": "::1",
        "LTT_SILENT_AFTER_S": "2.5",
        "LTT_SILENCE_DBFS": "-40",
        "LTT_TRANSLATION_ENDPOINT_URL": "",  # empty: not set
    }
    s = load_settings(env)
    assert s.port == 9001 and s.source("port") == "env LTT_PORT"
    assert s.asr_endpoint_url == "ws://env:2"
    assert s.translation_url == "http://env:2"
    assert s.detect_languages == ("en", "de")
    assert s.data_dir == tmp_path / "env-data"
    assert s.default_target_language == "fr" and s.host == "::1"
    assert (s.silent_after_s, s.silence_dbfs) == (2.5, -40.0)


def test_flag_overrides_everything(env):
    env["LTT_PORT"] = "9001"
    s = load_settings(env).with_overrides(port=9100, host=None)
    assert s.port == 9100 and s.source("port") == "flag"
    assert s.host == "127.0.0.1" and s.source("host") == "default"


def test_bad_toml(env):
    path = write_config(env, "port = \n")
    with pytest.raises(SettingsError, match=f"{path}: not valid TOML"):
        load_settings(env)


def test_unknown_key(env):
    write_config(env, 'asr_url = "ws://x:1"\n')
    with pytest.raises(
        SettingsError, match="unknown key 'asr_url'; the keys are: asr_endpoint_url"
    ):
        load_settings(env)


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ('port = "8000"', "port must be a whole number"),
        ("port = 70000", "port must be a whole number"),
        ('asr_endpoint_url = "http://x:1"', "must start with ws:// or wss://"),
        ('translation_endpoint_url = "ws://x:1"', "must start with http:// or https://"),
        ('detect_languages = "en,fr"', "must be a list of language codes"),
        ("detect_languages = []", "at least one language code"),
        ('default_target_language = "xx"', "not a supported Target language"),
        ('silent_after_s = "long"', "silent_after_s must be a number"),
        ("silent_after_s = 0", "must be more than 0"),
        ('host = ""', "host must be a non-empty string"),
    ],
)
def test_bad_values_in_the_file(env, line, message):
    write_config(env, line + "\n")
    with pytest.raises(SettingsError, match=message):
        load_settings(env)


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("LTT_PORT", "eighty", "environment LTT_PORT: port has a bad value"),
        ("LTT_SILENCE_DBFS", "loud", "environment LTT_SILENCE_DBFS"),
        ("LTT_ASR_ENDPOINT_URL", "http://x:1", "environment LTT_ASR_ENDPOINT_URL"),
    ],
)
def test_bad_environment_values(env, name, value, message):
    env[name] = value
    with pytest.raises(SettingsError, match=message):
        load_settings(env)


def test_effective_lists_every_key_with_its_source(env):
    write_config(env, "port = 8123\n")
    rows = {k: (v, src) for k, v, src in load_settings(env).effective()}
    assert rows["port"] == (8123, "file")
    assert rows["translation_endpoint_url"] == (
        "http://127.0.0.1:8080",
        "derived from asr_endpoint_url",
    )
    assert "sources" not in rows and len(rows) == 9


def test_static_dir_override_and_checkout(tmp_path):
    assert static_dir({"LTT_STATIC_DIR": str(tmp_path)}) == tmp_path
    found = static_dir({})
    # In the checkout (no installed copy in ltt/static): frontend/dist if it is built.
    assert found is None or found.name in ("static", "dist")
