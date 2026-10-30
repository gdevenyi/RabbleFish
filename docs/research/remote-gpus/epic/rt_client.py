"""Realtime latency test for NeMo-Speech.cpp: N sources streamed at 1x speed.

Usage: python rt_client.py URL OUTDIR WAV [WAV ...]   (one WAV per concurrent source)
Per final word: latency = arrival wall time - (stream start + word end time).
"""

import asyncio
import json
import os
import statistics
import sys
import time
import wave

import websockets

FRAME_MS = 80
ENDPOINT_MS = 800


async def run_source(url: str, path: str, idx: int, outdir: str) -> dict:
    with wave.open(path, "rb") as w:
        assert (
            w.getframerate() == 16000
            and w.getnchannels() == 1
            and w.getsampwidth() == 2
        )
        pcm = w.readframes(w.getnframes())
    frame_bytes = 16000 * 2 * FRAME_MS // 1000
    events = []
    word_lat, first_partial = [], None
    async with websockets.connect(url, max_size=None, ping_interval=None) as ws:
        events.append(json.loads(await ws.recv()))  # session.created
        await ws.send(
            json.dumps(
                {
                    "type": "session.update",
                    "session": {
                        "word_timestamps": True,
                        "speaker_diarization": os.environ.get("DIAR", "1") == "1",
                        "endpointing_ms": ENDPOINT_MS,
                        **({"language": os.environ["LANG_CODE"]} if os.environ.get("LANG_CODE") else {}),
                    },
                }
            )
        )
        start = None

        async def reader():
            nonlocal first_partial
            try:
                async for msg in ws:
                    now = time.monotonic()
                    ev = json.loads(msg)
                    ev["_t"] = round(now - start, 3) if start else None
                    events.append(ev)
                    t = ev.get("type", "")
                    if t.endswith(".delta") and first_partial is None and start:
                        first_partial = now - start
                    if t.endswith(".completed"):
                        for wd in ev.get("words", []) or []:
                            if "end" in wd:
                                word_lat.append(now - (start + wd["end"]))
            except websockets.ConnectionClosed as e:
                events.append(
                    {
                        "type": "error",
                        "_client": f"connection closed: {e!r}",
                        "_t": round(time.monotonic() - start, 3),
                    }
                )

        start = time.monotonic()
        rd = asyncio.create_task(reader())
        for i, off in enumerate(range(0, len(pcm), frame_bytes)):
            await ws.send(pcm[off : off + frame_bytes])
            # pace to real time against the absolute schedule
            target = start + (i + 1) * FRAME_MS / 1000
            await asyncio.sleep(max(0.0, target - time.monotonic()))
        audio_end = time.monotonic() - start
        await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
        await asyncio.sleep(8)  # drain finals after commit
        rd.cancel()
    with open(f"{outdir}/rt_events_src{idx}.jsonl", "w") as f:
        f.writelines(json.dumps(ev, ensure_ascii=False) + "\n" for ev in events)
    q = sorted(word_lat)
    speakers = {
        wd.get("speaker")
        for ev in events
        for wd in (ev.get("words") or [])
        if isinstance(wd, dict)
    }
    langs = {
        ev.get("language") for ev in events if ev.get("type", "").endswith(".completed")
    }
    return {
        "source": idx,
        "wav": path.rsplit("/", 1)[-1],
        "audio_s": round(audio_end, 1),
        "finals": sum(1 for e in events if e.get("type", "").endswith(".completed")),
        "words": len(q),
        "first_partial_s": round(first_partial, 2) if first_partial else None,
        "word_latency_p50_s": round(statistics.median(q), 2) if q else None,
        "word_latency_p95_s": round(q[int(0.95 * (len(q) - 1))], 2) if q else None,
        "word_latency_max_s": round(q[-1], 2) if q else None,
        "speakers_seen": sorted(s for s in speakers if s is not None),
        "languages_seen": sorted(str(x) for x in langs),
        "errors": [e for e in events if e.get("type") == "error"][:3],
    }


async def main() -> None:
    url, outdir, wavs = sys.argv[1], sys.argv[2], sys.argv[3:]
    res = await asyncio.gather(
        *(run_source(url, p, i, outdir) for i, p in enumerate(wavs))
    )
    print(json.dumps(res, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
