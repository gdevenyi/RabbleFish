#!/bin/bash
# usage: nemo_n.sh NAME N WAV  -> N concurrent copies of WAV
cd /var/tmp/ltt-bench
export MONPID=$(cat nemo.pid) LANG_CODE=${LANG_CODE-auto} DIAR=${DIAR-1}
U=ws://127.0.0.1:8091/v1/audio/transcriptions/realtime
w=""; for i in $(seq $2); do w="$w $3"; done
./run_bench.sh results/nemo/$1 .venv/bin/python -I rt_client.py $U results/nemo/$1 $w
.venv/bin/python -I analyze_nemo.py results/nemo/$1
.venv/bin/python -I -c "import json;[print({k:v for k,v in d.items() if k not in (\"wav\",\"source\")}) for d in json.load(open(\"results/nemo/$1/summary.json\"))]"
cat results/nemo/$1/client.err
