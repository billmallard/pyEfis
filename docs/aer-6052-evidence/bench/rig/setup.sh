#!/bin/bash
# AER-6052: build the private fixgw + pyEfis trees for the AFC5 sim session.
set -eu
W=~/bench-scratch/aer6052; cd $W
PY=$HOME/pyefis-venv/bin/python
[ -d fgw ] || git clone -q --branch dev https://github.com/billmallard/fix-gateway.git fgw
git -C fgw fetch -q origin dev && git -C fgw checkout -q --detach origin/dev
[ -d pr ] || git clone -q --branch aer-6052/afc5-flight-director https://github.com/billmallard/pyEfis.git pr
git -C pr fetch -q origin aer-6052/afc5-flight-director && git -C pr checkout -q --detach origin/aer-6052/afc5-flight-director
echo "fgw $(git -C fgw log --oneline -1)"; echo "pr  $(git -C pr log --oneline -1)"
$PY mkconfig_fgw.py $W/fgw/src/fixgw/config $HOME/makerplane/fixgw/config/connections/xplane.yaml $W/fcfg 10.110.10.167 49103 3593 $W/raw.jsonl
$PY mkconfig_pyefis.py $W/pr/src/pyefis/config $HOME/makerplane/pyefis/config/screens/managed.yaml $W/pcfg 3593
$PY -m py_compile seq.py && echo seq ok
