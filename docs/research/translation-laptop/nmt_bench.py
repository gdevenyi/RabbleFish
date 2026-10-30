"""Riva-Translate latency through NeMo-Speech.cpp /v1/translations.

Usage:
  python nmt_bench.py BASE_URL EVENTS.jsonl OUT.json alone
  python nmt_bench.py BASE_URL EVENTS.jsonl OUT.json live N_SOURCES
EVENTS.jsonl is a recorded realtime run; its `.completed` events give the segments and
their final times. Segments with more French than English stopwords count as French.
In `live` mode each source posts each segment at its recorded final time (1x).
"""

import asyncio
import json
import statistics
import sys
import time

import httpx

FR = {
    "le",
    "la",
    "les",
    "de",
    "des",
    "je",
    "il",
    "ne",
    "pas",
    "et",
    "un",
    "une",
    "que",
    "mais",
    "à",
    "en",
    "du",
}
EN = {
    "the",
    "a",
    "and",
    "to",
    "i",
    "we",
    "it",
    "is",
    "that",
    "you",
    "of",
    "what",
    "just",
    "yeah",
    "if",
}


def segments(path):
    out = []
    for line in open(path, encoding="utf-8"):
        e = json.loads(line)
        if e.get("type", "").endswith(".completed") and e.get("transcript", "").strip():
            words = [w.lower().strip(".,?!") for w in e["transcript"].split()]
            lang = (
                "fr"
                if sum(w in FR for w in words) > sum(w in EN for w in words)
                else "en"
            )
            out.append({"t": e["_t"], "text": e["transcript"].strip(), "lang": lang})
    return out


async def translate(client, base, seg):
    src, dst = (seg["lang"], "fr" if seg["lang"] == "en" else "en")
    t = time.monotonic()
    r = await client.post(
        f"{base}/v1/translations",
        json={"input": seg["text"], "source_language": src, "target_language": dst},
    )
    dt = time.monotonic() - t
    body = r.json()
    text = (
        body["translations"][0]["text"]
        if r.status_code == 200
        else f"HTTP {r.status_code}: {body}"
    )
    return {**seg, "target": dst, "latency_s": round(dt, 3), "translation": text}


def stats(xs):
    xs = sorted(xs)
    return {
        "n": len(xs),
        "p50": round(statistics.median(xs), 2),
        "p95": round(xs[int(0.95 * (len(xs) - 1))], 2),
        "max": round(xs[-1], 2),
    }


async def main():
    base, events, out, mode = sys.argv[1:5]
    segs = segments(events)
    async with httpx.AsyncClient(timeout=120) as client:
        await translate(client, base, segs[0])  # warm-up
        if mode == "alone":
            rows = [await translate(client, base, s) for s in segs]
        else:
            n = int(sys.argv[5])
            start = time.monotonic()

            async def source(i):
                res = []
                for s in segs:
                    await asyncio.sleep(max(0.0, start + s["t"] - time.monotonic()))
                    res.append({**await translate(client, base, s), "source": i})
                return res

            rows = [
                r
                for rs in await asyncio.gather(*(source(i) for i in range(n)))
                for r in rs
            ]
    summary = {
        "mode": mode,
        "all": stats([r["latency_s"] for r in rows]),
        "en_to_fr": stats([r["latency_s"] for r in rows if r["lang"] == "en"]),
        "fr_to_en": stats([r["latency_s"] for r in rows if r["lang"] == "fr"]),
    }
    json.dump(
        {"summary": summary, "rows": rows}, open(out, "w"), ensure_ascii=False, indent=1
    )
    print(json.dumps(summary))


if __name__ == "__main__":
    asyncio.run(main())
