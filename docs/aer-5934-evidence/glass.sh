#!/bin/sh
# glass.sh LABEL TAB: plain pyEfis (stock launcher, no probe, no py-spy).
# Restart, MAPPAINT1 feed at 20 s, at 75 s grab 10 s of DRM scanout at 60 fps
# (kmsgrab), crop a patch of SVS terrain, count frames whose pixels changed.
D=$HOME/bench-scratch/aer5934; L=$1; TAB=$2
cmp -s $HOME/start-pyefis.sh $D/start-pyefis.sh.orig || { echo "launcher not stock"; exit 3; }
echo "== $L tab=$TAB pyEfis $(git -C $HOME/src/pyEfis rev-parse --short HEAD) load $(cut -d' ' -f1-3 /proc/loadavg)"
systemctl --user restart pyefis; sleep 5
PY=""; n=0
while [ -z "$PY" ] && [ $n -lt 60 ]; do sleep 1; n=$((n+1)); PY=$(systemctl --user show pyefis -p MainPID --value); PY=$(pgrep -u pyefis -P $PY -f xinit >/dev/null; pgrep -u pyefis -f "pyefis-venv/bin/pyefis$" | head -1); done
[ -n "$PY" ] || { echo "no pyefis"; exit 5; }
while [ "$(ps -o etimes= -p $PY | tr -d ' ')" -lt 20 ]; do sleep 1; done
setsid -f python3 $HOME/bench-scratch/aer5668/feed.py 120 $D/feed.pid >/dev/null 2>&1
sleep 2
[ "$TAB" = engine ] && DISPLAY=:0 xdotool mousemove 1385 10 click 1 && echo "clicked Engine tab"
while [ "$(ps -o etimes= -p $PY | tr -d ' ')" -lt 75 ]; do sleep 1; done
sudo ffmpeg -loglevel error -y -framerate 60 -device /dev/dri/card1 -f kmsgrab -i - -t 10 \
  -vf "hwmap=derive_device=vaapi,scale_vaapi=w=1920:h=1080:format=nv12,hwdownload,format=nv12,crop=480:360:380:560" \
  -f framemd5 $D/out/glass_$L.md5
kill $(cat $D/feed.pid) 2>/dev/null
python3 - $D/out/glass_$L.md5 <<'PY'
import sys
rows=[l.split(",") for l in open(sys.argv[1]) if not l.startswith("#")]
pts=[int(r[2]) for r in rows]; h=[r[-1].strip() for r in rows]
ch=sum(1 for a,b in zip(h,h[1:]) if a!=b); n=len(h)
print(f"captured {n} frames ({n/10:.1f}/s of 60 asked); SVS patch changed {ch} times = {ch/10:.1f} distinct frames/s")
PY
echo RC=done
