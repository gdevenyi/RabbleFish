#!/bin/bash
# usage: serve.sh BIN DEVICE LOG
B=/var/tmp/ltt-bench
BIN=$1; DEV=$2; LOG=$3; shift 3
nohup "$BIN" serve --asr-model $B/models/nemotron-3.5-asr-streaming-0.6b.q8_0.gguf \
  --diar-model $B/models/Nemotron-3-Diarization.q8_0.gguf --device "$DEV" \
  --host 127.0.0.1 --port 8091 --no-ui --asr.endpointing.enable=true --asr.batching.enabled=false "$@" \
  > "$LOG" 2>&1 < /dev/null &
echo $! > $B/server.pid
for i in $(seq 1 120); do curl -sf http://127.0.0.1:8091/ready >/dev/null && { echo READY after $i s; exit 0; }; sleep 1; done
echo NOT READY; tail -30 "$LOG"; exit 1
