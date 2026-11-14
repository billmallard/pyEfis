#!/bin/sh
# ab.sh <label-suffix> <variant>... : for each variant, start pyEfis on the stack, measure, stop.
cd ~/bench-scratch/aer5670
[ -f fly.pid ] && kill -0 $(cat fly.pid) 2>/dev/null || { NFX_PORT=3492 setsid ~/pyefis-venv/bin/python fly.py 3000 >fly.out 2>&1 </dev/null & sleep 5; }
tail -1 fly.log
SUF=$1; shift
for v in "$@"; do
  sh stack.sh efis-up $v; P=$(cat stack/efis.pid)
  sh measure_pid.sh ${v}_$SUF $P
  grep -c Traceback stack/efis_$v.out | sed 's/^/tracebacks in efis log: /'
  sh stack.sh efis-down
done
