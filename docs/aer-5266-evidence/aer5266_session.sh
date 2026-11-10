#!/bin/sh
# AER-5266 P3b bench evidence: STRATUX on for one injection, then reverted.
set -u
W=~/bench-scratch/aer5266; mkdir -p $W; cd $W
export DISPLAY=:0
C=~/makerplane/fixgw/config/preferences.yaml.custom
TS=$(date -u +%Y%m%dT%H%M%SZ)
cp -p $C $C.bak-aer5266-$TS
grab() { g=$(xdotool getdisplaygeometry); ffmpeg -loglevel error -y -f x11grab -draw_mouse 0 -video_size "$(echo $g | tr ' ' x)" -i :0 -frames:v 1 "$1"; echo "grab $1 $(date -u +%T) rev=$(git -C ~/src/pyEfis rev-parse --short HEAD)"; }
dump() { ~/pyefis-venv/bin/python - <<PY > "$1"
import fixgw.netfix as n
c=n.Client("127.0.0.1",3490); c.connect()
for k in ["TFCCOUNT","TFCDROP","PALT","LAT","LONG"]+["TFC%d%s"%(i,f) for i in range(1,8) for f in ("TGT","ALT","NIC","ALRT","TTYP","CS")]:
    print(c.read(k))
c.disconnect()
PY
echo "dump $1 $(date -u +%T)"; }
restore() {
  cp -p $C.bak-aer5266-$TS $C
  sudo systemctl restart fixgw; sleep 6
  systemctl --user restart pyefis
  echo "REVERTED STRATUX $(date -u +%T): $(grep -c 'STRATUX: true' $C) STRATUX:true lines in custom"
}
trap restore EXIT
python3 - "$C" <<'PY'
import sys
p=sys.argv[1]; s=open(p).read()
assert "\nenabled:\n" in s
s=s.replace("\nenabled:\n","\nenabled:\n  STRATUX: true  # AER-5266 one-off P3b traffic evidence; reverted by the same session\n",1)
open(p,"w").write(s)
PY
grep -n "STRATUX" $C
sudo systemctl restart fixgw; sleep 6
systemctl --user restart pyefis
echo "restarted $(date -u +%T); waiting for the startup banner to clear"; sleep 32
~/pyefis-venv/bin/python ~/src/pyEfis/tools/bench_traffic_inject.py --ownship --lat 34.4258 --lon -119.8415 --alt 4500 --track 34 --seconds 34 --warmup 18 > inject.log 2>&1 &
IP=$!
sleep 12; grab live12.png; dump live12.txt
sleep 10; grab stale22.png; dump stale22.txt
sleep 1.5; grab stale24.png
wait $IP
cat inject.log
sleep 2; dump end.txt
echo DONE
