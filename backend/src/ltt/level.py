"""The level of a Source, and the "silent" and "muted" warnings.

Each captured chunk (100 ms) gets its peak level. A chunk is quiet when its peak is
below `SILENCE_DBFS`. The warning of a Source is:

- "muted": the chunk is quiet and PipeWire reports the node as muted (see
  `ltt.sources.node_muted`). It shows at once.
- "silent": all chunks were quiet for `SILENT_AFTER_S` seconds of audio time.
- None: the last chunk had sound. A chunk with sound clears the warning at once.

The time comes from the chunk timestamps, not from the wall clock, so lost audio
between two quiet chunks counts as silence too.
"""

import math

from ltt.capture import NS_PER_S, AudioChunk

SILENT_AFTER_S = 30.0  # quiet time before the "silent" warning
SILENCE_DBFS = -60.0  # a chunk with a lower peak is quiet (about 33 of 32768)
FULL_SCALE = 32768


def peak_dbfs(pcm: bytes) -> float:
    """The peak of PCM16 (native byte order, which is little-endian on our targets) in
    dBFS; -inf for digital silence or no samples."""
    usable = len(pcm) - len(pcm) % 2
    if not usable:
        return -math.inf
    samples = memoryview(pcm)[:usable].cast("h")
    peak = max(max(samples), -min(samples))
    return 20 * math.log10(peak / FULL_SCALE) if peak else -math.inf


class SilenceDetector:
    """Gives the warning of one Source from its chunks."""

    def __init__(self, after_s: float | None = None, threshold_dbfs: float | None = None):
        """The defaults are `SILENT_AFTER_S` and `SILENCE_DBFS`. The app gives the
        `silent_after_s` and `silence_dbfs` settings (see `ltt.settings`)."""
        if after_s is None:
            after_s = SILENT_AFTER_S
        if threshold_dbfs is None:
            threshold_dbfs = SILENCE_DBFS
        self.after_ns = int(after_s * NS_PER_S)
        self.threshold_dbfs = threshold_dbfs
        self.quiet_since_ns: int | None = None  # start of the current quiet time
        self.warning: str | None = None

    def feed(self, chunk: AudioChunk, muted: bool) -> bool:
        """Measure one chunk. Return True if the warning changed."""
        before = self.warning
        if peak_dbfs(chunk.pcm) >= self.threshold_dbfs:
            self.quiet_since_ns = None
            self.warning = None
        else:
            if self.quiet_since_ns is None:
                self.quiet_since_ns = chunk.start_ns
            quiet_ns = chunk.start_ns + chunk.duration_ns - self.quiet_since_ns
            if muted:
                self.warning = "muted"
            elif quiet_ns >= self.after_ns:
                self.warning = "silent"
            else:
                self.warning = None
        return self.warning != before
