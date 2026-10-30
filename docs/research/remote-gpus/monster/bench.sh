#!/bin/bash
# usage: bench.sh OUTDIR DIAR WAV...   (idle check before/after; samples VRAM, util, RSS, compute apps every 1 s)
B=/var/tmp/ltt-bench
OUT=$1; DIAR=$2; shift 2
mkdir -p "$OUT"
PID=$(cat $B/server.pid)
$B/gpucheck.sh pre $PID > "$OUT/gpucheck.txt" || { cat "$OUT/gpucheck.txt"; exit 2; }
( while true; do echo "$(date +%s) $(nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader,nounits | tr -d ' ') $(ps -o rss= -p $PID) apps=$(nvidia-smi --query-compute-apps=pid --format=csv,noheader | tr '\n' ';')"; sleep 1; done ) > "$OUT/mem.log" &
MP=$!
DIAR=$DIAR LANG_CODE=auto $B/.venv/bin/python -I $B/rt_client.py ws://127.0.0.1:8091/v1/audio/transcriptions/realtime "$OUT" "$@" > "$OUT/summary.json" 2> "$OUT/client.err"
kill $MP
FOREIGN=$(grep -o 'apps=.*' "$OUT/mem.log" | tr ';=' '\n\n' | grep -E '^[0-9]+$' | grep -vx "$PID" | sort -u | tr '\n' ' ')
sleep 2
$B/gpucheck.sh post $PID >> "$OUT/gpucheck.txt" 2>/dev/null; POST=$?
echo "foreign_pids_during_run=[$FOREIGN]" >> "$OUT/gpucheck.txt"
awk '{split($2,a,","); if(a[1]>v)v=a[1]; if(a[2]>u)u=a[2]; if($3>r)r=$3} END{print "peak VRAM MiB",v," peak GPU util %",u," peak RSS MiB",int(r/1024)}' "$OUT/mem.log" > "$OUT/mem_peak.txt"
cat "$OUT/gpucheck.txt" "$OUT/mem_peak.txt"
if [ -n "$FOREIGN" ] || [ $POST -ne 0 ]; then echo RUN_INVALID; exit 3; fi
echo RUN_VALID
