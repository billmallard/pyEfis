#!/bin/sh
# run6139.sh LABEL NTGT: one unprofiled SVS frame-rate run (AER-6139 DoD 3),
# the AER-5934 probe method on the MAPPAINT1 panel and feed. NTGT 0 = no
# traffic; 20 = bench_traffic_inject --layout svs --extra 14 (20 targets)
# placed ahead along the feed's track. Run under the bench lock.
D=$HOME/bench-scratch/aer6139; L=$1; N=$2
mkdir -p $D/out; OUT=$D/out/$L.jsonl; : > $OUT
L0=$HOME/start-pyefis.sh; B=$D/start-pyefis.sh.orig
[ -f $B ] || cp -p $L0 $B
cmp -s $L0 $B || { echo "launcher differs from backup, abort"; exit 3; }
printf 'export PROBE_OUT=%s\n' $OUT > $D/probe.env
sed 's#^exec pyefis$#. '$D'/probe.env; exec python '$D'/probe_launch.py#' $B > $D/start-probe.sh
cat $D/start-probe.sh > $L0
grep -q probe_launch $L0 || { cat $B > $L0; echo "sed failed"; exit 4; }
echo "== $L ntgt=$N pyEfis $(git -C $HOME/src/pyEfis rev-parse --short HEAD) load $(cut -d' ' -f1-3 /proc/loadavg)"
systemctl --user restart pyefis; sleep 5
PY=""; n=0
while [ -z "$PY" ] && [ $n -lt 60 ]; do sleep 1; n=$((n+1)); PY=$(pgrep -u pyefis -f "aer6139/probe_launch.py" | head -1); done
[ -n "$PY" ] || { echo "no probe process"; cat $B > $L0; exit 5; }
while [ "$(ps -o etimes= -p $PY | tr -d ' ')" -lt 20 ]; do sleep 1; done
setsid -f python3 $HOME/bench-scratch/aer5668/feed.py 160 $D/feed.pid >/dev/null 2>&1
if [ "$N" -gt 0 ]; then
  # origin 3.2 NM along the feed's track (307.76) from its start point
  setsid -f sh -c "echo \$\$ > $D/inj.pid; exec $HOME/pyefis-venv/bin/python $HOME/src/pyEfis/tools/bench_traffic_inject.py --layout svs --extra $((N-6)) --lat 35.74061 --lon -83.44133 --alt 4500 --track 307.76 --seconds 170 --warmup 999" > $D/out/$L.inject.log 2>&1
fi
while [ "$(ps -o etimes= -p $PY | tr -d ' ')" -lt 75 ]; do sleep 1; done
date +%s > $OUT.win
sleep 30
[ "$N" -gt 0 ] && DISPLAY=:0 ffmpeg -loglevel error -y -f x11grab -draw_mouse 0 -video_size 1920x1080 -i :0 -frames:v 1 $D/out/$L.glass.png
sleep 31
date +%s > $OUT.end; sleep 6
pidstat -t -p $PY 10 1 | awk '/Average/ && $4=="'$PY'" {print "GUI thread CPU: " $9 "%"} /Average/ && $3=="'$PY'" {print "process CPU: " $9 "%"}'
kill $(cat $D/feed.pid) 2>/dev/null
[ "$N" -gt 0 ] && kill $(cat $D/inj.pid) 2>/dev/null
cat $B > $L0; cmp $L0 $B && echo "launcher restored"
echo "load $(cut -d' ' -f1-3 /proc/loadavg)"
python3 $D/summ.py $OUT
echo RC=done
