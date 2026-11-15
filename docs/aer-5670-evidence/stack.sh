#!/bin/sh
# AER-5670 (FPLWRITE2) isolated A/B stack on the Beelink, beside a staged
# review: private fixgw on 127.0.0.1:3492 (config copied from the live bench,
# XPLANE/KNOBSTER/DEMO/CANFIX off, so it binds nothing the live gateway owns;
# the flight plan engine restores the bench route from the copied
# flightplan_state.json), and a pyEfis clone on Xvfb :57. Writes nothing
# outside this directory; never touches the live display, gateway or checkout.
#   sh stack.sh setup                 clone A (dev base) and B (branch), copy configs
#   sh stack.sh gw-up | gw-down
#   sh stack.sh efis-up <A|B> | efis-down
S=$HOME/bench-scratch/aer5670/stack; mkdir -p $S; cd $S
case "$1" in
setup)
  set -e
  for v in A B; do [ -d $v ] || git clone -q --shared ~/src/pyEfis $v; done
  git -C A fetch -q origin dev && git -C A checkout -q --detach 1c39a1fc
  git -C B fetch -q origin aer-5670/fplwrite2-lazy-engine && git -C B checkout -q --detach FETCH_HEAD
  rm -rf fcfg pcfg; cp -a ~/makerplane/fixgw/config fcfg; cp -a ~/makerplane/pyefis/config pcfg
  python3 - "$S" <<'PY'
import sys, yaml
S = sys.argv[1]
p = S + "/fcfg/preferences.yaml.custom"
c = yaml.safe_load(open(p)) or {}
en = c.setdefault("enabled", {})
for k in ("QUORUM", "DEMO", "XPLANE", "KNOBSTER", "DATA_RECORDER", "CANFIX", "STRATUX", "GNX375", "GPSD"):
    en[k] = False
yaml.safe_dump(c, open(p, "w"))
n = S + "/fcfg/connections/netfix.yaml"; s = open(n).read()
s = s.replace("host: 0.0.0.0", "host: 127.0.0.1").replace("port: 3490", "port: 3492"); open(n, "w").write(s)
m = S + "/pcfg/main/default.yaml"; s = open(m).read()
assert "FixPort: 3490" in s; open(m, "w").write(s.replace("FixPort: 3490", "FixPort: 3492"))
PY
  grep -n "port\|host" fcfg/connections/netfix.yaml | grep -v "#"; grep -n FixPort pcfg/main/default.yaml
  echo "A $(git -C A log --oneline -1 | cut -c1-60)"; echo "B $(git -C B log --oneline -1 | cut -c1-60)";;
gw-up)
  [ -f gw.pid ] && kill -0 $(cat gw.pid) 2>/dev/null && { echo "gw already up"; exit 0; }
  setsid ~/pyefis-venv/bin/fixgw --config-file $S/fcfg/default.yaml >fixgw.out 2>&1 </dev/null & echo $! > gw.pid
  sleep 6; echo "gw pid $(cat gw.pid) $(kill -0 $(cat gw.pid) && echo alive)"; tail -3 fixgw.out;;
gw-down)
  [ -f gw.pid ] && kill $(cat gw.pid); rm -f gw.pid; echo gw down;;
efis-up)
  v=$2
  [ -f xvfb.pid ] && kill -0 $(cat xvfb.pid) 2>/dev/null || { setsid Xvfb :57 -screen 0 1920x1080x24 -nolisten tcp >xvfb.out 2>&1 </dev/null & echo $! > xvfb.pid; sleep 2; }
  DISPLAY=:57 QT_QPA_PLATFORM=xcb PYTHONPATH=$S/$v/src setsid ~/pyefis-venv/bin/python -c "import sys,pyefis; print(pyefis.__file__, flush=True); sys.argv=['pyefis','--config-file','$S/pcfg/default.yaml']; from pyefis.main import main; main()" >efis_$v.out 2>&1 </dev/null &
  echo $! > efis.pid; echo "efis $v pid $(cat efis.pid)";;
efis-down)
  [ -f efis.pid ] && kill $(cat efis.pid); rm -f efis.pid; sleep 2; echo efis down;;
esac
