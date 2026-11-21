#!/bin/sh
# pi6139.sh: AER-6139 DoD 2 Pi 5 GL capture. Throwaway clone of the branch,
# the service's own interpreter and eglfs environment, svs_capture --offscreen
# --traffic with pyefis.service stopped (CMA headroom, AER-2002), then pyefis
# restarted and verified. Run inside flock on the bench lock.
set -u
W=$HOME/aer6139-eval; OUT=$HOME/bench-scratch/aer6139; mkdir -p $OUT
rm -rf $W; git clone -q --depth 1 --branch aer-6139/svs-traffic https://github.com/billmallard/pyEfis.git $W || exit 4
echo "clone $(git -C $W rev-parse --short HEAD)"
export QT_QPA_PLATFORM=eglfs QT_QPA_EGLFS_KMS_CONFIG=$HOME/eglfs_hdmi.json
PYB=$HOME/pyEfis/.venv/bin/python
restart() { systemctl --user start pyefis.service; sleep 20; echo "pyefis $(systemctl --user is-active pyefis.service) NRestarts=$(systemctl --user show pyefis.service -p NRestarts --value) CmaFree $(grep CmaFree /proc/meminfo | tr -s ' ')"; }
trap restart EXIT
systemctl --user stop pyefis.service; sleep 3
echo "stopped pyefis; CmaFree $(grep CmaFree /proc/meminfo | tr -s ' ')"
cd $W
for spec in "pi_svs6:--traffic svs" "pi_tfc20:--traffic svs --traffic-extra 14" "pi_none:"; do
  n=${spec%%:*}; a=${spec#*:}
  PYTHONPATH=$W/src timeout 180 $PYB tools/svs_capture.py --out $OUT/$n.png --lat 35.72835 --lon -83.42185 --alt 4500 --heading 320 $a --tiles /data/makerplane-data/terrain/tiles --nasr "" --dof "" --water "" --offscreen --width 800 --height 480 --range 20 > $OUT/$n.log 2>&1
  echo "$n RC=$? $(tail -1 $OUT/$n.log)"
done
rm -rf $W
echo PI-DONE
