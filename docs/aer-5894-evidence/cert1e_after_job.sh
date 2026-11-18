#!/bin/sh
# CERT1e (AER-5894) "after" job on the Beelink: stage the branch, capture the
# HSI under HEAD old and fail, restore dev.
set -u
D=$HOME/bench-scratch/aer-5894; LOG=$D/after_job.log
BD=$D/bench-deploy.sh; REF=aer-5894/cert1e-hsi-heading-quality
exec >>$LOG 2>&1
echo "$(date -u +%FT%TZ) job start"
BENCH_LOCK_WAIT=600 sh $BD --ref $REF --owner AVIONICS --issue AER-5894; echo "deploy RC=$?"
if [ "$(git -C $HOME/src/pyEfis branch --show-current)" = "$REF" ]; then
  flock -w 600 /tmp/pyefis-bench.lock sh -c '
    sleep 45
    DISPLAY=:0 ffmpeg -loglevel error -y -f x11grab -i :0 -frames:v 1 '$D'/after_boot.png
    sh '$D'/cert1e_capture.sh after'
  echo "capture RC=$?"
else
  echo "not staged; no capture"
fi
BENCH_LOCK_WAIT=600 sh $BD --restore=pyEfis --owner AVIONICS --issue AER-5894; echo "restore RC=$?"
echo "$(date -u +%FT%TZ) job end branch=$(git -C $HOME/src/pyEfis branch --show-current)"
