"""The state of the model endpoint, for the "Endpoint" chip of the UI (issue #31).

`rabblefish serve` checks the endpoint when it starts, but it never waits for the check: the app
starts also when the endpoint is not reachable yet. The app checks again at each Session
start, and every `RECHECK_S` seconds while the endpoint is not ready.

The check is `GET /ready` and `GET /v1/models` on the ASR endpoint, and `GET /v1/models`
on the translation endpoint when it is another server. The result is the
`endpoint_status` event (not saved in the Session log):

    {"type": "endpoint_status", "state": "checking" | "ready" | "not_ready" | "unreachable",
     "asr_url": ..., "translation_url": ...,
     "capabilities": ["transcription", "diarization", "translation"],
     "missing": [...], "message": str | None, "checked_at": unix time | None}

- "unreachable": the ASR endpoint does not answer.
- "not_ready": it answers, but `/ready` is not true or it has no transcription model.
- "ready": it can transcribe. `missing` names the capabilities that it does not have
  (diarization, translation); then the UI shows a warning, but a Session can start.
"""

import json
import time
import urllib.error
import urllib.request

CAPABILITIES = ("transcription", "diarization", "translation")
CHECK_TIMEOUT_S = 3.0
RECHECK_S = 30.0


class _Unreachable(Exception):
    pass


def _get_json(url: str) -> dict:
    """The JSON body; raise _Unreachable when there is no answer, ValueError for an HTTP
    error or a body that is not JSON."""
    try:
        with urllib.request.urlopen(url, timeout=CHECK_TIMEOUT_S) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise ValueError(f"{url}: HTTP {e.code}") from e
    except (OSError, TimeoutError) as e:
        raise _Unreachable(f"{url}: {getattr(e, 'reason', e)}") from e
    except json.JSONDecodeError as e:
        raise ValueError(f"{url}: the answer is not JSON") from e


def _capabilities(base_url: str) -> set[str]:
    models = _get_json(base_url + "/v1/models").get("data") or []
    return {m.get("capability") for m in models if isinstance(m, dict)}


def initial_status(asr_http_url: str, translation_url: str) -> dict:
    return {
        "type": "endpoint_status",
        "state": "checking",
        "asr_url": asr_http_url,
        "translation_url": translation_url,
        "capabilities": [],
        "missing": [],
        "message": None,
        "checked_at": None,
    }


def check_endpoint(asr_http_url: str, translation_url: str) -> dict:
    """Check the endpoint (blocking; run it in a thread). It never raises."""
    status = initial_status(asr_http_url, translation_url)
    status["checked_at"] = time.time()
    found: set[str] = set()
    try:
        ready = _get_json(asr_http_url + "/ready").get("ready")
        found |= _capabilities(asr_http_url)
    except _Unreachable as e:
        return {**status, "state": "unreachable", "message": str(e)}
    except ValueError as e:
        return {**status, "state": "not_ready", "message": str(e)}
    message = None
    if translation_url.rstrip("/") != asr_http_url.rstrip("/"):
        # The app translates only through translation_url.
        found.discard("translation")
        try:
            found |= _capabilities(translation_url) & {"translation"}
        except (_Unreachable, ValueError) as e:
            message = f"translation endpoint: {e}"
    capabilities = [c for c in CAPABILITIES if c in found]
    missing = [c for c in CAPABILITIES if c not in found]
    if not ready:
        state, message = "not_ready", f"{asr_http_url}/ready: the endpoint is not ready"
    elif "transcription" not in found:
        state, message = "not_ready", f"{asr_http_url}/v1/models: no transcription model"
    else:
        state = "ready"
        if missing and message is None:
            message = "no " + " or ".join(missing) + " model"
    return {
        **status,
        "state": state,
        "capabilities": capabilities,
        "missing": missing,
        "message": message,
    }
