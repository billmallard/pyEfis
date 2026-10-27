#!/bin/sh
# Live on-glass check of the baro box push toggle (AER-4009), Beelink X11.
#
# Touches the box with xdotool, pushes and turns the knob by writing the
# encoder FIX keys (BTN3 / ENC3, the bench Knobster's keys from
# hmi/encoder_input.yaml) to the live fix-gateway, reads BARO back from the
# gateway after every action and grabs the box from :0. BARO is put back to
# its starting value at the end. The PFD must be on screen (past the boot
# navdata page). Run it under the bench lock:
#
#   flock -w 900 /tmp/pyefis-bench.lock sh tools/bench_baro_push_toggle.sh OUTDIR
set -eu
OUT=${1:-./baro_toggle}
mkdir -p "$OUT"
export DISPLAY=:0
BOX_X=1064 BOX_Y=629

gw() {  # gw "line" -> gateway's reply line (or nothing for a plain write)
    python3 - "$1" <<'EOF'
import socket, sys
s = socket.create_connection(("localhost", 3490), timeout=3)
s.sendall((sys.argv[1] + "\n").encode())
if sys.argv[1].startswith("@r"):
    buf = b""
    while b"\n" not in buf:
        buf += s.recv(256)
    print(buf.decode().split(";")[1])
s.close()
EOF
}
baro() { gw "@rBARO"; }
shot() {  # shot NAME LABEL
    sleep 0.8
    ffmpeg -loglevel error -y -f x11grab -video_size 200x120 -i :0+970,560 \
        -frames:v 1 "$OUT/$1.png"
    echo "$1  gw BARO=$(baro)  # $2"
}
push() { gw "BTN3;True;0000"; sleep 0.3; gw "BTN3;False;0000"; }
turn() { gw "ENC3;$1;0000"; sleep 0.3; gw "ENC3;0;0000"; }
touch_box() { xdotool mousemove $BOX_X $BOX_Y click 1; sleep 0.3; xdotool mousemove 1900 1070; }

ORIG=$(baro)
echo "BARO before: $ORIG"
trap 'gw "BARO;$ORIG;0000"; sleep 0.5; echo "restored: $(baro)"' EXIT

# A: toggle
gw "BARO;30.05;0000"; shot a0_start "set 30.05 from outside"
touch_box;            shot a1_touched "touched: ring"
push;                 shot a2_push1 "push 1 -> standard"
push;                 shot a3_push2 "push 2 -> 30.05 back"
push;                 shot a4_push3 "push 3 -> standard again"
push;                 shot a5_push4 "push 4 -> 30.05 again"

# B: a knob turn clears the saved setting
push;                 shot b1_push "push -> standard (30.05 saved)"
turn 1;               shot b2_up "inner +1 -> 29.93 (clears)"
turn -1;              shot b3_down "inner -1 -> 29.92"
push;                 shot b4_push "push at standard, nothing saved -> no-op 29.92"

# C: a change from another source clears it
gw "BARO;30.05;0000"; touch_box
push;                 shot c1_push "push -> standard (30.05 saved)"
gw "BARO;29.80;0000"; shot c2_ext "external write 29.80 (clears)"
push;                 shot c3_push "push -> standard (29.80 saved)"
push;                 shot c4_push "push -> 29.80, not 30.05"
ffmpeg -loglevel error -y -f x11grab -video_size 1920x1080 -i :0 -frames:v 1 "$OUT/z_full.png"
