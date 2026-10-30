"""Paced client for the vLLM Realtime WebSocket API (/v1/realtime).

Usage: python vllm_rt_client.py URL MODEL OUTDIR TIMINGREF WAV [WAV ...]
  One WAV per concurrent source, streamed at 1x real time in 80 ms PCM16 frames
  (base64 in input_audio_buffer.append). TIMINGREF is a NeMo rt_events jsonl of the
  same WAV (word end times) or "-". Writes OUTDIR/rt_events_src<i>.jsonl and
  OUTDIR/hyp_src<i>.txt (language tags stripped). Prints a JSON summary per source.

Approximate word latency = arrival time of the last character of a hypothesis word
minus the end time of the matching word in TIMINGREF (difflib word alignment,
only matching runs of >= 3 words).
"""

import asyncio
import base64
import difflib
import json
import re
import statistics
import sys
import time
import wave

import websockets

FRAME_MS = 80
DRAIN_TIMEOUT_S = 60
MIN_BLOCK = 3
LANG_TAG = re.compile(r"language\s+([A-Za-z]+)\s*<asr_text>")


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
    out = []
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    for line in lines:
        ev = json.loads(line)
        if ev.get("type", "").endswith(".completed"):
            for wd in ev.get("words") or []:
                n = norm(wd["word"])
                if n:
                    out.append((n, wd["end"]))
    return out


async def run_source(url, model, path, idx, outdir, refw):
    with wave.open(path, "rb") as w:
        assert (
            w.getframerate() == 16000
            and w.getnchannels() == 1
            and w.getsampwidth() == 2
        )
        pcm = w.readframes(w.getnframes())
    frame_bytes = 16000 * 2 * FRAME_MS // 1000
    events, chars = [], []  # chars: (char, arrival_t)
    start = None
    done = asyncio.Event()
    async with websockets.connect(url, max_size=None, ping_interval=None) as ws:
        events.append(json.loads(await ws.recv()))  # session.created
        await ws.send(json.dumps({"type": "session.update", "model": model}))
        await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
        sent = 0

        async def reader():
            try:
                async for msg in ws:
                    now = time.monotonic() - start
                    ev = json.loads(msg)
                    ev["_t"] = round(now, 3)
                    ev["_audio_sent_s"] = round(sent * FRAME_MS / 1000, 2)
                    events.append(ev)
                    if ev.get("type") == "transcription.delta":
                        chars.extend((c, now) for c in ev.get("delta", ""))
                    elif ev.get("type") == "transcription.done":
                        done.set()
                    elif ev.get("type") == "error":
                        pass
            except websockets.ConnectionClosed as e:
                events.append(
                    {
                        "type": "error",
                        "_client": f"connection closed: {e!r}",
                        "_t": round(time.monotonic() - start, 3),
                    }
                )
                done.set()

        start = time.monotonic()
        rd = asyncio.create_task(reader())
        for i, off in enumerate(range(0, len(pcm), frame_bytes)):
            chunk = pcm[off : off + frame_bytes]
            await ws.send(
                json.dumps(
                    {
                        "type": "input_audio_buffer.append",
                        "audio": base64.b64encode(chunk).decode(),
                    }
                )
            )
            sent = i + 1
            target = start + (i + 1) * FRAME_MS / 1000
            await asyncio.sleep(max(0.0, target - time.monotonic()))
        audio_end = time.monotonic() - start
        await ws.send(json.dumps({"type": "input_audio_buffer.commit", "final": True}))
        try:
            await asyncio.wait_for(done.wait(), DRAIN_TIMEOUT_S)
        except TimeoutError:
            events.append(
                {
                    "type": "error",
                    "_client": "no transcription.done within timeout",
                    "_t": round(time.monotonic() - start, 3),
                }
            )
        rd.cancel()
    write_text(
        f"{outdir}/rt_events_src{idx}.jsonl",
        "".join(json.dumps(ev, ensure_ascii=False) + "\n" for ev in events),
    )

    raw = "".join(c for c, _ in chars)
    langs = LANG_TAG.findall(raw)
    # language tags with the time they arrived
    lang_times = [
        (m.group(1), round(chars[m.end() - 1][1], 2)) for m in LANG_TAG.finditer(raw)
    ]
    # strip tags but keep per-char arrival times
    # a tag starts each Qwen3-ASR segment: replace it with one space (segment break)
    keep = [True] * len(raw)
    for m in LANG_TAG.finditer(raw):
        for k in range(m.start() + 1, m.end()):
            keep[k] = False
        chars[m.start()] = (" ", chars[m.start()][1])
    text_chars = [(c, t) for (c, t), k in zip(chars, keep) if k]
    text = "".join(c for c, _ in text_chars)
    write_text(f"{outdir}/hyp_src{idx}.txt", text.strip() + "\n")
    # words with arrival time of their last character
    hyp, cur, last_t = [], "", None
    for c, t in text_chars + [(" ", None)]:
        if c.isspace():
            if norm(cur):
                hyp.append((norm(cur), last_t))
            cur = ""
        else:
            cur += c
            last_t = t
    lat = []
    if refw:
        sm = difflib.SequenceMatcher(
            a=[w for w, _ in hyp], b=[w for w, _ in refw], autojunk=False
        )
        for a, b, n in sm.get_matching_blocks():
            if (
                n < MIN_BLOCK
            ):  # skip short matches (e.g. lone "yeah") that align far away
                continue
            for k in range(n):
                lat.append(hyp[a + k][1] - refw[b + k][1])
    deltas = [
        e for e in events if e.get("type") == "transcription.delta" and e.get("delta")
    ]
    done_ev = [e for e in events if e.get("type") == "transcription.done"]
    # text that arrived after 61 s of stream (French part of en_fr.wav)
    late = "".join(c for c, t in text_chars if t > 61.0)
    return {
        "source": idx,
        "wav": path.rsplit("/", 1)[-1],
        "audio_s": round(audio_end, 1),
        "first_delta_s": deltas[0]["_t"] if deltas else None,
        "n_deltas": len(deltas),
        "final_done_after_audio_end_s": round(done_ev[0]["_t"] - audio_end, 2)
        if done_ev
        else None,
        "approx_word_latency_vs_nemo_timing": q(lat),
        "hyp_words": len(hyp),
        "language_tags_seen": sorted(set(langs)),
        "language_tag_times": lang_times[:40],
        "text_after_61s_head": late[:200],
        "errors": [e for e in events if e.get("type") == "error"][:3],
    }


async def main():
    url, model, outdir, tref, wavs = (
        sys.argv[1],
        sys.argv[2],
        sys.argv[3],
        sys.argv[4],
        sys.argv[5:],
    )
    refw = ref_words(tref)
    res = await asyncio.gather(
        *(run_source(url, model, p, i, outdir, refw) for i, p in enumerate(wavs))
    )
    print(json.dumps(res, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
