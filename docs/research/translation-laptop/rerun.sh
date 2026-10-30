#!/usr/bin/env bash
# Translation benchmark, all scenarios, one at a time, each started only when the
# machine is quiet (1-min load < 1.0). Results in rerun/<scenario>/.
set -u
B=/var/tmp/claude/claude-1000/-home-gdevenyi-projects-live-transcribe-translate/b77459c2-530f-47aa-8ec0-57ff5f4638fa/scratchpad/bench
N=/var/tmp/claude/claude-1000/-home-gdevenyi-projects-live-transcribe-translate/nmt
K=/var/tmp/claude/claude-1000/-home-gdevenyi-projects-live-transcribe-translate/remote-kit
A=$K/audio
VK=$B/vulkan/nemo-speech-0.2.0-linux-x86_64-vulkan/bin/nemo-speech
CPU=$B/cpu/nemo-speech-0.2.0-linux-x86_64-cpu/bin/nemo-speech
ASR="--asr-model $B/models/nemotron-3.5-asr-streaming-0.6b.q8_0.gguf --diar-model $B/models/Nemotron-3-Diarization.q8_0.gguf --asr.endpointing.enable=true --asr.batching.enabled=false"
NMT="--nmt.model.path $N/riva-translate-4b-instruct-v2.q8_0.gguf"
R=$N/rerun
PY=$N/.venv-bench/bin/python
mkdir -p $R
log() { echo "[$(date +%T)] $*" | tee -a $R/rerun.log; }
load1() { cut -d' ' -f1 /proc/loadavg; }

busy() { vmstat 2 2 | tail -1 | awk '{print $13 + $14}'; }  # user + system CPU %
wait_quiet() {  # CPU user+system < 10 %, checked for up to 20 min
  for _ in $(seq 240); do
    [ "$(busy)" -lt 10 ] && return 0
    sleep 3
  done
  log "WARNING: CPU did not become quiet (busy $(busy) %)"
}

start_server() {  # name port args...
  local name=$1 port=$2; shift 2
  "$@" --host 127.0.0.1 --port "$port" --no-ui --threads 8 > "$R/server_$name.log" 2>&1 &
  echo $! > "$R/server_$name.pid"
  timeout 300 bash -c "until curl -sf http://127.0.0.1:$port/ready >/dev/null; do sleep 2; done"
}
stop_server() { kill "$(cat "$R/server_$1.pid")" 2>/dev/null; sleep 3; }

asr_stats() {
  $PY - "$1" <<'EOF'
import glob, json, statistics, sys
for f in sorted(glob.glob(sys.argv[1] + "/rt_events_src*.jsonl")):
    evs = [json.loads(l) for l in open(f)]
    pl = sorted(e["_t"] - e["audio_processed"] for e in evs if e.get("type", "").endswith("delta") and e.get("_t"))
    fin = [e for e in evs if e.get("type", "").endswith("completed") and e.get("words")]
    tail = sorted(e["_t"] - e["words"][-1]["end"] for e in fin)
    print(f"  {f[-9:]} finals={len(fin)} partial lag p50={statistics.median(pl):.2f} p95={pl[int(.95*(len(pl)-1))]:.2f} max={pl[-1]:.2f} | utt end->final p50={statistics.median(tail):.2f} max={tail[-1]:.2f}")
EOF
}

run() {  # name asr_url nmt_url n_sources(0 = no ASR) mode(alone|live|none)
  local name=$1 asr=$2 nmt=$3 n=$4 mode=$5 d=$R/$1
  mkdir -p "$d"; wait_quiet
  log "RUN $name: before: cpu busy $(busy) %, loadavg $(cut -d" " -f1-3 /proc/loadavg)"
  local cpid=""
  if [ "$n" -gt 0 ]; then
    $PY $K/rt_client.py "$asr/v1/audio/transcriptions/realtime" "$d" $(for i in $(seq "$n"); do echo $A/en_fr.wav; done) > "$d/summary.json" 2> "$d/client.err" &
    cpid=$!; sleep 0.3
  fi
  case $mode in
    alone) $PY $N/nmt_bench.py "$nmt" $N/segments_events.jsonl "$d/nmt.json" alone | tee -a $R/rerun.log ;;
    live) $PY $N/nmt_bench.py "$nmt" $N/segments_events.jsonl "$d/nmt.json" live "$n" | tee -a $R/rerun.log ;;
  esac
  [ -n "$cpid" ] && wait $cpid
  log "RUN $name: after: cpu busy $(busy) %, loadavg $(cut -d" " -f1-3 /proc/loadavg)"
  [ "$n" -gt 0 ] && asr_stats "$d" | tee -a $R/rerun.log
}

H=http://127.0.0.1; W=ws://127.0.0.1
log "== A: one Vulkan server with ASR + diarization + NMT"
start_server combined 8093 $VK serve $ASR $NMT --device vulkan
run A_alone    - $H:8093 0 alone
run A_asr3_ctl $W:8093 - 3 none
run A_live1    $W:8093 $H:8093 1 live
run A_live2    $W:8093 $H:8093 2 live
run A_live3    $W:8093 $H:8093 3 live
stop_server combined

log "== B: ASR + diarization on a Vulkan server, NMT on a CPU-build server"
start_server asr 8093 $VK serve $ASR --device vulkan
start_server nmtcpu 8094 $CPU serve $NMT --device cpu
run B_alone    - $H:8094 0 alone
run B_live1    $W:8093 $H:8094 1 live
run B_live2    $W:8093 $H:8094 2 live
run B_live3    $W:8093 $H:8094 3 live
stop_server asr; stop_server nmtcpu
log "== done"
