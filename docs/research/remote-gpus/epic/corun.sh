#!/bin/bash
# usage: corun.sh OUTDIR MODEL  -> NeMo 1 source + vLLM 1 source of en_fr.wav at once
cd /var/tmp/ltt-bench; o=$1; mkdir -p $o/nemo $o/vllm
LANG_CODE=auto DIAR=1 .venv/bin/python -I rt_client.py ws://127.0.0.1:8091/v1/audio/transcriptions/realtime $o/nemo audio/en_fr.wav > $o/nemo/summary.json 2> $o/nemo/client.err &
.venv/bin/python -I vllm_rt_client.py ws://127.0.0.1:8000/v1/realtime $2 $o/vllm results/nemo/n1/rt_events_src0.jsonl audio/en_fr.wav > $o/vllm/summary.json 2> $o/vllm/client.err
wait
echo "{}"
