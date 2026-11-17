#!/bin/sh
# AER-5847 bench capture: the one-button BRG tab in every state it offers
# with the CDI on GPS, VLOC1 and VLOC2, plus the NAVSRC drop-outs.
export DISPLAY=:0
D=~/bench-scratch/AER-5847; O=$D/frames; mkdir -p $O; rm -f $O/*
PY=~/pyefis-venv/bin/python; C=~/pyefis-venv/bin/fixgwc
w() { $C --execute "write $1 $2" >/dev/null 2>&1; }
r() { $C --execute "read $1" 2>/dev/null; }
grab() { ffmpeg -loglevel error -y -f x11grab -video_size 1920x1080 -i :0 -frames:v 1 $1; }
# x11grab can return the previous state on the first grab after a step:
# grab twice and keep the second, then read the bus beside it.
shot() { sleep 3; grab $O/$1_a.png; sleep 1.5; grab $O/$1_glass.png; rm -f $O/$1_a.png
  echo "$1 NAVSRC=$(r NAVSRC) BRG1SRC=$(r BRG1SRC) BRG2SRC=$(r BRG2SRC) BRG1=$(r BRG1) BRG2=$(r BRG2) HEAD=$(r HEAD)"; }
TAB="753 669"
tap() { xdotool mousemove $TAB click 1; sleep 0.3; xdotool mousemove 1000 300; sleep 0.5; }
SAVE="NAVSRC=$(r NAVSRC | cut -d' ' -f1) BRG1SRC=$(r BRG1SRC | cut -d' ' -f1) BRG2SRC=$(r BRG2SRC | cut -d' ' -f1) GPSSRC=$(r GPSSRC | cut -d' ' -f1) NAV1CRS=$(r NAV1CRS | cut -d' ' -f1) NAV2CRS=$(r NAV2CRS | cut -d' ' -f1)"
echo "saved $SAVE"
$PY $D/feed.py 200 & F=$!
w GPSSRC 1
w NAVSRC 2; sleep 3
shot gps_0_none
tap; shot gps_1_brg1
tap; shot gps_2_brg2
tap; shot gps_3_both
w NAVSRC 0; shot vloc1_drop_both_to_brg2
tap; shot vloc1_0_none
tap; shot vloc1_1_brg2
tap; shot vloc1_2_none_again
tap; w NAVSRC 1; shot vloc2_drop_brg2_to_none
tap; shot vloc2_1_brg1
tap; shot vloc2_2_none_again
kill $F
for kv in $SAVE; do w ${kv%%=*} ${kv#*=}; done
echo "restored NAVSRC=$(r NAVSRC) BRG1SRC=$(r BRG1SRC) BRG2SRC=$(r BRG2SRC) GPSSRC=$(r GPSSRC) NAV1CRS=$(r NAV1CRS) NAV2CRS=$(r NAV2CRS)"
