#!/bin/sh
# AER-6639 exp3: fresh start, SIGUSR1 screenshot, then a touch at $2,$3.
# Frames: before/after the screenshot, after the touch, after a PITCH change.
OUT=$1; X=$2; Y=$3; mkdir -p "$OUT"; export DISPLAY=:0
G=$(xdotool getdisplaygeometry | tr ' ' x)
f() { ffmpeg -loglevel error -y -f x11grab -draw_mouse 0 -video_size "$G" -i :0 -frames:v 1 "$OUT/$1.png"
      ffmpeg -loglevel error -y -f x11grab -draw_mouse 0 -video_size 650x230 -i :0+300,100 -frames:v 1 -f rawvideo -pix_fmt gray - | python3 -c "import sys; b=sys.stdin.buffer.read(); print('$1 sky mean', round(sum(b)/len(b),1))"; }
w() { python3 -c "
import socket; s=socket.create_connection(('127.0.0.1',3490),timeout=3); f=s.makefile('rw')
f.write('@w$1\n'); f.flush(); print('write $1 ->', f.readline().strip())"; }
systemctl --user restart pyefis.service; sleep 30
f fresh
PID=$(pgrep -u pyefis -f "bin/pyefis" | head -1); echo "pyefis pid $PID"
kill -USR1 $PID; sleep 2
f after_usr1
sleep 5; f after_usr1_7s
xdotool mousemove $X $Y click 1
sleep 1.5; f touched
sleep 12; f timed_out
w "PITCH;1.0"; sleep 1; f pitch1
w "PITCH;0.0"; sleep 1; f pitch0
xdotool mousemove 1900 1070
