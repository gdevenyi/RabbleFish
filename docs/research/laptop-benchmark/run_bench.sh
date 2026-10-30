#!/usr/bin/env bash
# Laptop benchmark for the wayfinder ticket
# "Measure streaming ASR and diarization speed on the laptop".
# Runs NVIDIA NeMo-Speech.cpp v0.2.0 prebuilt binaries (SHA-256 checked against
# the release SHA256 files) on local files only. No server, no network.
set -u
B=/var/tmp/claude/claude-1000/-home-gdevenyi-projects-live-transcribe-translate/b77459c2-530f-47aa-8ec0-57ff5f4638fa/scratchpad/bench
CPU=$B/cpu/nemo-speech-0.2.0-linux-x86_64-cpu/bin/nemo-speech
VK=$B/vulkan/nemo-speech-0.2.0-linux-x86_64-vulkan/bin/nemo-speech
ASR=$B/models/nemotron-3.5-asr-streaming-0.6b.q8_0.gguf
DIAR=$B/models/Nemotron-3-Diarization.q8_0.gguf
A=$B/audio
OUT=$B/results
mkdir -p "$OUT"

run() { # name, command...
  local name=$1; shift
  echo "=== $name" | tee -a "$OUT/summary.log"
  # /usr/bin/time is not installed; measure peak RSS of the child with Python.
  python3 -c 'import resource,subprocess,sys,time
t=time.monotonic(); rc=subprocess.call(sys.argv[3:], stdout=open(sys.argv[1],"w"), stderr=open(sys.argv[2],"w"))
print(f"exit={rc} wall_s={time.monotonic()-t:.1f} maxrss_kb={resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss}")' \
    "$OUT/$name.out" "$OUT/$name.err" "$@" | tee -a "$OUT/summary.log"
}

# 0. Help text for the commands used later (for the combined live run).
"$CPU" help transcribe > "$OUT/help_transcribe.txt" 2>&1
"$CPU" help serve > "$OUT/help_serve.txt" 2>&1
"$CPU" help diarize > "$OUT/help_diarize.txt" 2>&1

# 1. Streaming ASR, 1 and 2 concurrent streams (= 1 and 2 sources), CPU then Vulkan.
run asr_stream_cpu    "$CPU" bench asr "$A/en_fr.wav" -m "$ASR" --mode stream -c 1,2 -n 1 --device cpu    --trace "$OUT/asr_cpu_trace.jsonl" --save "$OUT/asr_cpu_text" --json
run asr_stream_vulkan "$VK"  bench asr "$A/en_fr.wav" -m "$ASR" --mode stream -c 1,2 -n 1 --device vulkan --trace "$OUT/asr_vk_trace.jsonl"  --save "$OUT/asr_vk_text"  --json

# 2. Streaming diarization, 1 and 2 concurrent streams, CPU then Vulkan.
run diar_stream_cpu    "$CPU" bench diarize "$A/en_fr.wav" -m "$DIAR" --preset streaming -c 1,2 -n 1 --device cpu    --save "$OUT/diar_cpu_out" --json
run diar_stream_vulkan "$VK"  bench diarize "$A/en_fr.wav" -m "$DIAR" --preset streaming -c 1,2 -n 1 --device vulkan --save "$OUT/diar_vk_out"  --json

# 3. Sustained load: 10 minutes of audio, streaming ASR, 1 stream, on the faster device later chosen by hand.
run asr_stream_cpu_10min    "$CPU" bench asr "$A/long_10min.wav" -m "$ASR" --mode stream -c 1 -n 1 --device cpu    --json
run asr_stream_vulkan_10min "$VK"  bench asr "$A/long_10min.wav" -m "$ASR" --mode stream -c 1 -n 1 --device vulkan --json

echo "done; results in $OUT" | tee -a "$OUT/summary.log"
