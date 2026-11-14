#!/bin/sh
# measure_pid.sh <label> <pid> -- measure.sh (~/perf/2026-11-14-svs-slow) for an explicit pid on port 3492.
D=$HOME/bench-scratch/aer5670/out; mkdir -p $D; L=$1; PID=$2; T=$HOME/perf/2026-11-14-svs-slow
while [ "$(ps -o etimes= -p $PID | tr -d ' ')" -lt 75 ]; do sleep 3; done
echo "== $L: pid $PID up $(ps -o etimes= -p $PID | tr -d ' ')s $(date -u +%FT%TZ)"
for k in FPLCOUNT FPLSTATE FPLACTLEG WPNAME WPDIS IAS; do printf "%s=%s " $k "$($HOME/pyefis-venv/bin/fixgwc --host 127.0.0.1 --port 3492 --execute "read $k" 2>&1 | tail -1)"; done; echo
pidstat -t -p $PID 10 1 | awk '/Average/ && $4=="'$PID'" {print "unprofiled GUI thread CPU: " $9 "%"} /Average/ && $3=="'$PID'" {print "unprofiled process CPU:    " $9 "%"}'
sudo $HOME/pyefis-venv/bin/py-spy record --pid $PID --duration 30 --rate 250 --idle --format speedscope -o /tmp/aer5670_$L.json >/dev/null 2>&1
sudo chown pyefis:pyefis /tmp/aer5670_$L.json; mv /tmp/aer5670_$L.json $D/$L.json
python3 $T/timeline.py $D/$L.json 2>/dev/null | grep -E "notify|ai_paint|map_paint|fpl_paint|idle_or_qt|longest"
