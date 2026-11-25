#!/bin/sh
# SVSFLOOR1 evidence: KSBA RWY 07, 1000 ft past the threshold, on the centreline,
# heading 088.6 true (magvar 0), pitch 0. Runway surface there is 11.5 ft (NASR).
D=/data/makerplane-data
cd ~/bench-scratch/aer6595
for tree in dev branch; do
  mkdir -p out/$tree
  for case in "ok 16.5" "under20 -8.5" "under40 -28.5"; do
    set -- $case
    DISPLAY=:0 PYTHONPATH=$PWD/$tree/src ~/pyefis-venv/bin/python $tree/tools/svs_capture.py \
      --offscreen --width 1024 --height 600 \
      --lat 34.427568 --lon -119.851317 --alt $2 --heading 88.6 --magvar 0 --pitch 0 \
      --range 15 --tiles $D/terrain/tiles --water $D/water/current/water.sqlite \
      --nasr $D/navdata/current/airports.sqlite --dof $D/obstacles/current/obstacles.sqlite \
      --out out/$tree/ksba07-$1.png > out/$tree/ksba07-$1.log 2>&1
    echo "$tree $1 rc=$?"
  done
done
