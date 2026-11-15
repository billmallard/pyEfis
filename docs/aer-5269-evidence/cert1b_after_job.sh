#!/bin/sh
# CERT1b (AER-5269) unattended "after" job on the Beelink: wait for the bench
# lock, stage the branch, capture with the feed stopped, restore dev.
set -u
D=$HOME/bench-scratch/aer-5269; LOG=$D/after_job.log
BD=$D/bench-deploy.sh; REF=aer-5269/cert1b-old-bad-tapes
exec >>$LOG 2>&1
echo "$(date -u +%FT%TZ) job start"
BENCH_LOCK_WAIT=7200 sh $BD --ref $REF --owner AVIONICS --issue AER-5269; echo "deploy RC=$?"
[ "$(git -C $HOME/src/pyEfis branch --show-current)" = "$REF" ] || { echo "not staged; abort"; exit 1; }
flock -w 1800 /tmp/pyefis-bench.lock sh -c '
  sleep 45
  DISPLAY=:0 ffmpeg -loglevel error -y -f x11grab -i :0 -frames:v 1 '$D'/after_boot.png
  sh '$D'/cert1b_capture.sh after'
echo "capture RC=$?"
BENCH_LOCK_WAIT=7200 sh $BD --restore=pyEfis --owner AVIONICS --issue AER-5269; echo "restore RC=$?"
echo "$(date -u +%FT%TZ) job end branch=$(git -C $HOME/src/pyEfis branch --show-current)"
