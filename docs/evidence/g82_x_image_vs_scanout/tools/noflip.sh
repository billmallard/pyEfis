#!/bin/sh
# restart the isolated pyEfis, put the 4x4 clip window on top, then run with both recorders
cd ~/bench-scratch/aer5478/g79
pkill -f "aer5478/stack/pcfg"; sleep 3
( cd .. && sh stack.sh up >/dev/null ); sleep 14
DISPLAY=:0 QT_QPA_PLATFORM=xcb setsid -f ~/pyefis-venv/bin/python tiny.py >tiny.out 2>&1 </dev/null; sleep 3
export DISPLAY=:0
for k in 1 2 3; do xdotool mousemove 1344 12 click 1; sleep 2; xdotool mousemove 1900 600; sleep 1
  grep fp_targets /tmp/g79_probe.log | tail -1 | grep -q "\"page\": \"fpl\"" && break; done
KMS=1 sh run.sh $1 12
pkill -f "g79/tiny.py\|python tiny.py"
