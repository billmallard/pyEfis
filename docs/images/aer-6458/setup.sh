#!/bin/sh
# AER-6458 setup: isolated SITL stack beside the live services.
set -e
S=~/bench-scratch/aer6458; mkdir -p $S/sitl $S/out
cp ~/bench-scratch/aer6351/sitl/bridge.py ~/bench-scratch/aer6351/sitl/plane.parm $S/sitl/
cp ~/src/fix-gateway/tools/mavlink_sitl/baro_session.py $S/sitl/
cmp ~/src/fix-gateway/tools/mavlink_sitl/bridge.py $S/sitl/bridge.py && echo bridge-same
cd $S/sitl
B=https://firmware.ardupilot.org/Plane/stable/SITL_x86_64_linux_gnu
[ -x arduplane ] || { curl -sSfO $B/arduplane && curl -sSfO $B/firmware-version.txt && chmod +x arduplane; }
cat firmware-version.txt; echo
cd $S
[ -d fgw-dev ] || git clone -q --shared ~/src/fix-gateway fgw-dev
git -C fgw-dev fetch -q https://github.com/billmallard/fix-gateway.git dev && git -C fgw-dev checkout -q FETCH_HEAD
for side in dev branch; do
  [ -d pye-$side ] || git clone -q --shared ~/src/pyEfis pye-$side
done
git -C pye-dev fetch -q https://github.com/billmallard/pyEfis.git dev && git -C pye-dev checkout -q FETCH_HEAD
git -C pye-branch fetch -q https://github.com/billmallard/pyEfis.git aer-6458/svs-talt && git -C pye-branch checkout -q FETCH_HEAD
[ -d pcfg ] || cp -a ~/bench-scratch/aer6351/pcfg pcfg
grep -rn "FixPort" pcfg/default.yaml
for side in dev branch; do
  echo "$side $(git -C pye-$side rev-parse --short HEAD) $(PYTHONPATH=$S/pye-$side/src ~/pyefis-venv/bin/python -c 'import pyefis;print(pyefis.__file__)')"
done
echo fgw $(git -C fgw-dev rev-parse --short HEAD)
