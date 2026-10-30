"""Chunked realtime test for OVMS /v3/audio/transcriptions: N sources at 1x speed.

Usage: python ovms_client.py URL MODEL LANG WINDOW_S OUTDIR WAV [WAV ...]
Each source is cut into WINDOW_S windows. A window is posted when its end time is
reached in real time; requests of one source run one after another.
Latency = result arrival - window end time.
"""

import asyncio
import io
import json
import sys
import time
import wave

import httpx


def q(xs, p):
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(p * (len(xs) - 1)))], 2) if xs else None


def wav_bytes(pcm):
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(pcm)
    return b.getvalue()


async def run_source(client, url, model, lang, window_s, path, idx, start):
    with wave.open(path, "rb") as w:
        pcm = w.readframes(w.getnframes())
    step = int(16000 * 2 * window_s)
    lat, rows = [], []
    for k, off in enumerate(range(0, len(pcm), step)):
        chunk = pcm[off : off + step]
        end_t = (off + len(chunk)) / 32000
        await asyncio.sleep(max(0.0, start + end_t - time.monotonic()))
        data = {"model": model, "temperature": "0"}
        if lang != "auto":
            data["language"] = lang
        t = time.monotonic()
        r = await client.post(
            url, data=data, files={"file": ("a.wav", wav_bytes(chunk), "audio/wav")}
        )
        now = time.monotonic()
        text = (
            r.json().get("text", "")
            if r.status_code == 200
            else f"HTTP {r.status_code}: {r.text[:100]}"
        )
        lat.append(now - (start + end_t))
        rows.append(
            {
                "k": k,
                "end_s": round(end_t, 2),
                "req_s": round(now - t, 2),
                "lat_s": round(now - (start + end_t), 2),
                "text": text,
            }
        )
    return {
        "source": idx,
        "windows": len(rows),
        "request_time_p50_s": q([r["req_s"] for r in rows], 0.5),
        "request_time_max_s": q([r["req_s"] for r in rows], 1.0),
        "latency_after_window_p50_s": q(lat, 0.5),
        "latency_after_window_max_s": q(lat, 1.0),
        "rows": rows,
    }


async def main():
    url, model, lang, window_s, outdir, wavs = (
        sys.argv[1],
        sys.argv[2],
        sys.argv[3],
        float(sys.argv[4]),
        sys.argv[5],
        sys.argv[6:],
    )
    async with httpx.AsyncClient(timeout=300) as client:
        start = time.monotonic() + 0.5
        res = await asyncio.gather(
            *(
                run_source(client, url, model, lang, window_s, p, i, start)
                for i, p in enumerate(wavs)
            )
        )
    with open(f"{outdir}/ovms_rows.json", "w") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    for r in res:
        print(json.dumps({k: v for k, v in r.items() if k != "rows"}))
    for row in res[0]["rows"]:
        print(f"  {row['end_s']:6.1f}s lat={row['lat_s']:5.2f}s  {row['text'][:110]}")


if __name__ == "__main__":
    asyncio.run(main())
