from ltt.capture import NS_PER_S, SAMPLE_RATE, Timeline, pw_record_args
from ltt.sources import Source

MIC = Source("microphone:m", "microphone", "m", "Mic", 58)
MON = Source("monitor:s", "monitor", "s", "Monitor of Speaker", 54)

CHUNK = SAMPLE_RATE // 10  # 100 ms
CHUNK_NS = NS_PER_S // 10


def test_monitor_captures_sink_and_mic_does_not():
    mic_props = pw_record_args(MIC)[pw_record_args(MIC).index("-P") + 1]
    mon_props = pw_record_args(MON)[pw_record_args(MON).index("-P") + 1]
    assert "stream.capture.sink=true" in mon_props
    assert "stream.capture.sink" not in mic_props
    for props in (mic_props, mon_props):
        for p in ("node.dont-fallback=true", "node.dont-reconnect=true", "node.dont-move=true"):
            assert p in props
    assert pw_record_args(MIC)[pw_record_args(MIC).index("--target") + 1] == "58"


class FakeClock:
    def __init__(self, t=10 * NS_PER_S):
        self.t = t

    def __call__(self):
        return self.t


def test_first_chunk_is_anchored_at_its_start():
    clock = FakeClock()
    tl = Timeline(clock=clock)
    assert tl.stamp(CHUNK) == clock.t - CHUNK_NS


def test_steady_stream_has_consecutive_times_and_no_gap():
    clock = FakeClock()
    tl = Timeline(clock=clock)
    first = tl.stamp(CHUNK)
    for i in range(1, 50):
        clock.t += CHUNK_NS + 3_000_000  # pipe jitter below the threshold
        assert tl.stamp(CHUNK) == first + i * CHUNK_NS
        clock.t -= 3_000_000
    assert tl.gaps == 0


def test_lost_audio_is_a_gap_and_reanchors():
    clock = FakeClock()
    tl = Timeline(clock=clock)
    tl.stamp(CHUNK)
    clock.t += CHUNK_NS + 500_000_000  # 0.5 s of audio never arrived
    start = tl.stamp(CHUNK)
    assert tl.gaps == 1
    assert start == clock.t - CHUNK_NS
