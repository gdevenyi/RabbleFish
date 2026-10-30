#!/usr/bin/env bash
# Realtime matrix: name device batching diar nsrc
set -u
B=/var/tmp/claude/claude-1000/-home-gdevenyi-projects-live-transcribe-translate/b77459c2-530f-47aa-8ec0-57ff5f4638fa/scratchpad/bench
A=$B/audio; R=$B/results/rt_matrix; mkdir -p $R
one() {
  local name=$1 dev=$2 batch=$3 diar=$4 n=$5
  local bin=$B/cpu/nemo-speech-0.2.0-linux-x86_64-cpu/bin/nemo-speech
  [ "$dev" = vulkan ] && bin=$B/vulkan/nemo-speech-0.2.0-linux-x86_64-vulkan/bin/nemo-speech
  mkdir -p $R/$name
  $bin serve --asr-model $B/models/nemotron-3.5-asr-streaming-0.6b.q8_0.gguf --diar-model $B/models/Nemotron-3-Diarization.q8_0.gguf \
    --device $dev --port 8091 --no-ui --asr.endpointing.enable=true --asr.batching.enabled=$batch > $R/$name/server.log 2>&1 &
  local pid=$!
  timeout 300 bash -c 'until curl -sf http://127.0.0.1:8091/ready >/dev/null; do sleep 1; done' || { echo "$name: server not ready" | tee -a $R/summary.txt; kill $pid; return; }
  local files=$(for i in $(seq $n); do echo $A/en_fr.wav; done)
  DIAR=$diar $B/.venv/bin/python $B/rt_client.py ws://127.0.0.1:8091/v1/audio/transcriptions/realtime $R/$name $files > $R/$name/summary.json 2> $R/$name/client.err
  local alive=yes; kill -0 $pid 2>/dev/null || alive="NO (crashed)"
  echo "### $name dev=$dev batching=$batch diar=$diar sources=$n server_alive=$alive" | tee -a $R/summary.txt
  python3 -c "
import json,sys
try: r=json.load(open('$R/$name/summary.json'))
except Exception as e: print('  client failed:', open('$R/$name/client.err').read().strip().splitlines()[-1][:200]); sys.exit()
for s in r: print('  ', {k:s[k] for k in ['source','finals','words','first_partial_s','word_latency_p50_s','word_latency_p95_s','word_latency_max_s','speakers_seen']}, 'errors:', [e.get('_client') or e.get('message') for e in s['errors']])" | tee -a $R/summary.txt
  grep -m3 -E 'ASSERT|error|abort' $R/$name/server.log | sed 's/^/   server: /' | tee -a $R/summary.txt
  kill $pid 2>/dev/null; wait $pid 2>/dev/null; sleep 2
}


one vk_b0_d1_n3 vulkan false 1 3




echo done | tee -a $R/summary.txt
