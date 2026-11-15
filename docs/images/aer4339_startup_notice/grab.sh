#!/bin/sh
export DISPLAY=:0
d=$HOME/bench-scratch/aer4339; rm -rf $d; mkdir -p $d
if systemctl --user cat pyefis.service >/dev/null 2>&1; then U="systemctl --user"; else U="sudo -n systemctl"; fi
echo "unit via: $U"
$U restart pyefis.service
t0=$(date +%s)
i=0
while [ $i -lt 20 ]; do
  ffmpeg -loglevel error -y -f x11grab -draw_mouse 0 -video_size 1920x1080 -i :0 -frames:v 1 $d/f$(printf %02d $i)_$(( $(date +%s) - t0 ))s.png 2>/dev/null
  i=$((i+1)); sleep 2
done
$U is-active pyefis.service
ls -l $d
