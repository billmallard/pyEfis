#!/bin/bash
# AER-5808: AFC4 + AFC5 on one Pi 5 frame. GL SVS + FD (AFC5) via
# svs_capture --offscreen under AFC5's guard, then AFC4's widgets composited
# by the real screen builder at the live MAP_CTL_TEST geometry (joint.py).
set -u
cd ~/bench-scratch/aer5808
D=/data/makerplane-data
COMMON="--offscreen --width 1248 --height 1200 --range 30 --tiles $D/terrain/tiles --nasr $D/navdata/current/airports.sqlite --dof $D/obstacles/current/obstacles.sqlite --water $D/water/current/water.sqlite --highways $D/highways/current/highways.sqlite --timeout 80"
mkdir -p gl sheet
while IFS='|' read -r name pose fd; do
  [ -z "$name" ] && continue
  for st in single_cue cross_pointer; do
    flock -w 900 /tmp/pyefis-bench.lock ./guarded_cap.sh $PWD/pr $PWD/gl/${name}_${st}.png $COMMON $pose --fd $fd --fd-style $st
    if [ -s gl/${name}_${st}.png ]; then
      QT_QPA_PLATFORM=offscreen REPO=$PWD/pr venv/bin/python pr/docs/aer-5808-evidence/joint/joint.py $name gl/${name}_${st}.png sheet/${name}_${st}.png > sheet/${name}_${st}.log 2>&1; echo "joint ${name}_${st} rc=$?"
    fi
  done
done <<'S'
ksba_final|--lat 34.4205 --lon -119.8790 --alt 700 --heading 75 --pitch -2 --roll 0|-4 8
mtn_climb|--lat 39.75 --lon -104.75 --alt 8500 --heading 270 --pitch 4 --roll 0|8 -15
bank_turn|--lat 39.75 --lon -104.75 --alt 8500 --heading 200 --pitch 2 --roll 25|0 10
ksba_disc|--lat 34.4205 --lon -119.8790 --alt 700 --heading 75 --pitch -2 --roll 0|1.5 8
S
echo JOINT_DONE svc=$(systemctl --user is-active pyefis.service) nrestarts=$(systemctl --user show -p NRestarts --value pyefis.service)
