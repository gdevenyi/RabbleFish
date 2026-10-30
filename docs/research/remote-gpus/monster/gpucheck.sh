#!/bin/bash
# usage: gpucheck.sh LABEL [SERVER_PID]  -> waits up to 10 min for idle GPU (only SERVER_PID allowed); exit 1 if not idle
SP=${2:-none}
for i in $(seq 1 60); do
  APPS=$(nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader)
  G=$(nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader,nounits | tr -d ' ')
  UT=${G%,*}; MU=${G#*,}
  OWN=$(echo "$APPS" | awk -F', ' -v p=$SP '$1==p{gsub(/ MiB/,"",$3); print $3}'); OWN=${OWN:-0}
  FOREIGN=$(echo "$APPS" | awk -F', ' -v p=$SP 'NF>1 && $1!=p')
  LOAD=$(cut -d' ' -f1 /proc/loadavg)
  LINE="$1 $(date +%T) apps=[$(echo $APPS | tr '\n' ';')] util=${UT}% mem=${MU}MiB own=${OWN}MiB load1=$LOAD"
  if [ -z "$FOREIGN" ] && [ "$UT" -le 5 ] && [ $((MU-OWN)) -le 100 ] && awk "BEGIN{exit !($LOAD<4)}"; then echo "OK $LINE"; exit 0; fi
  echo "BUSY $LINE foreign=[$FOREIGN]" >&2
  sleep 10
done
echo "FAIL $LINE foreign=[$FOREIGN]"; exit 1
