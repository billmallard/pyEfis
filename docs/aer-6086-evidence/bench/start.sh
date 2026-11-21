#!/bin/bash
# AER-6086 private bench run: fixgw on 3492 + pyEfis on Xvfb :7. Touches no live unit.
S=$HOME/bench-scratch/aer6086; cd $S; mkdir -p run
PY=$HOME/pyefis-venv/bin/python
PYTHONPATH=$S/fgw/src setsid -f $PY -c "import sys; sys.argv=['fixgw','--config-file','$S/fgwcfg/default.yaml']; from fixgw.server import main; main()" > run/fixgw.log 2>&1 < /dev/null
sleep 4
setsid -f Xvfb :7 -screen 0 1920x1080x24 -nolisten tcp > run/xvfb.log 2>&1 < /dev/null
sleep 2
DISPLAY=:7 QT_QPA_PLATFORM=xcb PYTHONPATH=$S/pyefis/src setsid -f $PY -c "import sys; sys.argv=['pyefis','--config-file','$S/efiscfg/default.yaml']; from pyefis.main import main; main()" > run/pyefis.log 2>&1 < /dev/null
sleep 1
for p in $(ls /proc | grep -E '^[0-9]+$'); do c=$(tr '\0' ' ' < /proc/$p/cmdline 2>/dev/null); case "$c" in *aer6086/fgwcfg*) echo $p > run/fixgw.pid;; *"Xvfb :7"*) echo $p > run/xvfb.pid;; *aer6086/efiscfg*) echo $p > run/pyefis.pid;; esac; done
cat run/*.pid
