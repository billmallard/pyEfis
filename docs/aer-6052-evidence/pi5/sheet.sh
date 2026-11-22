#!/bin/bash
# AER-6052: FD bars over Pi 5 GL terrain, live MAP_CTL_TEST geometry, both styles.
set -u
cd ~/bench-scratch/aer6052
D=/data/makerplane-data
COMMON="--offscreen --width 1248 --height 1200 --range 30 --tiles $D/terrain/tiles --nasr $D/navdata/current/airports.sqlite --dof $D/obstacles/current/obstacles.sqlite --water $D/water/current/water.sqlite --highways $D/highways/current/highways.sqlite --timeout 80"
# name | pose | fd
while IFS='|' read -r name pose fd; do
  [ -z "$name" ] && continue
  for st in single_cue cross_pointer; do
    flock -w 900 /tmp/pyefis-bench.lock ./guarded_cap.sh $PWD/pr $PWD/sheet/${name}_${st}.png $COMMON $pose --fd $fd --fd-style $st
  done
done <<'S'
ksba_final|--lat 34.4205 --lon -119.8790 --alt 700 --heading 75 --pitch -2 --roll 0|-4 8
mtn_climb|--lat 39.75 --lon -104.75 --alt 8500 --heading 270 --pitch 4 --roll 0|8 -15
bank_turn|--lat 39.75 --lon -104.75 --alt 8500 --heading 200 --pitch 2 --roll 25|0 10
S
echo SHEET_DONE
