#!/bin/sh
# AER-6347 private annunciator session on the Beelink. Touches nothing live:
# private fixgw on 3497, private Xvfb :47, scratch copies of both configs, my
# branch's src on PYTHONPATH. Cleans up on exit.
D=$HOME/bench-scratch/aer6347
PY=$HOME/pyefis-venv/bin/python
cd $D || exit 2
rm -rf fgwcfg pcfg cap_*.png STOP *.pid *.log
cp -a $HOME/makerplane/fixgw/config fgwcfg && cp fgw.yaml fgwcfg/aer6347.yaml
cp -a $HOME/makerplane/pyefis/config pcfg && $PY edit_cfg.py pcfg || exit 3
cleanup() {
  touch STOP
  for p in pyefis fgw xvfb; do [ -f $p.pid ] && kill $(cat $p.pid) 2>/dev/null; done
  sleep 2
  for p in pyefis fgw xvfb; do [ -f $p.pid ] && kill -9 $(cat $p.pid) 2>/dev/null; done
}
trap cleanup EXIT
setsid sh -c "echo \$\$ > fgw.pid; exec $PY -c 'import sys; from fixgw.server import main; sys.exit(main())' --config-file $D/fgwcfg/aer6347.yaml" > fgw.log 2>&1 < /dev/null &
setsid sh -c "echo \$\$ > xvfb.pid; exec Xvfb :47 -screen 0 1920x1080x24 -nolisten tcp +extension GLX" > xvfb.log 2>&1 < /dev/null &
sleep 4
ss -ltn | grep -q ":3497" || { echo "fgw not listening"; tail -20 fgw.log; exit 4; }
setsid sh -c "echo \$\$ > pyefis.pid; DISPLAY=:47 QT_QPA_PLATFORM=xcb PYTHONPATH=$D/src exec $PY -c 'import pyefis,sys; print(\"PYEFIS\", pyefis.__file__, flush=True); from pyefis.main import main; sys.exit(main())' --config-file $D/pcfg/default.yaml" > pyefis.log 2>&1 < /dev/null &
sleep 25
grep PYEFIS pyefis.log
$PY drive.py
echo "pyefis errors:"; grep -iE "Traceback|Error|annunciator" pyefis.log | head -20
echo RC=0
