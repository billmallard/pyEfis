#!/bin/sh
# stack.sh up [ENV=V ...] | down  -- isolated fixgw + probe pyEfis, fullscreen over the kiosk
S=~/bench-scratch/aer5478/stack; cd $S
case "$1" in
up) shift
  pgrep -f "fixgw --config-file $S" >/dev/null || setsid -f ~/pyefis-venv/bin/fixgw --config-file $S/fcfg/default.yaml >fixgw.out 2>&1 </dev/null
  sleep 4
  [ -f /tmp/g79_probe.log ] && mv /tmp/g79_probe.log /tmp/g79_probe.log.$(date +%s)
  env "$@" DISPLAY=:0 QT_QPA_PLATFORM=xcb PYTHONPATH=$S/pyEfis/src setsid -f ~/pyefis-venv/bin/python -c "import sys,pyefis; print(pyefis.__file__, flush=True); sys.argv=['pyefis','--config-file','$S/pcfg/default.yaml']; from pyefis.main import main; main()" >pyefis.out 2>&1 </dev/null
  echo "up $(date -u +%T) env=$*";;
down)
  pkill -f "pyefis','--config-file','$S" ; sleep 2; pkill -f "fixgw --config-file $S"; sleep 1
  pgrep -af "$S" | grep -v pgrep || echo "down";;
esac
