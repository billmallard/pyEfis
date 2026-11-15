#!/bin/sh
# AER-809: keep fp8_s2.py waiting for the sim session; never relaunch once it armed or finished.
D=$HOME/bench-scratch/aer809; cd $D || exit 0
[ -e s2/ARMED ] || [ -e s2/DONE ] || [ -e s2/NOT_FLOWN ] && exit 0
pgrep -f "bin/python fp8_s2[.]py" >/dev/null && exit 0
mkdir -p s2; setsid nohup $HOME/pyefis-venv/bin/python fp8_s2.py >> s2/run.out 2>&1 < /dev/null &
