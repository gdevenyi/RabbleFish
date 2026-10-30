"""Partial lag and utterance-end->final from rt_events_src*.jsonl. Usage: analyze_nemo.py DIR"""
import glob, json, statistics, sys

def q(v):
    if not v: return None
    v = sorted(v)
    return {"p50": round(statistics.median(v), 2), "p95": round(v[int(0.95*(len(v)-1))], 2), "max": round(v[-1], 2), "n": len(v)}

for f in sorted(glob.glob(sys.argv[1] + "/rt_events_src*.jsonl")):
    ev = [json.loads(l) for l in open(f)]
    lag = [e["_t"] - e["audio_processed"] for e in ev if e.get("type","").endswith(".delta") and e.get("_t") is not None and "audio_processed" in e]
    fin = [e["_t"] - e["words"][-1]["end"] for e in ev if e.get("type","").endswith(".completed") and e.get("words")]
    text = " ".join(w["word"] for e in ev if e.get("type","").endswith(".completed") for w in (e.get("words") or []))
    print(json.dumps({"file": f.rsplit("/",1)[-1], "partial_lag": q(lag), "utt_end_to_final": q(fin)}))
    open(f.replace("rt_events_", "hyp_").replace(".jsonl", ".txt"), "w").write(text + "\n")
