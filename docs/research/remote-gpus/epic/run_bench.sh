#!/bin/bash
# usage: run_bench.sh OUTDIR CLIENTCMD...   (monitors GPU apps each second; pre/post checks)
cd /var/tmp/ltt-bench
out=$1; shift; mkdir -p $out
./gpucheck.sh pre > $out/gpucheck.txt
( while true; do echo "$(date +%s)|$(nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader,nounits)|$(nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader | tr "\n" ";")|${MONPID:+$(./treerss.sh $MONPID)}"; sleep 1; done ) > $out/mon.txt &
mon=$!
"$@" > $out/summary.json 2> $out/client.err
kill $mon
./gpucheck.sh post >> $out/gpucheck.txt
cat $out/gpucheck.txt
echo "distinct GPU app sets during run:"; cut -d"|" -f3 $out/mon.txt | sed -E "s/, [0-9]+ MiB//g" | sort | uniq -c
awk -F"|" "{split(\$2,a,\", \"); if(a[1]+0>v)v=a[1]+0; if(a[2]+0>u)u=a[2]+0; if(\$4+0>r)r=\$4+0} END{print \"peak VRAM MiB\",v,\"peak util %\",u,\"peak RSS KiB\",r}" $out/mon.txt
