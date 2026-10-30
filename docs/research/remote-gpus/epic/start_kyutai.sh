#!/bin/bash
# usage: start_kyutai.sh LOGFILE CONFIG
cd /var/tmp/ltt-bench/kyutai
mkdir -p logs
nohup ./install/bin/moshi-server worker --config "$2" --addr 127.0.0.1 --port 8080 > "$1" 2>&1 &
echo $! > ../kyutai.pid
for i in $(seq 1 600); do ss -ltn | grep -q "127.0.0.1:8080 " && break; kill -0 $(cat ../kyutai.pid) 2>/dev/null || { echo DIED; break; }; sleep 1; done
sleep 2; echo pid $(cat ../kyutai.pid)
