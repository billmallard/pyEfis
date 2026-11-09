#!/bin/sh
# CERT1a (AER-5178) unattended "after" job on the Beelink: wait for the bench
# lock, stage the branch, capture with fixgw stopped, restore dev.
set -u
D=$HOME/bench-scratch/aer-5178; LOG=$D/after_job.log
BD=$D/bench-deploy.sh; REF=aer-5178/cert1a-failed-tape-x
exec >>$LOG 2>&1
echo "$(date -u +%FT%TZ) job start"
BENCH_LOCK_WAIT=7200 sh $BD --ref $REF --owner AVIONICS --issue AER-5178; echo "deploy RC=$?"
[ "$(git -C $HOME/src/pyEfis branch --show-current)" = "$REF" ] || { echo "not staged; abort"; exit 1; }
flock -w 1800 /tmp/pyefis-bench.lock sh -c '
  sleep 45
  DISPLAY=:0 ffmpeg -loglevel error -y -f x11grab -i :0 -frames:v 1 '$D'/after_boot.png
  DISPLAY=:0 xdotool mousemove 402 971 click 1; sleep 10
  DISPLAY=:0 ffmpeg -loglevel error -y -f x11grab -i :0 -frames:v 1 '$D'/after_boot_tapped.png
  sh '$D'/cert1a_capture.sh after'
echo "capture RC=$?"
BENCH_LOCK_WAIT=7200 sh $BD --restore --owner AVIONICS --issue AER-5178; echo "restore RC=$?"
echo "$(date -u +%FT%TZ) job end branch=$(git -C $HOME/src/pyEfis branch --show-current)"
