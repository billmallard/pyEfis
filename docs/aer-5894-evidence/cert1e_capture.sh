#!/bin/sh
# CERT1e (AER-5894) bench capture of the HSI under HEAD old and HEAD fail.
# old: feed live data, then stop the feed with fix-gateway running, so HEAD goes
#      `old` when its 2 s TOL runs out (the link watchdog never trips).
# fail: feed again, then SIGSTOP fix-gateway (a hung gateway), so CERT1's
#      watchdog marks every key `fail`; SIGCONT after the grab.
# Usage: cert1e_capture.sh <label>   (run under /tmp/pyefis-bench.lock)
set -u
L=$1; D=$HOME/bench-scratch/aer-5894; K=$HOME/bench-scratch/aer-5269; OUT=$D/$L; mkdir -p $OUT
PY=$HOME/pyefis-venv/bin/python
KEYS="HEAD IAS"
FGW=$(systemctl show -p MainPID --value fixgw.service)
echo "fixgw=$FGW pyefis=$(systemctl --user show -p MainPID --value pyefis.service) pyEfis_head=$(git -C $HOME/src/pyEfis rev-parse --short HEAD) branch=$(git -C $HOME/src/pyEfis branch --show-current)" | tee $OUT/info.txt
$PY $K/fixflags.py --tol $KEYS | tee -a $OUT/info.txt
cleanup() { kill -CONT $FGW 2>/dev/null; kill $WPID 2>/dev/null; }
trap cleanup EXIT INT TERM
grab() {  # real framebuffer, twice 1 s apart (the first can be stale)
  DISPLAY=:0 ffmpeg -loglevel error -y -f x11grab -i :0 -frames:v 1 $OUT/$1_a.png
  sleep 1
  DISPLAY=:0 ffmpeg -loglevel error -y -f x11grab -i :0 -frames:v 1 $OUT/$1.png
  echo "$(date -u +%T) grabbed $1 $(sha256sum < $OUT/$1.png | cut -c1-12)" | tee -a $OUT/info.txt
}
$PY $K/cert1_writer.py 30 & WPID=$!
sleep 6; $PY $K/fixflags.py $KEYS | tee -a $OUT/info.txt; grab 1_live
kill $WPID; echo "$(date -u +%T) feed stopped (fixgw running)" | tee -a $OUT/info.txt
sleep 5; $PY $K/fixflags.py $KEYS | tee -a $OUT/info.txt; grab 2_old
$PY $K/cert1_writer.py 40 & WPID=$!
sleep 6; $PY $K/fixflags.py $KEYS | tee -a $OUT/info.txt; grab 3_live_again
kill -STOP $FGW; echo "$(date -u +%T) SIGSTOP fixgw" | tee -a $OUT/info.txt
sleep 6; grab 4_fail
kill -CONT $FGW; echo "$(date -u +%T) SIGCONT fixgw" | tee -a $OUT/info.txt
sleep 6; $PY $K/fixflags.py $KEYS | tee -a $OUT/info.txt; grab 5_resumed
kill $WPID 2>/dev/null
echo DONE
