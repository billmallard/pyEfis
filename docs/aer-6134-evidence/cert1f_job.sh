#!/bin/sh
# CERT1f (AER-6134): before on dev, stage the branch, after, restore dev.
set -u
D=$HOME/bench-scratch/aer-6134; LOG=$D/job.log; BD=$D/bench-deploy.sh
REF=aer-6134/cert1f-numerals-follow-heading
exec >>$LOG 2>&1
echo "$(date -u +%FT%TZ) job start"
flock -w 900 /tmp/pyefis-bench.lock sh $D/cert1f_capture.sh before; echo "before RC=$?"
BENCH_LOCK_WAIT=900 sh $BD --ref $REF --owner AVIONICS --issue AER-6134; echo "deploy RC=$?"
if [ "$(git -C $HOME/src/pyEfis branch --show-current)" = "$REF" ]; then
  flock -w 900 /tmp/pyefis-bench.lock sh -c "sleep 45; DISPLAY=:0 ffmpeg -loglevel error -y -f x11grab -i :0 -frames:v 1 $D/after_boot.png; sh $D/cert1f_capture.sh after"
  echo "after RC=$?"
else
  echo "not staged; no after capture"
fi
BENCH_LOCK_WAIT=900 sh $BD --restore=pyEfis --owner AVIONICS --issue AER-6134; echo "restore RC=$?"
echo "$(date -u +%FT%TZ) job end branch=$(git -C $HOME/src/pyEfis branch --show-current) head=$(git -C $HOME/src/pyEfis rev-parse --short HEAD)"
echo JOBEND
