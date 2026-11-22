#!/bin/bash
# AER-6288 rehearsal: bring the private stack up with no X-Plane, run seq.py
# in --watch mode (log and grab once a second, press nothing), feed the
# scripted state sequence, let the keys go old for 10 s, then stop.
# Output: ~/bench-scratch/aer6288/rehearsal (frames/, frames.jsonl, bus.jsonl).
W=~/bench-scratch/aer6288; R=$W/rehearsal; rm -rf $R; mkdir -p $R
cp $W/session.sh $R/
PY=$HOME/pyefis-venv/bin/python
SEQ_ARGS=--watch sh $R/session.sh start
$PY $W/rehearse.py 3594
sleep 10
sh $R/session.sh stop
grep -iE "error|traceback" $R/pyefis.log | head -20 || true
echo "frames: $(ls $R/frames | wc -l)"
