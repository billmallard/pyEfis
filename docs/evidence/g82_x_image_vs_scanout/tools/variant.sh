#!/bin/sh
# variant.sh <label> [ENV=V ...]: restart the isolated pyEfis with ENV, open the FPL tab, run 12 cycles
L=$1; shift; cd ~/bench-scratch/aer5478
pkill -f "aer5478/stack/pcfg"; sleep 3
sh stack.sh up "$@" >/dev/null; sleep 14
export DISPLAY=:0
for k in 1 2 3; do
  xdotool mousemove 1344 12 click 1; sleep 2; xdotool mousemove 1900 600; sleep 1
  grep fp_targets /tmp/g79_probe.log | tail -1 | grep -q '"page": "fpl"' && break
done
grep -q fp_targets /tmp/g79_probe.log || { echo "FPL tab not open"; exit 3; }
cd g79 && sh run.sh $L 12
