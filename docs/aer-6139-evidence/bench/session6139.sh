#!/bin/sh
# session6139.sh: AER-6139 bench session. STRATUX on for the session only
# (trap reverts it and restarts fixgw + pyefis); glass run; then interleaved
# frame-rate arms A0 B20 A0 B20. Run inside flock on the bench lock.
set -u
D=$HOME/bench-scratch/aer6139; cd $D
C=$HOME/makerplane/fixgw/config/preferences.yaml.custom
TS=$(date -u +%Y%m%dT%H%M%SZ)
cp -p $C $C.bak-aer6139-$TS
restore() {
  cp -p $C.bak-aer6139-$TS $C
  [ -f $D/start-pyefis.sh.orig ] && ! cmp -s $HOME/start-pyefis.sh $D/start-pyefis.sh.orig && cat $D/start-pyefis.sh.orig > $HOME/start-pyefis.sh
  sudo systemctl restart fixgw; sleep 6
  systemctl --user restart pyefis
  echo "REVERTED STRATUX $(date -u +%T): $(grep -c 'STRATUX: true' $C) STRATUX:true lines; launcher stock: $(cmp -s $HOME/start-pyefis.sh $D/start-pyefis.sh.orig && echo yes || echo NO)"
}
trap restore EXIT
python3 - "$C" <<'PY'
import sys
p=sys.argv[1]; s=open(p).read()
assert "\nenabled:\n" in s
s=s.replace("\nenabled:\n","\nenabled:\n  STRATUX: true  # AER-6139 one-off SVS traffic evidence; reverted by the same session\n",1)
open(p,"w").write(s)
PY
grep -n "STRATUX" $C
sudo systemctl restart fixgw; sleep 6
echo "fixgw restarted $(date -u +%T)"
sh $D/glass6139.sh
for L in A0_1:0 B20_1:20 A0_2:0 B20_2:20; do sh $D/run6139.sh ${L%%:*} ${L#*:}; done
echo SESSION-DONE
