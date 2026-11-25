#!/bin/sh
# AER-6401 (SVSSHADE2) bench strips. Throwaway clones under
# ~/bench-scratch/aer6401 (never the live checkout); offscreen SVS captures
# and map captures at the four export_svs_preview_patch SCENES poses, for
# dev and the branch. Does not restart or touch pyEfis.
# usage: bench6401.sh <branch-sha> <python> <data-root> <display-env...>
set -u
SHA=$1; PY=$2; D=$3
W=$HOME/bench-scratch/aer6401
mkdir -p $W/out
cd $W
[ -d dev ] || git clone -q https://github.com/billmallard/pyEfis.git dev
[ -d br ] || git clone -q https://github.com/billmallard/pyEfis.git br
git -C dev fetch -q origin && git -C dev checkout -q --detach origin/dev
git -C br fetch -q origin && git -C br checkout -q --detach $SHA
# The map capture tool is new on the branch; dev gets a copy of it so the
# "today" map runs dev's own map code at the same pose.
cp br/tools/map_terrain_capture.py dev/tools/
echo "dev=$(git -C dev rev-parse --short HEAD) br=$(git -C br rev-parse --short HEAD)" > out/revs.txt
TILES=$D/terrain/tiles
NASR=$D/navdata/current/airports.sqlite
WATER=$D/water/current/water.sqlite
while read name lat lon alt head; do
  for spec in "dev dev1" "dev dev2" "br brclr --terrain-shading clearance" "br brrel"; do
    set -- $spec; tree=$1; tag=$2; shift 2
    ( cd $tree && PYTHONPATH=$W/$tree/src $PY tools/svs_capture.py \
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
done <<SC
coastal 34.4275 -119.8546 2500 0
mountains 39.20 -106.85 12500 150
approach 37.96933 -107.98168 10500 105
final 34.42721 -119.87481 611 89
SC
echo DONE
