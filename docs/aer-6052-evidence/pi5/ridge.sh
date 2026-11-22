#!/bin/bash
set -u
cd ~/bench-scratch/aer6052
D=/data/makerplane-data
COMMON="--offscreen --width 1248 --height 1200 --range 30 --tiles $D/terrain/tiles --nasr $D/navdata/current/airports.sqlite --dof $D/obstacles/current/obstacles.sqlite --water $D/water/current/water.sqlite --highways $D/highways/current/highways.sqlite --timeout 80"
for st in single_cue cross_pointer; do
  flock -w 900 /tmp/pyefis-bench.lock ./guarded_cap.sh $PWD/pr $PWD/sheet/ksba_ridge_${st}.png $COMMON --lat 34.4205 --lon -119.8790 --alt 700 --heading 75 --pitch -2 --roll 0 --fd 1.5 8 --fd-style $st
done
echo RIDGE_DONE
