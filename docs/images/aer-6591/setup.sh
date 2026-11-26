#!/bin/sh
# AER-6591 setup: isolated SITL stack beside the live services, reusing the
# AER-6458 SITL binary and bridge. The map is put in caution mode in a copy
# of the bench's live config.
set -e
S=~/bench-scratch/aer6591; O=~/bench-scratch/aer6458
mkdir -p $S/sitl $S/out
cp $O/sitl/bridge.py $O/sitl/plane.parm $O/sitl/arduplane $O/sitl/firmware-version.txt $S/sitl/
cp ~/src/fix-gateway/tools/mavlink_sitl/baro_session.py $S/sitl/
cd $S
[ -d fgw-dev ] || git clone -q --shared ~/src/fix-gateway fgw-dev
git -C fgw-dev fetch -q https://github.com/billmallard/fix-gateway.git dev && git -C fgw-dev checkout -q FETCH_HEAD
for side in dev branch; do
  [ -d pye-$side ] || git clone -q --shared ~/src/pyEfis pye-$side
done
git -C pye-dev fetch -q https://github.com/billmallard/pyEfis.git dev && git -C pye-dev checkout -q FETCH_HEAD
git -C pye-branch fetch -q https://github.com/billmallard/pyEfis.git aer-6591/mapalt1-talt && git -C pye-branch checkout -q FETCH_HEAD
rm -rf pcfg && cp -a $O/pcfg pcfg
sed -i 's/^\( *\)terrain_mode: relief$/\1terrain_mode: caution/' pcfg/screens/managed.yaml
# The live map is nav_only (no relief, so no caution tint): standard style,
# and airways/fixes off so the terrain is not hidden under them.
sed -i -e 's/^\( *\)map_style: nav_only$/\1map_style: standard/' \
  -e 's/^\( *\)layer_airways: true$/\1layer_airways: false/' \
  -e 's/^\( *\)layer_fixes: true$/\1layer_fixes: false/' pcfg/screens/managed.yaml
grep -n "terrain_mode\|map_style\|layer_airways\|layer_fixes" pcfg/screens/managed.yaml; grep -n FixPort pcfg/main/default.yaml
for side in dev branch; do echo "$side $(git -C pye-$side rev-parse --short HEAD)"; done
echo fgw $(git -C fgw-dev rev-parse --short HEAD)
