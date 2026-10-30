"""Translation of Segments: the source-language rule, the skips, and a Session against a
fake translation endpoint."""

import pytest
from conftest import FakeCapture
from fastapi.testclient import TestClient
from test_app import MIC, SPEAKER, fake_watcher
from test_session import count, receive_until

from ltt import pipeline
from ltt.app import create_app
from ltt.translation import LanguageTracker, normalize_target

FRENCH = {"le", "je", "de", "et", "à", "mais", "la", "dans"}


@pytest.fixture(autouse=True)
def fast_retry(monkeypatch):
    monkeypatch.setattr(pipeline, "RETRY_MIN_S", 0.05)


def detect(text):
    return "fr" if FRENCH & set(text.lower().split()) else "en"


def make_client(nemo_url, translation_url):
    app = create_app(
        watch=fake_watcher([MIC, SPEAKER]),
        asr_endpoint_url=nemo_url,
        capture_factory=FakeCapture,
        detect_language=detect,
        translation_endpoint_url=translation_url,
    )
    return TestClient(app)


def seg(sid, lang, speaker="s#1", source="s"):
    return {"id": sid, "speaker_id": speaker, "source_key": source, "lang": lang, "text": "x"}


# The source-language rule and the skips


def test_source_language_is_the_segment_language():
    t = LanguageTracker("en")
    assert t.source_language(seg("1", "fr")) == ("fr", "")


def test_fallback_to_the_speaker_then_the_source():
    t = LanguageTracker("en")
    t.source_language(seg("1", "fr", speaker="s#1"))
    t.source_language(seg("2", "de", speaker="s#2"))
    # A Segment with no language: the last language of its Speaker.
    assert t.source_language(seg("3", None, speaker="s#1")) == ("fr", "")
    # A new Speaker: the last language of its Source (here, of s#2).
    assert t.source_language(seg("4", None, speaker="s#3")) == ("de", "")
    # A Source with no language yet: no translation.
    lang, reason = t.source_language(seg("5", None, speaker="o#1", source="o"))
    assert lang is None and reason == "unknown language"


def test_skip_segments_in_the_target_language():
    t = LanguageTracker("en")
    assert t.source_language(seg("1", "en")) == (None, "already in the target language")
    # The fallback language counts too.
    assert t.source_language(seg("2", None))[0] is None
    # The region of the Target language does not matter.
    assert LanguageTracker("es-ES").source_language(seg("3", "es"))[0] is None


def test_skip_pairs_with_no_english_side():
    t = LanguageTracker("fr")
    lang, reason = t.source_language(seg("1", "de"))
    assert lang is None and "no English side" in reason
    assert t.source_language(seg("2", "en")) == ("en", "")


def test_skip_languages_that_riva_translate_does_not_have():
    lang, reason = LanguageTracker("en").source_language(seg("1", "eu"))
    assert lang is None and "not a Riva-Translate language" in reason


def test_target_language_names():
    assert normalize_target("en") == "en"
    assert normalize_target("es-es") == "es-ES"
    assert normalize_target("ZH-cn") == "zh-CN"
    assert normalize_target("es") is None
    assert normalize_target("eu") is None


# A Session with translation


def start(c, target=None):
    c.patch("/api/sources/monitor:spk", json={"selected": True})
    body = None if target is None else {"target_language": target}
    r = c.post("/api/session/start", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_french_segments_get_english_translations(fake_nemo, fake_translator):
    nemo, tr = fake_nemo(), fake_translator()
    with make_client(nemo.url, tr.url) as c:
        with c.websocket_connect("/ws") as ws:
            assert start(c)["target_lang"] == "en"  # the default
            events = receive_until(ws, lambda ev: count(ev, "translation") >= 4)
        segments = {e["id"]: e for e in events if e["type"] == "segment"}
        translations = [e for e in events if e["type"] == "translation"]
        for t in translations:
            s = segments[t["segment_id"]]
            assert s["lang"] == "fr"
            assert t == {
                "type": "translation",
                "segment_id": s["id"],
                "text": f"[en] {s['text']}",
                "target_lang": "en",
            }
        assert all(r["source_language"] == "fr" for r in tr.requests)
        assert all(r["target_language"] == "en" for r in tr.requests)
        assert [e for e in events if e["type"] == "translation_status"][0]["state"] == "ready"

        # A UI that connects now gets the translations in the snapshot.
        with c.websocket_connect("/ws") as ws:
            snap = receive_until(ws, lambda ev: count(ev, "translation_status") >= 1)
            assert count(snap, "translation") >= 4
            assert snap[2]["type"] == "session" and snap[2]["target_lang"] == "en"
            kinds = [e["type"] for e in snap]
            assert kinds.index("segment") < kinds.index("translation")
        assert c.post("/api/session/stop").status_code == 200


def test_target_french_translates_the_english_segments(fake_nemo, fake_translator):
    nemo, tr = fake_nemo(), fake_translator()
    with make_client(nemo.url, tr.url) as c, c.websocket_connect("/ws") as ws:
        assert start(c, "fr")["target_lang"] == "fr"
        events = receive_until(ws, lambda ev: count(ev, "translation") >= 3)
        c.post("/api/session/stop")
    segments = {e["id"]: e for e in events if e["type"] == "segment"}
    for t in (e for e in events if e["type"] == "translation"):
        assert t["target_lang"] == "fr"
        assert segments[t["segment_id"]]["lang"] in ("en", None)  # None: the fallback
    assert all(r["source_language"] == "en" for r in tr.requests)


def test_unsupported_target_language_is_400(fake_nemo, fake_translator):
    with make_client(fake_nemo().url, fake_translator().url) as c:
        c.patch("/api/sources/monitor:spk", json={"selected": True})
        r = c.post("/api/session/start", json={"target_language": "eu"})
        assert r.status_code == 400 and "unsupported target language" in r.text
        r = c.post("/api/session/start", json={"target_language": "es-es"})
        assert r.status_code == 200 and r.json()["target_lang"] == "es-ES"
        c.post("/api/session/stop")


def test_no_translation_model_does_not_stop_the_session(fake_nemo, fake_translator):
    nemo, tr = fake_nemo(), fake_translator(capabilities=("transcription",))
    with make_client(nemo.url, tr.url) as c, c.websocket_connect("/ws") as ws:
        start(c)
        events = receive_until(
            ws,
            lambda ev: (
                count(ev, "translation_status", state="error") >= 1
                and count(ev, "segment", lang="fr") >= 3
            ),
        )
        assert c.post("/api/session/stop").status_code == 200
    status = next(e for e in events if e["type"] == "translation_status")
    assert status["state"] == "error" and "no translation model" in status["message"]
    assert count(events, "translation") == 0 and tr.requests == []
    assert count(events, "translation_status") == 1  # sent once, not for each Segment


def test_endpoint_error_does_not_stop_the_session(fake_nemo, fake_translator):
    nemo, tr = fake_nemo(), fake_translator(fail=1)  # only the first request fails
    with make_client(nemo.url, tr.url) as c, c.websocket_connect("/ws") as ws:
        start(c)
        events = receive_until(ws, lambda ev: count(ev, "translation") >= 1)
        assert c.post("/api/session/stop").status_code == 200
    states = [e["state"] for e in events if e["type"] == "translation_status"]
    assert states[:3] == ["ready", "error", "ready"]
    error = next(e for e in events if e["type"] == "translation_status" and e["state"] == "error")
    assert "HTTP 500" in error["message"]
    first_fr = next(e for e in events if e["type"] == "segment" and e["lang"] == "fr")
    assert all(e["segment_id"] != first_fr["id"] for e in events if e["type"] == "translation")
