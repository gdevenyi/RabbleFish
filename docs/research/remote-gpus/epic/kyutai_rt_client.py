"""Paced client for the Kyutai moshi-server streaming ASR WebSocket (/api/asr-streaming).

Usage: python kyutai_rt_client.py URL OUTDIR TIMINGREF WAV [WAV ...]
  One WAV (16 kHz mono PCM16) per concurrent source. Audio is resampled to 24 kHz and
  sent at 1x real time as msgpack {"type": "Audio", "pcm": [float32]} frames of 1920
  samples (80 ms). After the audio: a Marker, then silence until the Marker comes back.
  TIMINGREF is a NeMo rt_events jsonl of the same WAV (word end times) or "-".
  Writes OUTDIR/rt_events_src<i>.jsonl (Step events thinned to 1 in 25) and
  OUTDIR/hyp_src<i>.txt. Prints a JSON summary per source.

Metrics (all in seconds, _t = time since first audio frame was sent):
  step_lag      = _t - step_idx * 0.08 for Step events (audio processed by the server).
  word_emit_lag = _t(Word) - start_time   (the server's own word start time).
  word_end_lag  = _t(EndWord) - stop_time (when the word end becomes known).
  approx word latency vs NeMo timing = _t(Word) - NeMo end of the matched word.
"""

import asyncio
import difflib
import json
import re
import statistics
import sys
import time
import wave

import msgpack
import numpy as np
import soxr
import websockets

SR = 24000
FRAME = 1920  # 80 ms at 24 kHz
FRAME_S = FRAME / SR
MIN_BLOCK = 3
API_KEY = "public_token"


def norm(w: str) -> str:
    return re.sub(r"[^\w']", "", w.lower().replace("’", "'"))


def q(v):
    if not v:
        return None
    v = sorted(v)
    return {
        "p50": round(statistics.median(v), 2),
        "p95": round(v[int(0.95 * (len(v) - 1))], 2),
        "max": round(v[-1], 2),
        "n": len(v),
    }


def write_text(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def ref_words(path: str):
    if path == "-":
        return []
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    out = []
    for line in lines:
        ev = json.loads(line)
        if ev.get("type", "").endswith(".completed"):
            for wd in ev.get("words") or []:
                n = norm(wd["word"])
                if n:
                    out.append((n, wd["end"]))
    return out


def load_pcm(path: str) -> np.ndarray:
    with wave.open(path, "rb") as w:
        assert (
            w.getframerate() == 16000
            and w.getnchannels() == 1
            and w.getsampwidth() == 2
        )
        x = (
            np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(
                np.float32
            )
            / 32768
        )
    return soxr.resample(x, 16000, SR).astype(np.float32)


def pack_audio(x) -> bytes:
    return msgpack.packb(
        {"type": "Audio", "pcm": [float(v) for v in x]}, use_single_float=True
    )


async def run_source(url, path, idx, outdir, refw):
    pcm = load_pcm(path)
    events = []
    start = None
    marker_back = asyncio.Event()
    async with websockets.connect(
        url,
        additional_headers={"kyutai-api-key": API_KEY},
        max_size=None,
        ping_interval=None,
    ) as ws:

        async def reader():
            try:
                async for msg in ws:
                    now = time.monotonic()
                    ev = msgpack.unpackb(msg, raw=False)
                    ev["_t"] = round(now - start, 3) if start else None
                    events.append(ev)
                    if ev.get("type") == "Marker":
                        marker_back.set()
            except websockets.ConnectionClosed as e:
                events.append({"type": "Error", "_client": f"connection closed: {e!r}"})
                marker_back.set()

        rd = asyncio.create_task(reader())
        start = time.monotonic()
        n = 0
        for n, off in enumerate(range(0, len(pcm), FRAME), start=1):
            await ws.send(pack_audio(pcm[off : off + FRAME]))
            await asyncio.sleep(max(0.0, start + n * FRAME_S - time.monotonic()))
        audio_end = time.monotonic() - start
        await ws.send(msgpack.packb({"type": "Marker", "id": 0}, use_single_float=True))
        silence = np.zeros(FRAME, dtype=np.float32)
        k = n
        while not marker_back.is_set() and time.monotonic() - start < audio_end + 30:
            k += 1
            await ws.send(pack_audio(silence))
            await asyncio.sleep(max(0.0, start + k * FRAME_S - time.monotonic()))
        marker_t = time.monotonic() - start if marker_back.is_set() else None
        rd.cancel()

    steps = [e for e in events if e.get("type") == "Step" and e.get("_t") is not None]
    step_lag = [
        e["_t"] - e["step_idx"] * FRAME_S for e in steps if e["_t"] <= audio_end
    ]
    words = [e for e in events if e.get("type") == "Word"]
    endw = [e for e in events if e.get("type") == "EndWord"]
    emit_lag = [e["_t"] - e["start_time"] for e in words]
    end_lag = [e["_t"] - e["stop_time"] for e in endw]
    text = " ".join(e["text"] for e in words)
    write_text(f"{outdir}/hyp_src{idx}.txt", text + "\n")
    hyp = [(norm(e["text"]), e["_t"]) for e in words if norm(e["text"])]
    lat = []
    if refw:
        sm = difflib.SequenceMatcher(
            a=[w for w, _ in hyp], b=[w for w, _ in refw], autojunk=False
        )
        for a, b, m in sm.get_matching_blocks():
            if m < MIN_BLOCK:
                continue
            for j in range(m):
                lat.append(hyp[a + j][1] - refw[b + j][1])
    kept = [e for e in events if e.get("type") != "Step"] + steps[::25]
    kept.sort(key=lambda e: e.get("_t") or 0)
    write_text(
        f"{outdir}/rt_events_src{idx}.jsonl",
        "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in kept),
    )
    late = " ".join(e["text"] for e in words if e["start_time"] > 60.5)
    return {
        "source": idx,
        "wav": path.rsplit("/", 1)[-1],
        "audio_s": round(audio_end, 1),
        "first_word_s": words[0]["_t"] if words else None,
        "words": len(words),
        "step_lag": q(step_lag),
        "word_emit_lag_vs_own_start": q(emit_lag),
        "word_end_lag_vs_own_stop": q(end_lag),
        "approx_word_latency_vs_nemo_timing": q(lat),
        "marker_back_after_audio_end_s": round(marker_t - audio_end, 2)
        if marker_t
        else None,
        "event_types": sorted({e.get("type") for e in events}),
        "text_after_60_5s_head": late[:200],
        "errors": [e for e in events if e.get("type") == "Error"][:3],
    }


async def main():
    url, outdir, tref, wavs = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:]
    refw = ref_words(tref)
    res = await asyncio.gather(
        *(run_source(url, p, i, outdir, refw) for i, p in enumerate(wavs))
    )
    print(json.dumps(res, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
