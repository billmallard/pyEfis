#!/bin/sh
# CERT1f (AER-6134) live-PFD grab on the Beelink: feed HEAD=090 (and the other
# primary keys) with CERT1b's writer, leave COURSE as the bench has it (bad),
# grab the framebuffer twice 1 s apart, keep the second.
# Usage: cert1f_capture.sh <label>   (run under /tmp/pyefis-bench.lock)
set -u
L=$1; D=$HOME/bench-scratch/aer-6134; K=$HOME/bench-scratch/aer-5269; OUT=$D/$L; mkdir -p $OUT
PY=$HOME/pyefis-venv/bin/python
echo "pyefis=$(systemctl --user show -p MainPID --value pyefis.service) head=$(git -C $HOME/src/pyEfis rev-parse --short HEAD) branch=$(git -C $HOME/src/pyEfis branch --show-current)" | tee $OUT/info.txt
$PY $K/cert1_writer.py 20 & WPID=$!
trap 'kill $WPID 2>/dev/null' EXIT INT TERM
sleep 6; $PY $K/fixflags.py HEAD COURSE CDI GSI | tee -a $OUT/info.txt
DISPLAY=:0 ffmpeg -loglevel error -y -f x11grab -i :0 -frames:v 1 $OUT/live_a.png
sleep 1
DISPLAY=:0 ffmpeg -loglevel error -y -f x11grab -i :0 -frames:v 1 $OUT/live.png
echo "$(date -u +%T) grabbed $(sha256sum < $OUT/live.png | cut -c1-12)" | tee -a $OUT/info.txt
$PY $K/fixflags.py HEAD COURSE | tee -a $OUT/info.txt
kill $WPID 2>/dev/null
echo DONE
