#!/bin/sh
# AER-5125 before/after captures. Run by path under the bench lock.
set -e
R=~/bench-scratch/aer5125; rm -rf $R; mkdir -p $R/out; cd $R
for side in base:aer-5122/svs-horizon-offset-tangent branch:aer-5125/svs-tangent-ladder; do
  name=${side%%:*}; ref=${side#*:}
  git clone -q --depth 1 --branch $ref https://github.com/billmallard/pyEfis.git $name
  cp $name/docs/aer-5122-evidence/hp_capture.py $name/
  ( cd $name; echo "$name $(git rev-parse --short HEAD)"
    for hp in 50 75; do for pitch in -20 20; do for mode in terrain-only symbology-only composite; do
      flag="--$mode"; [ $mode = composite ] && flag=""
      HP=$hp PDS=50 DISPLAY=:0 PYTHONPATH=$PWD/src timeout 120 ~/pyefis-venv/bin/python hp_capture.py \
        --offscreen --flat $flag --width 1024 --height 768 \
        --lat 24.30 --lon -81.80 --alt 100 --heading 180 --pitch $pitch --roll 0 \
        --range 30 --tiles /data/makerplane-data/terrain/tiles \
        --water /data/makerplane-data/water/current/water.sqlite \
        --out $R/out/${name}_hp${hp}_p${pitch}_${mode}.png > $R/out/${name}_hp${hp}_p${pitch}_${mode}.log 2>&1 || echo "FAIL $name $hp $pitch $mode"
    done; done; done )
done
ls $R/out | grep -c png
