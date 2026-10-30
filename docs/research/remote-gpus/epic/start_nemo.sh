#!/bin/bash
# usage: start_nemo.sh LOGFILE
cd /var/tmp/ltt-bench
B=nemo-cuda/x/nemo-speech-0.2.0-linux-x86_64-cuda
nohup $B/bin/nemo-speech serve --asr-model models/nemotron-3.5-asr-streaming-0.6b.q8_0.gguf --diar-model models/Nemotron-3-Diarization.q8_0.gguf --device cuda --host 127.0.0.1 --port 8091 --no-ui --threads ${THREADS:-4} --asr.endpointing.enable=true --asr.batching.enabled=false > "$1" 2>&1 &
echo $! > nemo.pid
for i in $(seq 1 120); do curl -sf http://127.0.0.1:8091/ready && break; sleep 1; done
echo; echo pid $(cat nemo.pid)
