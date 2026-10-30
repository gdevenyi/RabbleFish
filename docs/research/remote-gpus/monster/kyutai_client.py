"""Paced client for moshi-server BatchedAsr: N concurrent sources at 1x real time.

Usage: python kyutai_client.py URL OUTDIR WAV [WAV ...]   (16 kHz mono PCM16 WAVs, resampled to 24 kHz)
Writes OUTDIR/ky_events_src<i>.jsonl (every server message except prs arrays trimmed, with _t since stream start)
and prints a JSON summary per source.
"""

import asyncio
import json
import sys
import time
import wave

import msgpack
import numpy as np
import websockets
from scipy.signal import resample_poly

SR = 24000
FRAME = 1920  # 80 ms


def pct(q, p):
    q = sorted(q)
    return round(q[int(p * (len(q) - 1))], 2) if q else None


async def run_source(url, path, idx, outdir):
    with wave.open(path, "rb") as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1
        pcm = (
            np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(
                np.float32
            )
            / 32768
        )
    pcm = resample_poly(pcm, 3, 2).astype(np.float32)
    events = []
    got_marker = asyncio.Event()
    async with websockets.connect(url, max_size=None, ping_interval=None) as ws:
        start = time.monotonic()

        async def reader():
            try:
                async for msg in ws:
                    ev = msgpack.unpackb(msg, raw=False)
                    ev["_t"] = round(time.monotonic() - start, 3)
                    if "prs" in ev:
                        ev["prs"] = [round(x, 3) for x in ev["prs"]]
                    events.append(ev)
                    if ev.get("type") == "Marker":
                        got_marker.set()
                        return
            except websockets.ConnectionClosed as e:
                events.append(
                    {
                        "type": "Error",
                        "_client": repr(e),
                        "_t": round(time.monotonic() - start, 3),
                    }
                )
                got_marker.set()

        rd = asyncio.create_task(reader())

        async def send(chunk):
            await ws.send(
                msgpack.packb(
                    {"type": "Audio", "pcm": chunk.tolist()}, use_single_float=True
                )
            )

        i = 0
        for off in range(0, len(pcm), FRAME):
            await send(pcm[off : off + FRAME])
            i += 1
            await asyncio.sleep(max(0.0, start + i * FRAME / SR - time.monotonic()))
        audio_end = time.monotonic() - start
        await ws.send(msgpack.packb({"type": "Marker", "id": 0}))
        silence = np.zeros(FRAME, dtype=np.float32)
        for _ in range(150):  # up to 12 s of paced silence to flush the model delay
            if got_marker.is_set():
                break
            await send(silence)
            i += 1
            await asyncio.sleep(max(0.0, start + i * FRAME / SR - time.monotonic()))
        try:
            await asyncio.wait_for(rd, 5)
        except TimeoutError:
            rd.cancel()
    with open(f"{outdir}/ky_events_src{idx}.jsonl", "w") as f:
        f.writelines(json.dumps(ev, ensure_ascii=False) + "\n" for ev in events)
    words = [e for e in events if e.get("type") == "Word"]
    word_lat = [e["_t"] - e["start_time"] for e in words]
    end_lat = [e["_t"] - e["stop_time"] for e in events if e.get("type") == "EndWord"]
    step_lag = [
        e["_t"] - (e["step_idx"] + 1) * FRAME / SR
        for e in events
        if e.get("type") == "Step"
    ]
    with open(f"{outdir}/hyp_src{idx}.txt", "w") as f:
        f.write(" ".join(e["text"] for e in words) + "\n")
    return {
        "source": idx,
        "wav": path.rsplit("/", 1)[-1],
        "audio_s": round(audio_end, 1),
        "words": len(words),
        "marker_received": got_marker.is_set(),
        "first_word_s": words[0]["_t"] if words else None,
        "word_start_to_arrival_p50_p95_max": [
            pct(word_lat, 0.5),
            pct(word_lat, 0.95),
            pct(word_lat, 1),
        ],
        "word_end_to_endword_p50_p95_max": [
            pct(end_lat, 0.5),
            pct(end_lat, 0.95),
            pct(end_lat, 1),
        ],
        "step_lag_p50_p95_max": [
            pct(step_lag, 0.5),
            pct(step_lag, 0.95),
            pct(step_lag, 1),
        ],
        "steps": len(step_lag),
        "message_types": sorted({e.get("type") for e in events}),
        "message_keys": sorted({k for e in events for k in e}),
        "errors": [e for e in events if e.get("type") == "Error"][:3],
    }


async def main():
    url, outdir, wavs = sys.argv[1], sys.argv[2], sys.argv[3:]
    res = await asyncio.gather(
        *(run_source(url, p, i, outdir) for i, p in enumerate(wavs))
    )
    print(json.dumps(res, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
