#!/bin/bash
# AER-6052 rehearsal: bring the private stack up with no X-Plane, feed keys,
# grab: FD on (bars), FD on then stale (no bars), FD off (no bars). Then stop.
W=~/bench-scratch/aer6052; R=$W/rehearsal; rm -rf $R; mkdir -p $R
cp $W/session.sh $R/
PY=$HOME/pyefis-venv/bin/python
g() { ffmpeg -loglevel error -y -f x11grab -video_size 1920x1080 -i :6 -frames:v 1 $R/$1.png; }
# start without seq: a STOP marker makes seq.py exit at once
SEQ_ARGS=--fast sh $R/session.sh start
touch $R/STOP; sleep 2
$PY $W/rehearse.py 3593 12 True; g on
$PY $W/rehearse.py 3593 1 True; sleep 4; g stale
$PY $W/rehearse.py 3593 12 False; g off
sh $R/session.sh stop
tail -20 $R/pyefis.log | grep -iE "error|traceback" || echo "pyefis log: no error lines"
ls $R
