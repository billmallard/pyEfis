#!/bin/sh
# BOOT1 (AER-5671) ground-boot capture on the Beelink. Feeds IAS/GS valid
# over netfix (X-Plane is not running, so the plugin writes nothing), restarts
# pyEfis, grabs the glass, then raises IAS through IAS.Vgnd and grabs again.
set -u
OUT=$HOME/bench-scratch/aer5671; mkdir -p "$OUT"
export DISPLAY=:0
grab() {
    geom=$(xdotool getdisplaygeometry); sw=${geom% *}; sh_=${geom#* }
    ffmpeg -loglevel error -y -f x11grab -draw_mouse 0 -video_size "${sw}x${sh_}" -i :0 -frames:v 1 "$1"
}
cat > "$OUT/feed.py" <<'P'
import socket, sys, time
ias_file = sys.argv[1]
s = socket.create_connection(("127.0.0.1", 3490))
end = time.time() + float(sys.argv[2])
while time.time() < end:
    try:
        ias = open(ias_file).read().strip() or "0.0"
    except OSError:
        ias = "0.0"
    s.sendall(("IAS;%s;0000\nGS;0.0;0000\n" % ias).encode())
    time.sleep(0.2)
P
echo 0.0 > "$OUT/ias"
python3 "$OUT/feed.py" "$OUT/ias" 150 &
FEED=$!
sleep 2
python3 - <<'P'
import socket, time
s = socket.create_connection(("127.0.0.1", 3490)); s.sendall(b"@rIAS\n@rGS\n@rIAS.Vgnd\n")
time.sleep(0.5); print("bus before restart:", s.recv(4096).decode().split())
P
T0=$(date +%s)
systemctl --user restart pyefis.service
sleep 12
grab "$OUT/1_ground_boot_12s.png"
sleep 20
grab "$OUT/2_ground_boot_32s.png"
echo 25.0 > "$OUT/ias"; sleep 3
grab "$OUT/3_taxi_25kt.png"
echo 45.0 > "$OUT/ias"; sleep 3
grab "$OUT/4_ias_45kt.png"
kill $FEED
journalctl --user -u pyefis.service --since "@$T0" --no-pager -q | grep -E "boot:|data-status:|startup notice|Traceback|Error" | tail -12
ls -la "$OUT"
