#!/bin/bash
# usage: run_nemo.sh NAME WAV [WAV...]  -> results/nemo/NAME/
cd /var/tmp/ltt-bench
name=$1; shift
out=results/nemo/$name; mkdir -p $out
pid=$(cat nemo.pid)
( while true; do echo "$(date +%s) $(nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader,nounits) $(ps -o rss= -p $pid)"; sleep 1; done ) > $out/mon.txt &
mon=$!
URL=ws://127.0.0.1:8091/v1/audio/transcriptions/realtime
LANG_CODE=${LANG_CODE-auto} DIAR=${DIAR-1} .venv/bin/python -I rt_client.py $URL $out "$@" > $out/summary.json 2> $out/client.err
kill $mon
awk "{split(\$2,a,\",\"); if(a[1]>v)v=a[1]; if(\$4>r)r=\$4; if(a[2]>u)u=a[2]} END{print \"peak VRAM MiB\",v,\"peak RSS KiB\",r,\"peak util\",u}" FS=" " $out/mon.txt
