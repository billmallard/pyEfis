#!/bin/sh
# AER-5805 (HSIBRG3): restart pyEfis, x11grab every 2 s for ~40 s (startup
# notice frames), then three grabs 4 s apart with LAT/LONG aged out (SVS
# UNAVAIL, map NO POS). Run under the bench lock.
export DISPLAY=:0
d=$HOME/bench-scratch/aer5805; rm -rf $d; mkdir -p $d
F=$HOME/pyefis-venv/bin/fixgwc
g() { ffmpeg -loglevel error -y -f x11grab -draw_mouse 0 -video_size 1920x1080 -i :0 -frames:v 1 "$1" 2>/dev/null; }
for k in LAT LONG; do echo "$k: $(timeout 10 $F --execute "read $k")"; done | tee $d/position_before.txt
systemctl --user restart pyefis.service
t0=$(date +%s)
i=0
while [ $i -lt 20 ]; do
  g $d/f$(printf %02d $i)_$(( $(date +%s) - t0 ))s.png
  i=$((i+1)); sleep 2
done
sleep 10
for k in LAT LONG; do echo "$k: $(timeout 10 $F --execute "read $k")"; done | tee $d/position_aged.txt
for n in 1 2 3; do g $d/aged_$n.png; sleep 4; done
systemctl --user is-active pyefis.service
md5sum $d/*.png
