#!/bin/sh
# CERT1a (AER-5178) bench capture, reusing CERT1s method: feed live data, SIGSTOP fix-gateway
# with its sockets open, capture the PFD, SIGCONT, capture again.
# Usage: cert1_capture.sh <label>   (run under the bench lock)
set -u
L=$1; OUT=$HOME/bench-scratch/aer-5178/$L; mkdir -p $OUT
PY=$HOME/pyefis-venv/bin/python
FGW=$(systemctl show -p MainPID --value fixgw.service)
XI=$(systemctl --user show -p MainPID --value pyefis.service)
EFIS=$(pgrep -P "$XI" -x pyefis)
echo "fixgw=$FGW pyefis=$EFIS pyEfis_head=$(git -C $HOME/src/pyEfis rev-parse --short HEAD) branch=$(git -C $HOME/src/pyEfis branch --show-current)" | tee $OUT/info.txt
trap 'kill -CONT $FGW 2>/dev/null; kill $WPID 2>/dev/null' EXIT INT TERM
$PY $HOME/bench-scratch/aer-5178/cert1_writer.py 40 & WPID=$!
grab() {  # $1 = name; real framebuffer, twice 1 s apart (the first can be stale)
  DISPLAY=:0 ffmpeg -loglevel error -y -f x11grab -i :0 -frames:v 1 $OUT/$1_a.png
  sleep 1
  DISPLAY=:0 ffmpeg -loglevel error -y -f x11grab -i :0 -frames:v 1 $OUT/$1.png
  echo "$(date -u +%T) grabbed $1 $(sha256sum < $OUT/$1_a.png | cut -c1-12) $(sha256sum < $OUT/$1.png | cut -c1-12)" | tee -a $OUT/info.txt
}
sleep 6; grab 1_live
sleep 1.5; grab 2_live_b
kill -STOP $FGW; echo "$(date -u +%T) SIGSTOP fixgw" | tee -a $OUT/info.txt
sleep 1; grab 3_stopped_1s
sleep 4; grab 4_stopped_6s
sleep 5; grab 5_stopped_12s
kill -CONT $FGW; echo "$(date -u +%T) SIGCONT fixgw" | tee -a $OUT/info.txt
sleep 4; grab 6_resumed_4s
for k in PITCH ROLL ALT IAS; do echo "$k $($HOME/pyefis-venv/bin/fixgwc --execute "read $k")"; done | tee -a $OUT/info.txt
journalctl --user -u pyefis.service --since "-2min" --no-pager 2>/dev/null | grep -i "watchdog\|FIX gateway" | tail -5 | tee -a $OUT/info.txt
echo DONE
