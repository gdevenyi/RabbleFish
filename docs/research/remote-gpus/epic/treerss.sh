#!/bin/bash
# sum RSS (KiB) of PID and all descendants
p=$1; all=$p; q=$p
while [ -n "$q" ]; do q=$(pgrep -d" " -P "$(echo $q | tr " " ",")"); all="$all $q"; done
ps -o rss= -p $(echo $all | tr " " ",") | awk "{s+=\$1} END{print s}"
