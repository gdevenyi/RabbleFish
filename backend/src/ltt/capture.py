"""Capture of one Source with `pw-record`, as 16 kHz mono PCM16 on the monotonic clock.

PipeWire converts and resamples in the stream. The raw pipe has no timestamps, so the
time of each chunk comes from an anchor (`time.monotonic_ns()` when the first bytes
arrive) plus the number of samples read since then. If the samples fall behind the
wall clock by more than `REANCHOR_NS`, audio was lost; the stream then counts a gap
and moves the anchor, so later chunks keep the correct time.
"""

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field

from ltt.sources import Source

SAMPLE_RATE = 16000
BYTES_PER_SAMPLE = 2  # s16, mono
CHUNK_BYTES = SAMPLE_RATE * BYTES_PER_SAMPLE // 10  # 100 ms
REANCHOR_NS = 50_000_000
NS_PER_S = 1_000_000_000

# Without these, WirePlumber can link the stream to another device with no error:
# the default device when the target cannot be linked, another device when the
# target goes away, or a device that another app (for example EasyEffects) chooses.
BASE_PROPERTIES = ("node.dont-fallback=true", "node.dont-reconnect=true", "node.dont-move=true")


def pw_record_args(source: Source) -> list[str]:
    props = list(BASE_PROPERTIES)
    if source.kind == "monitor":
        props.append("stream.capture.sink=true")  # capture the sink's monitor ports
    return [
        "pw-record",
        "--raw",
        "--rate",
        str(SAMPLE_RATE),
        "--channels",
        "1",
        "--format",
        "s16",
        "--target",
        str(source.serial),
        "-P",
        "{ " + " ".join(props) + " }",
        "-",
    ]


@dataclass(frozen=True)
class AudioChunk:
    source_key: str
    start_ns: int  # monotonic time of the first sample
    pcm: bytes  # PCM16 little-endian, mono, SAMPLE_RATE

    @property
    def duration_ns(self) -> int:
        return len(self.pcm) // BYTES_PER_SAMPLE * NS_PER_S // SAMPLE_RATE


@dataclass
class Timeline:
    """Gives each chunk its time from the anchor and the sample count."""

    clock: Callable[[], int] = time.monotonic_ns
    anchor_ns: int | None = None
    samples: int = 0  # since the anchor
    total_samples: int = 0
    gaps: int = 0
    max_lag_ns: int = 0  # largest seen lag of the sample clock behind the wall clock
    started_ns: int | None = field(default=None)

    def stamp(self, n_samples: int) -> int:
        """Return the start time of the next `n_samples`, read just now."""
        now = self.clock()
        if self.anchor_ns is None:
            # The chunk has just arrived, so it started n_samples ago.
            self.anchor_ns = now - n_samples * NS_PER_S // SAMPLE_RATE
            self.started_ns = self.anchor_ns
        else:
            end_ns = self.anchor_ns + (self.samples + n_samples) * NS_PER_S // SAMPLE_RATE
            lag = now - end_ns
            self.max_lag_ns = max(self.max_lag_ns, lag)
            if lag > REANCHOR_NS:
                self.gaps += 1
                self.anchor_ns = now - n_samples * NS_PER_S // SAMPLE_RATE
                self.samples = 0
        start = self.anchor_ns + self.samples * NS_PER_S // SAMPLE_RATE
        self.samples += n_samples
        self.total_samples += n_samples
        return start


class CaptureError(RuntimeError):
    pass


class Capture:
    """One running `pw-record` for one Source."""

    def __init__(self, source: Source, clock: Callable[[], int] = time.monotonic_ns) -> None:
        self.source = source
        self.timeline = Timeline(clock=clock)
        self._proc: asyncio.subprocess.Process | None = None
        self._stopping = False
        self.stderr = b""

    async def chunks(self) -> AsyncIterator[AudioChunk]:
        """Yield chunks until the stream ends; raise CaptureError if pw-record fails."""
        self._proc = await asyncio.create_subprocess_exec(
            *pw_record_args(self.source),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        assert self._proc.stdout is not None and self._proc.stderr is not None
        stderr_task = asyncio.create_task(self._proc.stderr.read())
        pending = b""
        eof = False
        try:
            while data := await self._proc.stdout.read(CHUNK_BYTES):
                data = pending + data
                usable = len(data) - len(data) % BYTES_PER_SAMPLE
                pending = data[usable:]
                if usable:
                    start = self.timeline.stamp(usable // BYTES_PER_SAMPLE)
                    yield AudioChunk(self.source.key, start, data[:usable])
            eof = True
        finally:
            if eof:
                await self._proc.wait()  # pw-record ended: by stop(), or by itself
            else:
                await self._terminate()  # the consumer stopped reading
            self.stderr = await stderr_task
        # pw-record exits with 1 also when we stop it, so only an unrequested exit is an error.
        if not self._stopping and self._proc.returncode != 0:
            msg = self.stderr.decode(errors="replace").strip()
            raise CaptureError(
                f"pw-record for {self.source.key} exited {self._proc.returncode}: {msg}"
            )

    async def stop(self) -> None:
        """Stop the capture; the running `chunks()` then ends without an error."""
        self._stopping = True
        await self._terminate()

    async def _terminate(self) -> None:
        if self._proc is not None and self._proc.returncode is None:
            self._proc.terminate()
            await self._proc.wait()


async def _record(keys: list[str], seconds: float, out_dir: str) -> int:
    import wave
    from pathlib import Path

    from ltt.sources import list_sources

    sources = {s.key: s for s in await list_sources()}
    missing = [k for k in keys if k not in sources]
    if missing:
        print(f"unknown source(s): {', '.join(missing)}")
        return 2
    captures = [Capture(sources[k]) for k in keys]

    async def run(cap: Capture) -> None:
        name = cap.source.key.replace(":", "_").replace("/", "_")
        with wave.open(str(Path(out_dir) / f"{name}.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(BYTES_PER_SAMPLE)
            w.setframerate(SAMPLE_RATE)
            async for chunk in cap.chunks():
                w.writeframes(chunk.pcm)

    t0 = time.monotonic_ns()
    tasks = [asyncio.create_task(run(c)) for c in captures]
    await asyncio.sleep(seconds)
    for c in captures:
        await c.stop()
    results = await asyncio.gather(*tasks, return_exceptions=True)
    wall = (time.monotonic_ns() - t0) / NS_PER_S
    for cap, res in zip(captures, results, strict=True):
        tl = cap.timeline
        audio = tl.total_samples / SAMPLE_RATE
        start = (tl.started_ns - t0) / NS_PER_S if tl.started_ns else float("nan")
        status = f"error: {res}" if isinstance(res, Exception) else "ok"
        print(
            f"{cap.source.key}: audio {audio:.2f} s in {wall:.2f} s,"
            f" first sample at +{start:.2f} s, gaps {tl.gaps},"
            f" max lag {tl.max_lag_ns / 1e6:.0f} ms, {status}"
        )
    return 0


def main() -> int:
    import argparse
    from pathlib import Path

    from ltt.sources import list_sources

    parser = argparse.ArgumentParser(prog="python -m ltt.capture")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list microphones and sink monitors")
    rec = sub.add_parser("record", help="record Sources together to WAV files")
    rec.add_argument("keys", nargs="+", help="Source keys from `list`")
    rec.add_argument("--seconds", type=float, default=10.0)
    rec.add_argument("--out", default="captures")
    args = parser.parse_args()
    if args.cmd == "list":
        for s in asyncio.run(list_sources()):
            print(f"{s.key}\t{s.description}\t(serial {s.serial})")
        return 0
    Path(args.out).mkdir(parents=True, exist_ok=True)
    return asyncio.run(_record(args.keys, args.seconds, args.out))


if __name__ == "__main__":
    raise SystemExit(main())
