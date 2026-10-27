#!/bin/bash
# AER-3865 sheet: 12 attitudes x {dev f1ef6ae, proto a4c1fe4}, Pi 5 live geometry.
set -u
cd ~/bench-scratch/aer3865
mkdir -p sheet
D=/data/makerplane-data
COMMON="--offscreen --width 1248 --height 1200 --range 30 --tiles $D/terrain/tiles --nasr $D/navdata/current/airports.sqlite --dof $D/obstacles/current/obstacles.sqlite --water $D/water/current/water.sqlite --highways $D/highways/current/highways.sqlite --timeout 80 --lat 39.75 --lon -104.75 --alt 8500 --heading 200"
for att in "0 0" "0 15" "0 30" "0 -30" "0 45" "0 60" "0 -60" "0 90" "0 120" "0 180" "20 60" "-20 60"; do
  set -- $att
  for b in dev proto; do
    flock -w 900 /tmp/pyefis-bench.lock ./guarded_cap.sh $PWD/$b $PWD/sheet/p${1}_r${2}_$b.png $COMMON --pitch $1 --roll $2
  done
done
echo SHEET_DONE
