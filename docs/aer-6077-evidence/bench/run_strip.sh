set -u
S=$HOME/bench-scratch/aer6077; cd $S; export DISPLAY=:0
rd() { python3 -c "
import socket,sys
s=socket.create_connection(('127.0.0.1',3492),timeout=3); s.sendall(('@r%s\n'%sys.argv[1]).encode()); print(s.recv(512).decode().strip().split(';')[1])" $1; }
grab() { ffmpeg -loglevel error -y -f x11grab -video_size 1920x1080 -i :0 -frames:v 1 $S/$1.png; echo "$(date -u +%H:%M:%S) $1: NAVSRC=$(rd NAVSRC) DEMOLOOP=$(rd DEMOLOOP) pyEfis=$(git -C pyEfis rev-parse --short HEAD) fgw=$(git -C fix-gateway rev-parse --short HEAD)" | tee -a $S/strip.log; }
# idle return pushed past the loop, so the loop trigger is what is measured
sed -i 's/^  idle_return_s: 60$/  idle_return_s: 900/' cfg/pyefis/default.yaml; grep -A2 "^kiosk:" cfg/pyefis/default.yaml | tail -1
kill $(cat x.pid); sleep 6
setsid -f sh -c "echo \$\$ > $S/x.pid; exec /usr/bin/xinit $S/pyefis-x.sh -- :0 vt1 -nolisten tcp" > $S/pyefis2.log 2>&1
timeout 120 sh -c "until grep -q 'visitor settings reset' $S/pyefis2.log; do sleep 2; done"; sleep 25
: > $S/strip.log
grab b1_before
xdotool mousemove 505 669 click 1; sleep 3
grab b2_tapped
L0=$(rd DEMOLOOP)
timeout 400 sh -c "while [ \"\$(python3 -c \"
import socket
s=socket.create_connection(('127.0.0.1',3492),timeout=3); s.sendall(b'@rDEMOLOOP\n'); print(s.recv(512).decode().strip().split(';')[1])\")\" = '$L0' ]; do sleep 1; done"
sleep 2
grab b3_next_loop
xdotool mousemove 1900 1070
grep "kiosk" $S/pyefis2.log | tail -4
