"""The silent and muted warnings: the level of a chunk, the detector, mute in pw-dump
objects, and the `source_status` warning of a running Session (also saved in the log)."""

import asyncio
import math

import pytest
from fastapi.testclient import TestClient
from test_app import fake_watcher
from test_session import receive_until
from test_sources import node

from ltt import pipeline
from ltt.app import create_app
from ltt.capture import NS_PER_S, AudioChunk
from ltt.level import SilenceDetector, peak_dbfs
from ltt.sources import SourceRegistry, source_from_node
from ltt.store import LOG_NAME, read_events

SILENT = b"\0\0" * 1600
NEAR_SILENT = (20).to_bytes(2, "little", signed=True) * 1600  # about -64 dBFS
LOUD = (3000).to_bytes(2, "little", signed=True) * 1600  # about -21 dBFS


def chunk(n: int, pcm: bytes) -> AudioChunk:
    return AudioChunk("monitor:spk", n * NS_PER_S // 10, pcm)


def test_peak_dbfs():
    assert peak_dbfs(SILENT) == -math.inf
    assert peak_dbfs(b"") == -math.inf
    assert peak_dbfs((-32768).to_bytes(2, "little", signed=True)) == 0.0
    assert round(peak_dbfs(LOUD), 1) == -20.8
    assert peak_dbfs(NEAR_SILENT) < -60


def test_silent_after_the_set_time_and_cleared_by_sound():
    d = SilenceDetector(after_s=30, threshold_dbfs=-60)
    changes = []
    for n in range(400):
        pcm = SILENT if n < 150 else NEAR_SILENT if n < 350 else LOUD
        if d.feed(chunk(n, pcm), muted=False):
            changes.append((n, d.warning))
    # 300 quiet chunks of 100 ms: the warning comes with the 300th chunk (n = 299).
    assert changes == [(299, "silent"), (350, None)]


def test_a_short_sound_restarts_the_quiet_time():
    d = SilenceDetector(after_s=1, threshold_dbfs=-60)
    pcms = [SILENT] * 9 + [LOUD] + [SILENT] * 10
    warnings = [(d.feed(chunk(n, p), muted=False), d.warning)[1] for n, p in enumerate(pcms)]
    assert warnings[:19] == [None] * 19 and warnings[19] == "silent"


def test_muted_shows_at_once_and_sound_clears_it():
    d = SilenceDetector(after_s=30, threshold_dbfs=-60)
    assert d.feed(chunk(0, SILENT), muted=True) and d.warning == "muted"
    assert not d.feed(chunk(1, SILENT), muted=True)
    # Unmuted but still quiet: no warning until the quiet time is long enough.
    assert d.feed(chunk(2, SILENT), muted=False) and d.warning is None
    assert not d.feed(chunk(5, LOUD), muted=True) and d.warning is None  # sound wins
    assert d.feed(chunk(6, SILENT), muted=True) and d.warning == "muted"


def test_lost_audio_counts_as_quiet_time():
    d = SilenceDetector(after_s=30, threshold_dbfs=-60)
    d.feed(chunk(0, SILENT), muted=False)
    assert d.feed(chunk(300, SILENT), muted=False) and d.warning == "silent"


def test_the_defaults_are_the_constants():
    d = SilenceDetector()
    assert d.after_ns == 30 * NS_PER_S and d.threshold_dbfs == -60.0


def with_props(obj: dict, *props: dict) -> dict:
    return {**obj, "info": {**obj["info"], "params": {"Props": list(props)}}}


SINK = node(148, 2001, "Audio/Sink", "ltt_test", "Test sink")
MIC = node(58, 58, "Audio/Source", "alsa_input.mic", "Microphone")
FOLLOWS = ["monitor.channel-volumes", True, "channelmix.disable", False]


def test_mute_from_pw_dump_props():
    # The shape of a null sink in pw-dump after `pactl set-sink-mute ltt_test 1`.
    muted = with_props(SINK, {"volume": 1.0, "mute": True, "monitorMute": False, "params": FOLLOWS})
    assert source_from_node(muted).muted
    assert not source_from_node(with_props(SINK, {"mute": False, "params": FOLLOWS})).muted
    assert not source_from_node(SINK).muted  # no params
    # The monitor does not follow the sink volume: a muted sink still gives sound.
    own = ["monitor.channel-volumes", False]
    assert not source_from_node(with_props(SINK, {"mute": True, "params": own})).muted
    assert source_from_node(with_props(SINK, {"mute": False, "monitorMute": True})).muted
    # A microphone with two Props entries (ALSA): the first has the mute.
    assert source_from_node(with_props(MIC, {"mute": True}, {"params": []})).muted
    assert not source_from_node(with_props(MIC, {"mute": False}, {"params": []})).muted
    assert not source_from_node(with_props(MIC, {"monitorMute": True})).muted


def test_registry_follows_a_mute_change():
    registry = SourceRegistry()
    registry.apply([with_props(SINK, {"mute": False, "params": FOLLOWS})])
    assert not registry.get("monitor:ltt_test").muted
    assert registry.apply([with_props(SINK, {"mute": True, "params": FOLLOWS})])
    assert registry.get("monitor:ltt_test").muted


class ScriptedCapture:
    """Real-time-free capture: quiet chunks, then (when `loud` is set) loud chunks."""

    loud = False  # set by the test thread

    def __init__(self, source) -> None:
        self.source = source
        self._stopped = asyncio.Event()

    async def chunks(self):
        n = 0
        while not self._stopped.is_set():
            yield chunk(n, LOUD if ScriptedCapture.loud else SILENT)
            n += 1
            await asyncio.sleep(0.002)

    async def stop(self) -> None:
        self._stopped.set()


@pytest.fixture(autouse=True)
def fast_retry(monkeypatch):
    monkeypatch.setattr(pipeline, "RETRY_MIN_S", 0.05)


def warnings(events, key="monitor:spk"):
    return [e["warning"] for e in events if e["type"] == "source_status" and e["source_key"] == key]


@pytest.mark.parametrize("muted", [False, True])
def test_session_warns_while_the_endpoint_is_down_and_saves_it(data_dir, muted):
    spk = with_props(node(54, 54, "Audio/Sink", "spk"), {"mute": muted, "params": FOLLOWS})
    ScriptedCapture.loud = False
    # Port 9 refuses the connection: the Source stays in "connecting" / "error".
    app = create_app(
        watch=fake_watcher([spk]),
        asr_endpoint_url="ws://127.0.0.1:9",
        capture_factory=ScriptedCapture,
        detect_language=lambda _t: "en",
    )
    with TestClient(app) as c:
        c.patch("/api/sources/monitor:spk", json={"selected": True})
        with c.websocket_connect("/ws") as ws:
            c.post("/api/session/start")
            want = "muted" if muted else "silent"
            events = receive_until(ws, lambda ev: want in warnings(ev))
            if muted:
                assert warnings(events)[0] == "muted"  # at once, in the first event
            # Sound: the warning goes away, and the state does not change.
            ScriptedCapture.loud = True
            events += receive_until(ws, lambda ev: None in warnings(ev))
            c.post("/api/session/stop")
    statuses = [e for e in events if e["type"] == "source_status"]
    assert {e["state"] for e in statuses} <= {"connecting", "error"}
    assert not any("gap" in e for e in statuses)
    (d,) = sorted((data_dir / "sessions").iterdir())
    logged = [e for e in read_events(d / LOG_NAME) if e["type"] == "source_status"]
    assert want in warnings(logged) and warnings(logged)[-1] is None
