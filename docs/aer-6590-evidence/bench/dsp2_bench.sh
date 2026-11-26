#!/bin/sh
# AER-6590 (DSP2) bench probe: stock pyEfis + stock fix-gateway configs, a
# private gateway on netfix 127.0.0.1:3495 and pyEfis offscreen, so the live
# kiosk and its gateway are untouched.  Runs dev, then the branch.  For each
# side, pyEfis boots EMS and the TESS1 spike page's six pulses are written
# over netfix (True then False, as the plugin's {pulse: KEY} does); each
# target key is read back.
S=~/bench-scratch/aer6590; PORT=3495; PY=~/pyefis-venv/bin/python
mkdir -p $S/out; cd $S || exit 1
[ -d fgw ] || git clone -q --shared ~/src/fix-gateway fgw
git -C fgw fetch -q https://github.com/billmallard/fix-gateway.git dev && git -C fgw checkout -q FETCH_HEAD
for side in dev branch; do [ -d pye-$side ] || git clone -q --shared ~/src/pyEfis pye-$side; done
git -C pye-dev fetch -q https://github.com/billmallard/pyEfis.git dev && git -C pye-dev checkout -q FETCH_HEAD
git -C pye-branch fetch -q https://github.com/billmallard/pyEfis.git aer-6590/dsp2-panel-bindings && git -C pye-branch checkout -q FETCH_HEAD
rm -rf gcfg && cp -a fgw/src/fixgw/config gcfg
sed -i "s/^\(    port: \)3490$/\1$PORT/" gcfg/connections/netfix.yaml
grep -n "port:" gcfg/connections/netfix.yaml

run_side() {
  side=$1; O=$S/out/$side; rm -rf $O; mkdir -p $O
  rm -rf pcfg-$side && cp -a pye-$side/src/pyefis/config pcfg-$side
  sed -i -e "s/^\(  FixPort: \)3490$/\1$PORT/" -e "s/^\(  defaultScreen: \)PFD$/\1EMS/" pcfg-$side/main/default.yaml
  grep -nE "FixPort|defaultScreen" pcfg-$side/main/default.yaml
  echo "side=$side fgw=$(git -C fgw rev-parse --short HEAD) pyefis=$(git -C pye-$side rev-parse --short HEAD) start=$(date -u +%FT%TZ)" > $O/prov.txt
  PYTHONPATH=$S/fgw/src setsid -f $PY -c "import sys; from fixgw.server import main; sys.exit(main())" --config-file $S/gcfg/default.yaml >$O/fixgw.out 2>&1 </dev/null
  sleep 6
  PYTHONPATH=$S/pye-$side/src QT_QPA_PLATFORM=offscreen setsid -f $PY -m pyefis.main --verbose --config-file $S/pcfg-$side/default.yaml >$O/pyefis.out 2>&1 </dev/null
  sleep 25
  grep -F "data-status: booting" $O/pyefis.out | tail -1 | tee -a $O/prov.txt
  $PY $S/probe.py $PORT | tee $O/probe.txt
  pkill -f "aer6590/pcfg-$side/default.yaml"; sleep 2
  pkill -f "aer6590/gcfg/default.yaml"; sleep 2
  pgrep -af "aer6590/" | grep -v "pgrep\|dsp2_bench" || echo "stack down"
  echo "end=$(date -u +%FT%TZ)" >> $O/prov.txt
}
run_side dev
run_side branch
