#!/bin/bash
# usage: vllm_n.sh MODELDIR NAME N WAV TIMINGREF  -> N concurrent copies of WAV, results/MODELDIR/NAME
cd /var/tmp/ltt-bench
export MONPID=$(cat vllm.pid)
M=$(curl -s http://127.0.0.1:8000/v1/models | .venv/bin/python -I -c "import json,sys;print(json.load(sys.stdin)[\"data\"][0][\"id\"])")
w=""; for i in $(seq $3); do w="$w $4"; done
./run_bench.sh results/$1/$2 .venv/bin/python -I vllm_rt_client.py ws://127.0.0.1:8000/v1/realtime $M results/$1/$2 $5 $w
.venv/bin/python -I -c "import json;[print(json.dumps({k:v for k,v in d.items() if k not in (\"wav\",\"language_tag_times\")},ensure_ascii=False)) for d in json.load(open(\"results/$1/$2/summary.json\"))]"
tail -5 results/$1/$2/client.err
