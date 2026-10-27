#!/bin/bash
# AER-3865: one svs_capture --offscreen frame, concurrent with pyefis.service,
# with the AER-1697 safety cutoffs: kill on V3D BO growth > 400 MB over
# baseline, any "Failed to allocate device memory for BO" in dmesg, or 90 s.
# Usage: guarded_cap.sh <repo> <out.png> <svs_capture args...>
set -u
REPO=$1; OUT=$2; shift 2
cd ~/bench-scratch/aer3865
export QT_QPA_PLATFORM=eglfs
export QT_QPA_EGLFS_KMS_CONFIG=/home/wpballard/eglfs_hdmi.json
BOS=/sys/kernel/debug/dri/1002000000.v3d/bo_stats
base=$(awk '/allocated bo size/{print $5}' $BOS)
d0=$(dmesg 2>/dev/null | grep -ci "Failed to allocate device memory for BO")
REPO=$REPO venv/bin/python cap_live.py "$@" --out "$OUT" > "$OUT.log" 2>&1 &
pid=$!
peak=0; reason=exited
for i in $(seq 1 180); do
  sleep 0.5
  kill -0 $pid 2>/dev/null || break
  g=$(( $(awk '/allocated bo size/{print $5}' $BOS) - base ))
  [ $g -gt $peak ] && peak=$g
  if [ $g -gt 400000 ]; then reason=bo_growth; kill -9 $pid; break; fi
  d=$(dmesg 2>/dev/null | grep -ci "Failed to allocate device memory for BO")
  if [ "$d" -gt "$d0" ]; then reason=bo_alloc_fail; kill -9 $pid; break; fi
  [ $i -eq 180 ] && { reason=timeout; kill -9 $pid; }
done
wait $pid; rc=$?
echo "$(basename $OUT) rc=$rc reason=$reason peak_bo_growth_kb=$peak svc=$(systemctl --user is-active pyefis.service)"
