import json, glob, os, sys
B = sys.argv[1]
for dev in ("vulkan", "cuda"):
    for d in sorted(glob.glob(f"{B}/results/{dev}/*")):
        if not os.path.exists(f"{d}/analysis.json") or os.path.getsize(f"{d}/analysis.json") < 5: continue
        a = json.load(open(f"{d}/analysis.json")); s = json.load(open(f"{d}/summary.json"))
        mp = open(f"{d}/mem_peak.txt").read().split()
        def rng(v): return f"{min(v)}-{max(v)}" if min(v) != max(v) else f"{v[0]}"
        print(dev, os.path.basename(d), "n=", len(a),
              "plag50", rng([x["partial_lag_p50"] for x in a]), "plag95", rng([x["partial_lag_p95"] for x in a]),
              "plagmax", max(x["partial_lag_max"] for x in a),
              "fin50", rng([x["uttend_final_p50"] for x in a]), "finmax", max(x["uttend_final_max"] for x in a),
              "wl50", rng([x["word_latency_p50_s"] for x in s]), "wl95", rng([x["word_latency_p95_s"] for x in s]), "wlmax", max(x["word_latency_max_s"] for x in s),
              "finals", rng([x["finals"] for x in s]), "words", rng([x["words"] for x in s]),
              "spk", rng([len(x["speakers_seen"]) for x in s]), "VRAM", mp[3], "util", mp[8], "RSS", mp[12])
