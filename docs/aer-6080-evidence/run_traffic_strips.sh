#!/bin/sh
# AER-6080 traffic strips: the SVSTFC1 layer drawn through the seam. Two
# poses from docs/aer-6139-evidence with the bench injector's six targets
# (--traffic svs), each at both flash phases, from the dev tree and the
# branch tree, into $OUT/<tree>/<pose>-<flash>.png. Then:
#   STRIP_POSES="near ridge" STRIP_MODES="on off" compare_strips.py $OUT ...
#
#   run_traffic_strips.sh <python> <dev-tree> <branch-tree> <out-dir> <tiles>
set -u
PY=$1; DEV=$2; BR=$3; OUT=$4; TILES=$5
HERE=$(cd "$(dirname "$0")" && pwd)

# name lat lon alt heading horizon_position extra_targets
POSES="near 34.4258 -119.8415 4500 34 50 0
ridge 34.4258 -119.8415 2000 0 68 14"

for tree in dev branch; do
  [ "$tree" = dev ] && T=$DEV || T=$BR
  mkdir -p "$OUT/$tree"
  echo "$tree $(git -C "$T" rev-parse HEAD)" >> "$OUT/manifest.txt"
  echo "$POSES" | while read -r name lat lon alt hdg hp extra; do
    for flash in on off; do
      png="$OUT/$tree/$name-$flash.png"
      PYTHONPATH="$T/src" nice -n 19 "$PY" "$HERE/strip_capture.py" \
        --tree "$T" --mode svs --horizon-position "$hp" --flash "$flash" -- \
        --offscreen --out "$png" --width 800 --height 480 \
        --lat "$lat" --lon "$lon" --alt "$alt" --heading "$hdg" --range 20 \
        --traffic svs --traffic-extra "$extra" \
        --tiles "$TILES" --nasr "" --dof "" --water "" --timeout 150 \
        > "$png.log" 2>&1
      echo "$tree $name $flash rc=$? rev=$(git -C "$T" rev-parse --short HEAD)" \
        | tee -a "$OUT/manifest.txt"
    done
  done
done
