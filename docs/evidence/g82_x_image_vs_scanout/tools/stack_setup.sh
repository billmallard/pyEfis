#!/bin/sh
# Isolated G82 stack: probe-branch pyEfis on its own fix-gateway (port 3492),
# configs copied from the live bench. Writes nothing outside this directory.
set -e
S=~/bench-scratch/aer5478/stack; mkdir -p $S; cd $S
[ -d pyEfis ] || git clone -q --shared ~/src/pyEfis pyEfis
git -C pyEfis fetch -q origin aer-5326/g79-paint-probe
git -C pyEfis checkout -q --detach FETCH_HEAD
rm -rf fcfg pcfg
cp -a ~/makerplane/fixgw/config fcfg
cp -a ~/makerplane/pyefis/config pcfg
python3 - <<PY
import re, yaml
p = "$S/fcfg/preferences.yaml.custom"
c = yaml.safe_load(open(p)) or {}
c["enabled"] = {"QUORUM": False, "DEMO": False, "XPLANE": False, "KNOBSTER": False,
                "FLIGHTPLAN": True, "NETFIX": True, "SYSTEM": True, "ANNUNCIATE": True,
                "COMPUTE": True, "STATE_PERSIST": True, "DATA_RECORDER": False, "CANFIX": False}
yaml.safe_dump(c, open(p, "w"))
n = "$S/fcfg/connections/netfix.yaml"; s = open(n).read()
s = s.replace("host: 0.0.0.0", "host: 127.0.0.1").replace("port: 3490", "port: 3492"); open(n, "w").write(s)
m = "$S/pcfg/main/default.yaml"; s = open(m).read()
assert "FixPort: 3490" in s; open(m, "w").write(s.replace("FixPort: 3490", "FixPort: 3492"))
PY
grep -n "port\|host" fcfg/connections/netfix.yaml | grep -v "#"; grep -n FixPort pcfg/main/default.yaml
grep -rln "3490" fcfg pcfg | grep -v "\.bak\|\.dist" | head
git -C pyEfis log --oneline -1
