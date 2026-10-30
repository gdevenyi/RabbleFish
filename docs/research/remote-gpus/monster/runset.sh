#!/bin/bash
# usage: runset.sh DEVICE NAME:WAV[,WAV...] ...   -> runs each with up to 3 attempts; prints summary lines
B=/var/tmp/ltt-bench; DEV=$1; shift; cd $B
for spec in "$@"; do
  NAME=${spec%%:*}; WAVS=$(echo ${spec#*:} | tr ',' ' ')
  for att in 1 2 3; do
    OUT=results/$DEV/$NAME
    [ -d $OUT ] && mv $OUT results/$DEV/discarded-$NAME-$(date +%s)
    echo "=== $DEV $NAME attempt $att"
    ./bench.sh $B/$OUT 1 $WAVS; rc=$?
    [ $rc -eq 2 ] && { echo "ABORT: GPU not idle"; exit 2; }
    [ $rc -eq 0 ] && break
  done
  .venv/bin/python -I analyze.py $OUT > $OUT/analysis.json
  cat $OUT/analysis.json
  .venv/bin/python -I -c "import json,sys;[print({k:r[k] for k in ('finals','words','first_partial_s','word_latency_p50_s','word_latency_p95_s','word_latency_max_s','speakers_seen','languages_seen','errors')}) for r in json.load(open(sys.argv[1]))]" $OUT/summary.json
  case $NAME in
    wer_en) .venv/bin/python -I wer.py refs/en_ref.txt $OUT/hyp_src0.txt | tee $OUT/wer.txt;;
    wer_fr) .venv/bin/python -I wer.py refs/fr_ref.txt $OUT/hyp_src0.txt | tee $OUT/wer.txt;;
  esac
done
echo ALL_DONE
