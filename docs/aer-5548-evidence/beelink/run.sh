#!/bin/sh
# AER-5548 bench capture: BRG tab states with NAVSRC on GPS and VLOC.
export DISPLAY=:0
O=~/bench-scratch/AER-5548/frames; mkdir -p $O; rm -f $O/*
PY=~/pyefis-venv/bin/python; C=~/pyefis-venv/bin/fixgwc
PID=$(systemctl --user show -p MainPID --value pyefis.service)
w() { $C --execute "write $1 $2" >/dev/null 2>&1; }
r() { $C --execute "read $1" 2>/dev/null; }
shot() { sleep 3
  ffmpeg -loglevel error -y -f x11grab -video_size 1920x1080 -i :0 -frames:v 1 $O/$1_glass.png
  echo "$1 NAVSRC=$(r NAVSRC) BRG1SRC=$(r BRG1SRC) BRG2SRC=$(r BRG2SRC) COURSE=$(r COURSE) HEAD=$(r HEAD)"; }
tap() { xdotool mousemove $1 $2 click 1; sleep 0.8; }
B1="767 661"; B2="767 678"
$PY ~/bench-scratch/AER-5548/feed.py 150 & F=$!
w GPSSRC 1
sleep 3
w NAVSRC 2; shot gps0_both_off
tap $B1; shot gps1_brg1_on
tap $B2; tap $B2; shot gps2_brg1_brg2_on
tap $B1; tap $B1; shot gps3_brg1_off_brg2_on
w NAVSRC 0; shot vloc0_brg2_on
tap $B1; shot vloc1_brg1_brg2_on
tap $B2; shot vloc2_brg1_on_brg2_off
tap $B1; tap $B1; shot vloc3_both_off
tap $B2; tap $B2; w NAVSRC 1; shot vloc2cdi_brg2_dropped
kill $F
w NAVSRC 2; w BRG1SRC 2; w BRG2SRC 0; w GPSSRC 0; w NAV1CRS 0; w NAV2CRS 0
echo "restored GPSSRC=$(r GPSSRC) NAV1CRS=$(r NAV1CRS) NAV2CRS=$(r NAV2CRS) NAVSRC=$(r NAVSRC) BRG1SRC=$(r BRG1SRC) BRG2SRC=$(r BRG2SRC)"
