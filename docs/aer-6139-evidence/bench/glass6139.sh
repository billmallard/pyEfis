#!/bin/sh
# glass6139.sh: DoD 2 glass run. Stock launcher; MAPPAINT1 feed (moving,
# valid attitude); at 60 s of uptime the P3b fixture (--layout svs, six
# states) through the stratux plugin, origin 2.0 NM along the feed's track.
# x11grab the glass at injector t=12 (all live) and t=22 (stale old), with a
# netfix dump of the TFC block at each. Run under the bench lock.
D=$HOME/bench-scratch/aer6139; mkdir -p $D/out
export DISPLAY=:0
cmp -s $HOME/start-pyefis.sh $D/start-pyefis.sh.orig || { [ -f $D/start-pyefis.sh.orig ] && { echo "launcher not stock"; exit 3; }; cp -p $HOME/start-pyefis.sh $D/start-pyefis.sh.orig; }
REV=$(git -C $HOME/src/pyEfis rev-parse --short HEAD)
grab() { ffmpeg -loglevel error -y -f x11grab -draw_mouse 0 -video_size 1920x1080 -i :0 -frames:v 1 "$1"; echo "grab $1 $(date -u +%T) rev=$(git -C $HOME/src/pyEfis rev-parse --short HEAD)"; }
dump() { $HOME/pyefis-venv/bin/python - <<PY > "$1"
import fixgw.netfix as n
c=n.Client("127.0.0.1",3490); c.connect()
for k in ["TFCCOUNT","PALT","ALT","LAT","LONG","TRACK","HEAD"]+["TFC%d%s"%(i,f) for i in range(1,8) for f in ("TGT","ALT","NIC","ALRT","TTYP","CS")]:
    print(c.read(k))
c.disconnect()
PY
echo "dump $1 $(date -u +%T)"; }
echo "== glass pyEfis $REV load $(cut -d' ' -f1-3 /proc/loadavg)"
systemctl --user restart pyefis; sleep 5
PY=""; n=0
while [ -z "$PY" ] && [ $n -lt 60 ]; do sleep 1; n=$((n+1)); PY=$(pgrep -u pyefis -f "pyefis-venv/bin/pyefis$" | head -1); done
[ -n "$PY" ] || { echo "no pyefis"; exit 5; }
while [ "$(ps -o etimes= -p $PY | tr -d ' ')" -lt 20 ]; do sleep 1; done
setsid -f python3 $HOME/bench-scratch/aer5668/feed.py 120 $D/feed.pid >/dev/null 2>&1
while [ "$(ps -o etimes= -p $PY | tr -d ' ')" -lt 58 ]; do sleep 1; done
grab $D/out/glass_t0_before.png
$HOME/pyefis-venv/bin/python $HOME/src/pyEfis/tools/bench_traffic_inject.py --layout svs --lat 35.72835 --lon -83.42185 --alt 4500 --track 307.76 --seconds 34 --warmup 18 > $D/out/glass_inject.log 2>&1 &
IP=$!
sleep 12; grab $D/out/glass_t12.png; dump $D/out/glass_t12.txt
sleep 10; grab $D/out/glass_t22.png; dump $D/out/glass_t22.txt
sleep 1.5; grab $D/out/glass_t24.png
wait $IP
sleep 2; dump $D/out/glass_end.txt
kill $(cat $D/feed.pid) 2>/dev/null
cat $D/out/glass_inject.log | tail -4
echo RC=done
