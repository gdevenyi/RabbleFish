"""Realtime latency test for WhisperLive: N sources streamed at 1x speed.

Usage: python wl_client.py URL MODEL LANG OUTDIR WAV [WAV ...]
Latency of a completed segment = first arrival wall time - (stream start + segment end).
Latency of partial text = arrival wall time - (stream start + end of the newest segment).
"""

import asyncio
import json
import os
import statistics
import sys
import time
import uuid
import wave

import websockets

FRAME_MS = 256


def q(xs, p):
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(p * (len(xs) - 1)))], 2) if xs else None


async def run_source(url, model, lang, path, idx, outdir):
    with wave.open(path, "rb") as w:
        pcm = w.readframes(w.getnframes())
    frame_bytes = 16000 * 2 * FRAME_MS // 1000
    uid = str(uuid.uuid4())
    events, done_lat, part_lat, seen = [], [], [], {}
    async with websockets.connect(url, max_size=None, ping_interval=None) as ws:
        opts = {
            "uid": uid,
            "language": lang,
            "task": "transcribe",
            "model": model,
            "use_vad": True,
            "audio_format": "int16",
            "enable_diarization": os.environ.get("DIAR") == "1",
        }
        await ws.send(json.dumps(opts))
        t0 = time.monotonic()
        while True:
            m = json.loads(await ws.recv())
            events.append(m)
            if m.get("message") == "SERVER_READY":
                break
        ready_s = time.monotonic() - t0
        start = time.monotonic()

        async def reader():
            try:
                async for msg in ws:
                    now = time.monotonic()
                    m = json.loads(msg)
                    m["_t"] = round(now - start, 3)
                    events.append(m)
                    segs = m.get("segments") or []
                    for s in segs:
                        key = (round(float(s["start"]), 2), s.get("completed", False))
                        if s.get("completed") and key not in seen:
                            seen[key] = s["text"]
                            done_lat.append(now - (start + float(s["end"])))
                    if segs and not segs[-1].get("completed"):
                        part_lat.append(now - (start + float(segs[-1]["end"])))
            except websockets.ConnectionClosed as e:
                events.append({"_client": f"closed: {e!r}"})

        rd = asyncio.create_task(reader())
        for i, off in enumerate(range(0, len(pcm), frame_bytes)):
            await ws.send(pcm[off : off + frame_bytes])
            await asyncio.sleep(
                max(0.0, start + (i + 1) * FRAME_MS / 1000 - time.monotonic())
            )
        audio_s = time.monotonic() - start
        await ws.send(b"END_OF_AUDIO")
        await asyncio.sleep(10)
        rd.cancel()
    with open(f"{outdir}/wl_events_src{idx}.jsonl", "w") as f:
        f.writelines(json.dumps(e, ensure_ascii=False) + "\n" for e in events)
    text = " ".join(seen[k] for k in sorted(seen))
    langs = {e.get("language") for e in events if "language" in e}
    spk = {s.get("speaker") for e in events for s in (e.get("segments") or []) if s.get("speaker") is not None}
    return {
        "source": idx,
        "model_ready_s": round(ready_s, 1),
        "audio_s": round(audio_s, 1),
        "completed_segments": len(done_lat),
        "completed_latency_p50_s": q(done_lat, 0.5),
        "completed_latency_p95_s": q(done_lat, 0.95),
        "completed_latency_max_s": q(done_lat, 1.0),
        "partial_latency_p50_s": q(part_lat, 0.5),
        "partial_latency_p95_s": q(part_lat, 0.95),
        "languages_reported": sorted(str(x) for x in langs),
        "speakers": sorted(str(x) for x in spk),
        "text_head": text[:160],
        "text_tail": text[-200:],
        "mean_completed_latency_s": round(statistics.mean(done_lat), 2)
        if done_lat
        else None,
    }


async def main():
    url, model, lang, outdir, wavs = (
        sys.argv[1],
        sys.argv[2],
        sys.argv[3],
        sys.argv[4],
        sys.argv[5:],
    )
    lang = None if lang == "auto" else lang
    res = await asyncio.gather(
        *(run_source(url, model, lang, p, i, outdir) for i, p in enumerate(wavs))
    )
    print(json.dumps(res, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
