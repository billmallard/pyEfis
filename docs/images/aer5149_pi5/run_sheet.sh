#!/bin/bash
set -u
cd ~/bench-scratch/aer5149
mkdir -p sheet
D=/data/makerplane-data
COMMON="--offscreen --width 1248 --height 1200 --range 30 --tiles $D/terrain/tiles --nasr $D/navdata/current/airports.sqlite --dof $D/obstacles/current/obstacles.sqlite --water $D/water/current/water.sqlite --highways $D/highways/current/highways.sqlite --timeout 80 --lat 39.75 --lon -104.75 --alt 8500 --heading 200"
for att in "-18 0" "18 0" "-45 45" "45 45" "-60 60" "60 60"; do
  set -- $att
  roll=$1; bug=$2
  flock -w 900 /tmp/pyefis-bench.lock ./guarded_cap.sh $PWD/dev $PWD/sheet/r${roll}_dev.png $COMMON --roll $roll
  BB=""; [ "$bug" != "0" ] && BB="--bank-bug $bug"
  flock -w 900 /tmp/pyefis-bench.lock ./guarded_cap.sh $PWD/pr $PWD/sheet/r${roll}_pr.png $COMMON --roll $roll $BB
done
echo SHEET_DONE
