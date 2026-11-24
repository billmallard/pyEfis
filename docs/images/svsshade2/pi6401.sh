#!/bin/sh
# AER-6401 Pi 5 strip: the KSBA final pose, SVS (dev, dev repeat, branch
# clearance, branch relief) via svs_capture --offscreen on eglfs alongside
# the live pyEfis, and the map in caution mode for dev and the branch.
set -u
SHA=$1; PY=$2; D=$3
W=$HOME/bench-scratch/aer6401
mkdir -p $W/out; cd $W
[ -d dev ] || git clone -q https://github.com/billmallard/pyEfis.git dev
[ -d br ] || git clone -q https://github.com/billmallard/pyEfis.git br
git -C dev fetch -q origin && git -C dev checkout -q --detach origin/dev
git -C br fetch -q origin && git -C br checkout -q --detach $SHA
cp br/tools/map_terrain_capture.py dev/tools/
echo "dev=$(git -C dev rev-parse --short HEAD) br=$(git -C br rev-parse --short HEAD)" > out/revs.txt
TILES=$D/terrain/tiles; NASR=$D/navdata/current/airports.sqlite
WATER=$D/water/current/water.sqlite
name=final; lat=34.42721; lon=-119.87481; alt=611; head=89
for spec in "dev dev1" "dev dev2" "br brclr --terrain-shading clearance" "br brrel"; do
  set -- $spec; tree=$1; tag=$2; shift 2
  ( cd $tree && QT_QPA_PLATFORM=eglfs QT_QPA_EGLFS_KMS_CONFIG=$HOME/eglfs_hdmi.json \
      PYTHONPATH=$W/$tree/src $PY tools/svs_capture.py \
      --out $W/out/${name}_svs_$tag.png --lat $lat --lon $lon --alt $alt \
      --heading $head --tiles $TILES --nasr $NASR --water $WATER \
      --offscreen --width 800 --height 480 --range 15 "$@" ) \
      > out/${name}_svs_$tag.log 2>&1
  echo "$name svs $tag rc=$?"
done
for tree in dev br; do
  ( cd $tree && QT_QPA_PLATFORM=offscreen PYTHONPATH=$W/$tree/src $PY \
      tools/map_terrain_capture.py --out $W/out/${name}_map_$tree.png \
      --lat $lat --lon $lon --alt $alt --track $head --tiles $TILES \
      --nasr $NASR --water $WATER --terrain-mode caution ) \
      > out/${name}_map_$tree.log 2>&1
  echo "$name map $tree rc=$?"
done
echo DONE
