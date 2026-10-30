"""Translation of Segments (decided in gdevenyi/RabbleFish#12).

Each `segment` is translated once, after it is finalized and its language is detected,
through the NeMo-Speech.cpp text translation endpoint (`POST /v1/translations`, with
Riva-Translate). Partial text is never translated, and each Segment is translated alone.

- The source language is the Segment's language; else the last detected language of its
  Speaker; else that of its Source; else the Segment is not translated.
- A Segment in the Target language is not translated.
- Riva-Translate has English on one side of each pair. A pair with no English side
  (for example de -> fr) is not translated.

One worker translates one Segment at a time, so the transcription never waits. The
result is the `translation` event {segment_id, text, target_lang}. The state of the
endpoint is the `translation_status` event {state: ready | error, target_lang, message}.
"""

import asyncio
import contextlib
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable

log = logging.getLogger(__name__)

TRANSLATIONS_PATH = "/v1/translations"
CHECK_TIMEOUT_S = 5.0
TRANSLATE_TIMEOUT_S = 60.0  # a 4B model on a busy laptop can be slow
DEFAULT_TARGET_LANGUAGE = "en"

# Riva-Translate-4B-Instruct-v2: English, and the languages it translates to and from
# English. Keep in step with TARGET_LANGUAGES in frontend/src/languages.ts.
OTHER_LANGUAGES = (
    "cs da de el es-ES es-US fi fr hu it lt lv nl no pl pt-PT pt-BR ro ru sk sv "
    "zh-CN zh-TW ja hi ko et sl bg uk hr ar vi tr id th"
).split()
TARGET_LANGUAGES = ("en", *OTHER_LANGUAGES)
_SUPPORTED_BASES = {"en"} | {c.split("-")[0].lower() for c in OTHER_LANGUAGES}
# Codes from the language identifier (ISO 639-1) that Riva-Translate names differently.
_ALIASES = {"nb": "no", "nn": "no"}

Publish = Callable[[dict], None]


def normalize_target(code: str) -> str | None:
    """Return the Target language in its canonical form, or None if not supported."""
    by_lower = {c.lower(): c for c in TARGET_LANGUAGES}
    return by_lower.get(code.strip().lower())


def base(code: str) -> str:
    """The language without its region: "es-ES" -> "es"."""
    code = code.lower().split("-")[0]
    return _ALIASES.get(code, code)


class LanguageTracker:
    """Chooses the source language of each Segment, and the Segments to skip."""

    def __init__(self, target_lang: str) -> None:
        self.target_lang = target_lang
        self._by_speaker: dict[str, str] = {}
        self._by_source: dict[str, str] = {}

    def source_language(self, segment: dict) -> tuple[str | None, str]:
        """Return (source language, "") to translate, or (None, the reason to skip).

        Call it once for each Segment, in the order of the Segments: a Segment with a
        language updates the last language of its Speaker and of its Source.
        """
        lang = segment.get("lang")
        speaker, source = segment.get("speaker_id"), segment.get("source_key")
        if lang:
            lang = base(lang)
            self._by_speaker[speaker] = lang
            self._by_source[source] = lang
        else:
            lang = self._by_speaker.get(speaker) or self._by_source.get(source)
        if lang is None:
            return None, "unknown language"
        if lang == base(self.target_lang):
            return None, "already in the target language"
        if lang not in _SUPPORTED_BASES:
            return None, f"{lang} is not a Riva-Translate language"
        if "en" not in (lang, base(self.target_lang)):
            return None, f"{lang} -> {self.target_lang} has no English side"
        return lang, ""


class TranslationError(RuntimeError):
    """The translation endpoint is not reachable, has no model, or failed."""


class TranslationEndpoint:
    def __init__(self, url: str) -> None:
        self.url = url.rstrip("/")
        if urllib.parse.urlsplit(self.url).scheme not in ("http", "https"):
            raise ValueError(f"translation_endpoint_url must be http:// or https://: {url}")

    def _request(self, path: str, body: dict | None, timeout: float) -> dict:
        url = self.url + path
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            detail = ""
            with contextlib.suppress(Exception):
                detail = e.read().decode(errors="replace")[:200]
            raise TranslationError(f"{url}: HTTP {e.code} {detail}".strip()) from e
        except (OSError, ValueError) as e:
            reason = getattr(e, "reason", e)
            raise TranslationError(f"{url}: {reason}") from e

    def _check(self) -> None:
        models = self._request("/v1/models", None, CHECK_TIMEOUT_S).get("data") or []
        if not any(m.get("capability") == "translation" for m in models):
            raise TranslationError(f"{self.url}/v1/models: no translation model")

    async def check(self) -> None:
        """Raise TranslationError unless `/v1/models` has a translation model."""
        await asyncio.to_thread(self._check)

    def _translate(self, text: str, source: str, target: str) -> str:
        body = {"input": text, "source_language": source, "target_language": target}
        out = self._request(TRANSLATIONS_PATH, body, TRANSLATE_TIMEOUT_S)
        try:
            return out["translations"][0]["text"]
        except (KeyError, IndexError, TypeError) as e:
            raise TranslationError(f"{self.url}{TRANSLATIONS_PATH}: bad response") from e

    async def translate(self, text: str, source: str, target: str) -> str:
        return await asyncio.to_thread(self._translate, text, source, target)


class Translator:
    """Translates the Segments of one Session in a background task, one at a time."""

    def __init__(self, endpoint: TranslationEndpoint, target_lang: str, publish: Publish) -> None:
        self.endpoint = endpoint
        self.target_lang = target_lang
        self.publish = publish
        self.languages = LanguageTracker(target_lang)
        self._queue: asyncio.Queue[tuple[dict, str, float]] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._state: str | None = None
        self._message: str | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    def submit(self, segment: dict) -> None:
        """Queue a Segment for translation, or skip it. It does not wait."""
        source, reason = self.languages.source_language(segment)
        if source is None:
            log.debug("segment %s not translated: %s", segment["id"], reason)
            return
        self._queue.put_nowait((segment, source, time.monotonic()))

    async def stop(self, drain_s: float) -> None:
        """Translate the queued Segments for up to `drain_s` seconds, then stop."""
        if self._task is None:
            return
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._queue.join(), drain_s)
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task

    def _status(self, state: str, message: str | None = None) -> None:
        if (state, message) == (self._state, self._message):
            return
        self._state, self._message = state, message
        self.publish(
            {
                "type": "translation_status",
                "state": state,
                "target_lang": self.target_lang,
                "message": message,
            }
        )

    async def _check(self) -> bool:
        try:
            await self.endpoint.check()
        except TranslationError as e:
            log.warning("translation: %s", e)
            self._status("error", str(e))
            return False
        self._status("ready")
        return True

    async def _run(self) -> None:
        ready = await self._check()
        while True:
            segment, source, queued = await self._queue.get()
            try:
                if not ready:  # check again, at most once for each Segment
                    ready = await self._check()
                    if not ready:
                        continue
                t0 = time.monotonic()
                try:
                    text = await self.endpoint.translate(segment["text"], source, self.target_lang)
                except TranslationError as e:
                    log.warning("translation of %s: %s", segment["id"], e)
                    self._status("error", str(e))
                    ready = False
                    continue
                now = time.monotonic()
                log.info(
                    "translated %s (%s -> %s) in %.2f s, %.2f s after the segment",
                    segment["id"],
                    source,
                    self.target_lang,
                    now - t0,
                    now - queued,
                )
                self._status("ready")
                self.publish(
                    {
                        "type": "translation",
                        "segment_id": segment["id"],
                        "text": text.strip(),
                        "target_lang": self.target_lang,
                    }
                )
            finally:
                self._queue.task_done()
