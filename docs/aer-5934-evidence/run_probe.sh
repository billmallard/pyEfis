#!/bin/sh
# run_probe.sh LABEL TAB [KEY=VAL ...]: one unprofiled SVSCEIL1 run on the
# Beelink. Run it under the bench lock. TAB is map|engine. Swaps the launcher's
# last line for probe_launch.py, restarts pyEfis, starts the MAPPAINT1 feed at
# 20 s of uptime, samples 60 s from 75 s of uptime, restores the launcher.
D=$HOME/bench-scratch/aer5934; L=$1; TAB=$2; shift 2
mkdir -p $D/out
OUT=$D/out/$L.jsonl; : > $OUT
L0=$HOME/start-pyefis.sh; B=$D/start-pyefis.sh.orig
[ -f $B ] || cp -p $L0 $B
cmp -s $L0 $B || { echo "launcher differs from backup, abort"; exit 3; }
{ printf 'export PROBE_OUT=%s\n' $OUT; for kv in "$@"; do printf 'export %s\n' "$kv"; done; } > $D/probe.env
sed 's#^exec pyefis$#. '$D'/probe.env; exec python '$D'/probe_launch.py#' $B > $D/start-probe.sh
cat $D/start-probe.sh > $L0   # keeps the inode, mode and owner
grep -q probe_launch $L0 || { cp -p $B $L0; echo "sed failed"; exit 4; }
echo "== $L tab=$TAB env=$* pyEfis $(git -C $HOME/src/pyEfis rev-parse --short HEAD) load $(cut -d' ' -f1-3 /proc/loadavg)"
systemctl --user restart pyefis
sleep 5
PY=""; n=0
while [ -z "$PY" ] && [ $n -lt 60 ]; do sleep 1; n=$((n+1)); PY=$(pgrep -u pyefis -f "aer5934/probe_launch.py" | head -1); done
[ -n "$PY" ] || { echo "no probe process"; cp -p $B $L0; exit 5; }
while [ "$(ps -o etimes= -p $PY | tr -d ' ')" -lt 20 ]; do sleep 1; done
setsid -f python3 $HOME/bench-scratch/aer5668/feed.py 160 $D/feed.pid >/dev/null 2>&1
sleep 2
[ "$TAB" = engine ] && DISPLAY=:0 xdotool mousemove 1385 10 click 1 && echo "clicked Engine tab"
while [ "$(ps -o etimes= -p $PY | tr -d ' ')" -lt 75 ]; do sleep 1; done
date +%s > $OUT.win
case " $* " in *" PROBE_SPY=1 "*)
  sudo timeout -s INT 45 $HOME/pyefis-venv/bin/py-spy record --pid $PY --duration 15 --rate 250 --idle --format speedscope -o /tmp/spy_$L.json >/dev/null 2>&1
  sudo chown pyefis:pyefis /tmp/spy_$L.json; mv /tmp/spy_$L.json $D/out/
  python3 $HOME/perf/2026-11-14-svs-slow/timeline.py $D/out/spy_$L.json | grep -E "ai_paint|stretches" ;;
*) sleep 61 ;;
esac
date +%s > $OUT.end; sleep 6; cp $OUT $OUT.all
pidstat -t -p $PY 10 1 | awk '/Average/ && $4=="'$PY'" {print "GUI thread CPU: " $9 "%"} /Average/ && $3=="'$PY'" {print "process CPU: " $9 "%"}'
kill $(cat $D/feed.pid) 2>/dev/null
cat $L0 > /dev/null; cat $B > $L0; cmp $L0 $B && echo "launcher restored"
echo "load $(cut -d' ' -f1-3 /proc/loadavg)"
python3 $D/summ.py $OUT
echo RC=done
