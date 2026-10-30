"""Step lag relative to the first Step of each session (step_idx is a server-wide counter).

Usage: python kyutai_steplag.py DIR [DIR ...]
lag = (_t - _t_first) - (step_idx - step_idx_first) * 0.08, for Steps before the audio ends.
A rising value means the server falls behind real time.
"""

import glob
import json
import statistics
import sys

for d in sys.argv[1:]:
    with open(f"{d}/summary.json", encoding="utf-8") as f:
        summ = json.load(f)
    for path in sorted(glob.glob(f"{d}/rt_events_src*.jsonl")):
        idx = int(path.rsplit("src", 1)[1].split(".")[0])
        audio_end = summ[idx]["audio_s"]
        with open(path, encoding="utf-8") as f:
            st = [e for e in map(json.loads, f) if e.get("type") == "Step"]
        st = [e for e in st if e["_t"] <= audio_end]
        t0, i0 = st[0]["_t"], st[0]["step_idx"]
        lag = sorted((e["_t"] - t0) - (e["step_idx"] - i0) * 0.08 for e in st)
        print(
            json.dumps(
                {
                    "dir": d,
                    "src": idx,
                    "n": len(lag),
                    "p50": round(statistics.median(lag), 3),
                    "p95": round(lag[int(0.95 * (len(lag) - 1))], 3),
                    "max": round(lag[-1], 3),
                    "min": round(lag[0], 3),
                }
            )
        )
