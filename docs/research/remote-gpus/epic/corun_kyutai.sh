#!/bin/bash
# usage: corun_kyutai.sh OUTDIR -> NeMo 1 source + Kyutai 1 source of en_fr.wav at once
cd /var/tmp/ltt-bench; o=$1; mkdir -p $o/nemo $o/kyutai
LANG_CODE=auto DIAR=1 .venv/bin/python -I rt_client.py ws://127.0.0.1:8091/v1/audio/transcriptions/realtime $o/nemo audio/en_fr.wav > $o/nemo/summary.json 2> $o/nemo/client.err &
.venv/bin/python -I kyutai_rt_client.py ws://127.0.0.1:8080/api/asr-streaming $o/kyutai results/nemo/n1/rt_events_src0.jsonl audio/en_fr.wav > $o/kyutai/summary.json 2> $o/kyutai/client.err
wait
echo "{}"
