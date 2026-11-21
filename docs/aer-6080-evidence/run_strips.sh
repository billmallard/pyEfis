#!/bin/sh
# AER-6080 bench strips: every pose x mode, rendered by the dev tree and by
# the branch tree, into $OUT/<tree>/<pose>-<mode>.png. compare_strips.py
# then checks the pairs pixel for pixel.
#
#   run_strips.sh <python> <dev-tree> <branch-tree> <out-dir> <tiles> <nasr> <dof> <water>
#
# Platform comes from the caller's environment: DISPLAY=:0 on the Beelink
# (xcb), QT_QPA_PLATFORM=eglfs + QT_QPA_EGLFS_KMS_CONFIG on the Pi 5. Every
# frame is offscreen (QOffscreenSurface + FBO): no window, no DRM master.
set -u
PY=$1; DEV=$2; BR=$3; OUT=$4; TILES=$5; NASR=$6; DOF=$7; WATER=$8
HERE=$(cd "$(dirname "$0")" && pwd)

# name lat lon alt heading pitch roll magvar horizon_position
POSES="coastal 34.4275 -119.8546 2500 0 0 0 -12 50
mountains 39.20 -106.85 12500 150 -5 20 0 68
approach 37.96933 -107.98168 10500 105 -3 -10 0 68
final 34.42721 -119.87481 611 89 -3 0 -12 68"

for tree in dev branch; do
  [ "$tree" = dev ] && T=$DEV || T=$BR
  mkdir -p "$OUT/$tree"
  echo "$tree $(git -C "$T" rev-parse HEAD)" >> "$OUT/manifest.txt"
  echo "$POSES" | while read -r name lat lon alt hdg pitch roll magvar hp; do
    for mode in svs symbology none; do
      png="$OUT/$tree/$name-$mode.png"
      PYTHONPATH="$T/src" nice -n 19 "$PY" "$HERE/strip_capture.py" \
        --tree "$T" --mode "$mode" --horizon-position "$hp" -- \
        --offscreen --out "$png" --width 800 --height 480 \
        --lat "$lat" --lon "$lon" --alt "$alt" --heading "$hdg" \
        --pitch "$pitch" --roll "$roll" --magvar "$magvar" --range 15 \
        --tiles "$TILES" --nasr "$NASR" --dof "$DOF" --water "$WATER" \
        --timeout 150 > "$png.log" 2>&1
      rc=$?
      echo "$tree $name $mode rc=$rc rev=$(git -C "$T" rev-parse --short HEAD)" \
        | tee -a "$OUT/manifest.txt"
    done
  done
done
