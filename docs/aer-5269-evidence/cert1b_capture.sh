#!/bin/sh
# CERT1b (AER-5269) bench capture: feed live data, then STOP THE FEED with
# fix-gateway still running, so every fed key goes `old` when its TOL runs out
# (not `fail`: the link watchdog never trips). Capture the PFD, restart the
# feed, capture again. Usage: cert1b_capture.sh <label>  (under the bench lock)
set -u
L=$1; D=$HOME/bench-scratch/aer-5269; OUT=$D/$L; mkdir -p $OUT
PY=$HOME/pyefis-venv/bin/python
KEYS="IAS ALT VS TAS"
XI=$(systemctl --user show -p MainPID --value pyefis.service)
echo "pyefis_xinit=$XI fixgw=$(systemctl show -p MainPID --value fixgw.service) pyEfis_head=$(git -C $HOME/src/pyEfis rev-parse --short HEAD) branch=$(git -C $HOME/src/pyEfis branch --show-current)" | tee $OUT/info.txt
$PY $D/fixflags.py --tol $KEYS | tee -a $OUT/info.txt
trap 'kill $WPID 2>/dev/null' EXIT INT TERM
$PY $D/cert1_writer.py 30 & WPID=$!
grab() {  # $1 = name; real framebuffer, twice 1 s apart (the first can be stale)
  DISPLAY=:0 ffmpeg -loglevel error -y -f x11grab -i :0 -frames:v 1 $OUT/$1_a.png
  sleep 1
  DISPLAY=:0 ffmpeg -loglevel error -y -f x11grab -i :0 -frames:v 1 $OUT/$1.png
  echo "$(date -u +%T) grabbed $1 $(sha256sum < $OUT/$1_a.png | cut -c1-12) $(sha256sum < $OUT/$1.png | cut -c1-12)" | tee -a $OUT/info.txt
  $PY $D/fixflags.py $KEYS | tee -a $OUT/info.txt
}
sleep 6; grab 1_live
kill $WPID; echo "$(date -u +%T) feed stopped (fixgw running)" | tee -a $OUT/info.txt
for i in 1 2 3 4 5 6 7 8; do sleep 0.5; $PY $D/fixflags.py $KEYS | tee -a $OUT/info.txt; done
grab 2_stopped_5s
sleep 5; grab 3_stopped_11s
$PY $D/cert1_writer.py 20 & WPID=$!
echo "$(date -u +%T) feed restarted" | tee -a $OUT/info.txt
sleep 4; grab 4_resumed_5s
journalctl --user -u pyefis.service --since "-2min" --no-pager 2>/dev/null | grep -ci "watchdog" | sed 's/^/watchdog lines in last 2 min: /' | tee -a $OUT/info.txt
echo DONE
