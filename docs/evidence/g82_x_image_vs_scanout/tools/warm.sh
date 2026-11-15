#!/bin/sh
# warm reruns on the already-running isolated pyEfis: flips allowed, then flips prevented
cd ~/bench-scratch/aer5478/g79; export DISPLAY=:0
grep fp_targets /tmp/g79_probe.log | tail -1 | grep -q "\"page\": \"fpl\"" || { echo "not on fpl"; exit 3; }
KMS=1 sh run.sh base2 12
QT_QPA_PLATFORM=xcb setsid -f ~/pyefis-venv/bin/python tiny.py >tiny.out 2>&1 </dev/null; sleep 3
KMS=1 sh run.sh noflip2 12
pkill -f "[p]ython tiny.py"
python3 tab.py base2 noflip2; echo WARM-DONE
