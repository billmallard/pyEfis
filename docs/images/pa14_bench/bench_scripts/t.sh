#!/bin/sh
# t.sh NAME [X Y | type TEXT | key KEY ...]: act 1.5 s apart, settle, grab twice (keep the 2nd)
cd ~/bench-scratch/aer1613 || exit 1
mkdir -p shots
export DISPLAY=:0
name=$1; shift
while [ $# -ge 2 ]; do
  case $1 in
    type) xdotool type --delay 120 "$2";;
    key) xdotool key "$2";;
    *) xdotool mousemove $1 $2 click 1;;
  esac
  sleep 1.5; shift 2
done
sleep 2.5
ffmpeg -loglevel error -y -f x11grab -video_size 1920x1080 -i :0 -frames:v 1 shots/_tmp.png
sleep 1
ffmpeg -loglevel error -y -f x11grab -video_size 1920x1080 -i :0 -frames:v 1 shots/$name.png
echo "$(date -u +%H:%M:%SZ) $name" >> shots/index.log
