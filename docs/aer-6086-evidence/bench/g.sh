#!/bin/bash
# g.sh NAME [xdotool args...]: optional click/keys on :7, wait, then grab the full frame
cd ~/bench-scratch/aer6086; n=$1; shift
if [ $# -gt 0 ]; then DISPLAY=:7 xdotool "$@"; fi
sleep ${WAIT:-1.5}
DISPLAY=:7 ffmpeg -loglevel error -y -f x11grab -video_size 1920x1080 -i :7 -frames:v 1 run/$n.png
echo "$n $(date -u +%H:%M:%S) $(tail -1 run/feed.csv)" >> run/frames.log
tail -1 run/frames.log
