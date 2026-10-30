"""usage: analyze.py RUNDIR [WERREF]  -> per-source lag stats; writes hyp_src<i>.txt"""
import glob, json, statistics, sys, re

def pct(q, p):
    q = sorted(q)
    return round(q[int(p * (len(q) - 1))], 2) if q else None

d = sys.argv[1]
rows = []
for f in sorted(glob.glob(f"{d}/rt_events_src*.jsonl")):
    i = re.search(r"src(\d+)", f).group(1)
    evs = [json.loads(l) for l in open(f)]
    plag, fin, words, langkeys = [], [], [], set()
    for e in evs:
        t = e.get("type", "")
        if e.get("_t") is None:
            continue
        if "language" in e and t != "session.updated" or any("language" in w for w in (e.get("words") or []) if isinstance(w, dict)):
            langkeys.add(t)
        if t.endswith(".delta") and "audio_processed" in e:
            plag.append(e["_t"] - e["audio_processed"])
        if t.endswith(".completed"):
            ws = e.get("words") or []
            if ws:
                fin.append(e["_t"] - ws[-1]["end"])
            words += [w["word"] for w in ws]
    open(f"{d}/hyp_src{i}.txt", "w").write(" ".join(words) + "\n")
    rows.append(dict(src=int(i), partial_lag_p50=pct(plag, .5), partial_lag_p95=pct(plag, .95),
                     partial_lag_max=pct(plag, 1), uttend_final_p50=pct(fin, .5), uttend_final_max=pct(fin, 1),
                     n_deltas=len(plag), n_finals_with_words=len(fin), lang_field_in=sorted(langkeys)))
print(json.dumps(rows))
