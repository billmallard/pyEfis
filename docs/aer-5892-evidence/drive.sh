#!/bin/sh
# MENU1 (AER-5892) bench driver. Each call runs under the bench lock and
# refuses to act unless the staging claim is still AER-5892.
# drive.sh swipe X0 Y0 X1 Y1 [STEP_SLEEP] | tap X Y | drag X0 Y0 X1 Y1 SECONDS | grab NAME
D=$HOME/bench-scratch/aer-5892
export DISPLAY=:0
exec flock -w 300 /tmp/pyefis-bench.lock sh -c '
grep -q "^issue=AER-5892$" $HOME/.bench-claim || { echo "claim is not AER-5892"; exit 9; }
D='"$D"'
cmd=$1; shift
case $cmd in
swipe)  # a quick swipe in 6 steps
  x0=$1 y0=$2 x1=$3 y1=$4; s=${5:-0.03}
  xdotool mousemove $x0 $y0 mousedown 1
  for i in 1 2 3 4 5 6; do sleep $s; xdotool mousemove $((x0+(x1-x0)*i/6)) $((y0+(y1-y0)*i/6)); done
  sleep $s; xdotool mouseup 1 ;;
drag)   # a slow drag over SECONDS in 20 steps
  x0=$1 y0=$2 x1=$3 y1=$4; secs=$5
  xdotool mousemove $x0 $y0 mousedown 1
  for i in $(seq 1 20); do sleep $(echo "$secs/20" | bc -l); xdotool mousemove $((x0+(x1-x0)*i/20)) $((y0+(y1-y0)*i/20)); done
  xdotool mouseup 1 ;;
tap) xdotool mousemove $1 $2 click 1 ;;
grab)
  sleep ${2:-0.8}
  ffmpeg -loglevel error -y -f x11grab -video_size 1920x1080 -i :0 -frames:v 1 $D/$1.png
  echo "$1 $(date -u +%FT%TZ) head=$(git -C $HOME/src/pyEfis rev-parse --short HEAD) pid=$(systemctl --user show -p MainPID --value pyefis)" >> $D/grabs.txt ;;
esac
' sh "$@"
