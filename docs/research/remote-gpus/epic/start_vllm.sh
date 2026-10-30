#!/bin/bash
# usage: start_vllm.sh LOGFILE vllm-serve-args...
cd /var/tmp/ltt-bench
log=$1; shift
VLLM_DISABLE_COMPILE_CACHE=${VLLM_DISABLE_COMPILE_CACHE-1} nohup .venv-vllm/bin/vllm serve "$@" --host 127.0.0.1 --port 8000 > $log 2>&1 &
echo $! > vllm.pid
for i in $(seq 1 900); do curl -sf http://127.0.0.1:8000/health >/dev/null && break; kill -0 $(cat vllm.pid) 2>/dev/null || { echo DIED; break; }; sleep 2; done
curl -s http://127.0.0.1:8000/v1/models; echo; echo pid $(cat vllm.pid)
