"""Saving the captured audio of a Session (issue #29).

Raw PCM16 little-endian, 16 kHz mono (`.pcm`), one file for each Source, and a new file
after each break in the capture: a restart of the capture, or a chunk that does not
follow the one before it on the monotonic clock (the capture moved its anchor after lost
audio). All captured audio is saved, also while the NeMo connection is down, so that a
gap can be transcribed again later.

Each file gets an `audio_file` event {source_key, path, start, sample_rate, format}:
`path` is relative to the Session directory and `start` is the Session time of the first
sample.
"""

import logging
import re
from collections.abc import Callable
from pathlib import Path

from rabblefish.capture import NS_PER_S, SAMPLE_RATE, AudioChunk
from rabblefish.store import AUDIO_DIR, Syncer
from rabblefish.transcript import CONTINUITY_TOLERANCE_NS

log = logging.getLogger(__name__)

AUDIO_FORMAT = "s16le"

Publish = Callable[[dict], None]


def file_stem(source_key: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", source_key)


class AudioRecorder:
    """Writes the audio of one Source to `.pcm` files in `<session dir>/audio/`."""

    def __init__(
        self, session_dir: Path, source_key: str, session_start_ns: int, publish: Publish
    ) -> None:
        self.session_dir = session_dir
        self.source_key = source_key
        self.session_start_ns = session_start_ns
        self.publish = publish
        self.files: list[Path] = []
        self._file: Syncer | None = None
        self._next_ns: int | None = None  # where the next chunk starts if it is contiguous
        self._failed = False

    def write(self, chunk: AudioChunk) -> None:
        if self._failed:
            return
        try:
            if self._file is None or (
                self._next_ns is not None
                and abs(chunk.start_ns - self._next_ns) > CONTINUITY_TOLERANCE_NS
            ):
                self._open(chunk.start_ns)
            assert self._file is not None
            self._file.write(chunk.pcm)
        except OSError as e:
            log.error("%s: cannot save the audio: %s", self.source_key, e)
            self._failed = True
            self.close()
            return
        self._next_ns = chunk.start_ns + chunk.duration_ns

    def capture_break(self) -> None:
        """The capture stopped: the next chunk goes to a new file."""
        self.close()

    def _open(self, start_ns: int) -> None:
        self.close()
        directory = self.session_dir / AUDIO_DIR
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{file_stem(self.source_key)}-{len(self.files) + 1:03d}.pcm"
        self._file = Syncer(path)
        self.files.append(path)
        self.publish(
            {
                "type": "audio_file",
                "source_key": self.source_key,
                "path": path.relative_to(self.session_dir).as_posix(),
                "start": round((start_ns - self.session_start_ns) / NS_PER_S, 3),
                "sample_rate": SAMPLE_RATE,
                "format": AUDIO_FORMAT,
            }
        )

    def sync(self) -> None:
        if self._file is not None:
            self._file.sync()

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None
        self._next_ns = None
