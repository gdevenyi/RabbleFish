#!/bin/bash
# usage: kyutai_n.sh OUTNAME N WAV TIMINGREF -> results/OUTNAME
cd /var/tmp/ltt-bench
export MONPID=$(cat kyutai.pid)
w=""; for i in $(seq $2); do w="$w $3"; done
./run_bench.sh results/$1 .venv/bin/python -I kyutai_rt_client.py ws://127.0.0.1:8080/api/asr-streaming results/$1 $4 $w
.venv/bin/python -I -c "import json;[print(json.dumps({k:v for k,v in d.items() if k not in (\"wav\",\"text_after_60_5s_head\")},ensure_ascii=False)) for d in json.load(open(\"results/$1/summary.json\"))]"
tail -5 results/$1/client.err
