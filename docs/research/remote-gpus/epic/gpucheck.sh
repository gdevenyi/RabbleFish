#!/bin/bash
# usage: gpucheck.sh LABEL ; prints GPU apps, util, mem, load, docker containers
echo "== $1 $(date -Is)"
echo "apps: $(nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader | tr "\n" ";")"
echo "gpu: $(nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader)"
echo "uptime: $(uptime)"
echo "docker: $(docker ps --format "{{.Names}} {{.Image}}" | tr "\n" ";")"
