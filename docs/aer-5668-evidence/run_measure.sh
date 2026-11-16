#!/bin/sh
# run_measure.sh LABEL [X Y]: restart pyEfis, start the MAPPAINT1 feed at 20 s of
# uptime, then measure.sh (the investigation's, writing here). Run it under
# the bench lock.
D=$HOME/bench-scratch/aer5668; L=$1
mkdir -p $D/perf
systemctl --user restart pyefis
sleep 3
PID=$(systemctl --user show pyefis -p MainPID --value)
PY=""
while [ -z "$PY" ]; do sleep 1; PY=$(pgrep -f "pyefis-venv/bin/pyefis" | head -1); done
while [ "$(ps -o etimes= -p $PY | tr -d ' ')" -lt 20 ]; do sleep 1; done
setsid -f python3 $D/feed.py 200 $D/feed.pid >/dev/null 2>&1
sleep 1
echo "feed pid $(cat $D/feed.pid), pyefis $PY (unit MainPID $PID)"
if [ -n "$3" ]; then
    DISPLAY=:0 xdotool mousemove $2 $3 click 1 && echo "clicked $2,$3"
fi
sh $D/measure.sh $L
sudo ffmpeg -loglevel error -y -device /dev/dri/card1 -f kmsgrab -i - -vf hwmap=derive_device=vaapi,scale_vaapi=w=1920:h=1080:format=nv12,hwdownload,format=nv12 -frames:v 1 $D/perf/frame_$L.png && sudo chown pyefis $D/perf/frame_$L.png && echo "frame $D/perf/frame_$L.png at pyEfis $(git -C $HOME/src/pyEfis rev-parse --short HEAD)"
kill $(cat $D/feed.pid) 2>/dev/null
echo RC=done
