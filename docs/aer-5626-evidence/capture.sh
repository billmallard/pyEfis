#!/bin/bash
# AER-5626 (DEMO4) bench capture: one full demo loop on the Beelink's live
# panel, kiosk on. A scratch demo gateway (fix-gateway aer-5626/demo-kiosk-keys)
# runs on netfix :3491 beside the bench's own fixgw, which is not touched.
# pyEfis's live config is pointed at :3491 with a kiosk block for the run, and
# put back byte-for-byte (cp -p) at the end, whatever happens.
# Run by path, under the bench lock:  flock -o -w 900 /tmp/pyefis-bench.lock bash capture.sh
set -u
export DISPLAY=:0
D=$HOME/bench-scratch/aer-5626
CFG=$HOME/makerplane/pyefis/config
LOOP_S=${LOOP_S:-1240}
mkdir -p $D/frames $D/backup
cd $D
log(){ echo "$(date -u +%H:%M:%S) $*" | tee -a $D/capture.log; }
: > $D/capture.log

restore(){
  log "restore: pyEfis config, scratch gateway, pyefis restart"
  cp -p $D/backup/default.yaml $CFG/default.yaml
  cp -p $D/backup/main-default.yaml $CFG/main/default.yaml
  systemctl --user stop aer5626-demo 2>/dev/null
  systemctl --user reset-failed aer5626-demo 2>/dev/null
  systemctl --user restart pyefis
  cmp -s $D/backup/default.yaml $CFG/default.yaml && cmp -s $D/backup/main-default.yaml $CFG/main/default.yaml \
    && log "restore: config byte-identical to the backup" || log "restore: CONFIG DIFFERS FROM BACKUP"
}

# 1. the scratch gateway
[ -d fix-gateway ] || git clone -q https://github.com/billmallard/fix-gateway.git fix-gateway
git -C fix-gateway fetch -q origin aer-5626/demo-kiosk-keys && git -C fix-gateway checkout -q FETCH_HEAD
log "fix-gateway at $(git -C fix-gateway rev-parse --short HEAD)"
log "pyEfis at $(git -C $HOME/src/pyEfis rev-parse --short HEAD) ($(git -C $HOME/src/pyEfis branch --show-current))"
rm -rf config && cp -r fix-gateway/src/fixgw/config config
sed -i 's/port: 3490/port: 3491/' config/connections/netfix.yaml
cat >> config/connections/demo.yaml <<'Y'
  pages:
    - {at: 0, page: PFD/Map}
    - {at: 150, page: PFD/Flight Plan}
    - {at: 420, page: PFD/Map}
    - {at: 780, page: PFD/Engine}
    - {at: 960, page: PFD/Map}
Y

# 2. pyEfis config for the run (backups first)
cp -p $CFG/default.yaml $D/backup/default.yaml
cp -p $CFG/main/default.yaml $D/backup/main-default.yaml
trap restore EXIT
trap "log signal HUP; exit 129" HUP
trap "log signal TERM; exit 143" TERM
trap "log signal INT; exit 130" INT
sed -i 's/^\(\s*FixPort:\s*\)3490/\13491/' $CFG/main/default.yaml
printf '\n# AER-5626 bench capture, reverted by capture.sh\nkiosk:\n  enabled: true\n  idle_return_s: 30\n' >> $CFG/default.yaml
grep -n "FixPort" $CFG/main/default.yaml | tee -a $D/capture.log

systemctl --user stop aer5626-demo 2>/dev/null; systemctl --user reset-failed aer5626-demo 2>/dev/null
systemd-run --user --unit=aer5626-demo --working-directory=$D \
  --setenv=PYTHONPATH=$D/fix-gateway/src \
  $HOME/pyefis-venv/bin/python $D/fix-gateway/doc/evidence/aer-5461-demo-soak/soak.py \
  $D/config/default.yaml 0.45 20 $D/soak.jsonl
sleep 2
systemctl --user restart pyefis
T0=$(date +%s)
log "gateway + pyefis started; T0=$T0 (route time ~= t - watch 3 s)"

nf(){ $HOME/pyefis-venv/bin/python - "$1" <<'P'
import socket,sys
s=socket.create_connection(('localhost',3491)); s.settimeout(3)
s.sendall(('@r'+sys.argv[1]+'\n').encode()); print(s.recv(200).decode().strip()); s.close()
P
}
grab(){ ffmpeg -loglevel error -y -f x11grab -video_size 1920x1080 -i :0 -frames:v 1 $D/frames/$1.png; }
tap(){ xdotool mousemove $1 $2 click 1; sleep 0.3; xdotool mousemove 1919 1079; log "tap $1,$2 ($3)"; }

next=0
touched1=0; touched2=0
while :; do
  t=$(( $(date +%s) - T0 ))
  [ $t -ge $LOOP_S ] && break
  if [ $t -ge $next ]; then
    n=$(printf "t%04d" $t)
    grab $n
    log "$n DEMOLIVE=$(nf DEMOLIVE) DEMOPAGE=$(nf DEMOPAGE) FPLSEQ=$(nf FPLSEQ)"
    next=$(( next + 10 ))
  fi
  # touch 1: on the Flight Plan page, the attendee taps Map; held 30 s, then back
  if [ $touched1 = 0 ] && [ $t -ge 200 ]; then touched1=1; tap 1272 10 "Map tab"; grab "touch1_t${t}"; fi
  # touch 2: just before the script's 420 s switch to Map, tap Engine; the
  # switch happens while held, and the idle return lands on Map
  if [ $touched2 = 0 ] && [ $t -ge 408 ]; then touched2=1; tap 1386 10 "Engine tab"; grab "touch2_t${t}"; fi
  sleep 1
done
log "loop window over; status of the scratch demo:"
tail -1 $D/soak.jsonl | tee -a $D/capture.log
log "journal (pyefis, kiosk/Traceback):"
journalctl --user -u pyefis --since "@$T0" --no-pager 2>/dev/null | grep -E -i "kiosk|Traceback" | tail -20 | tee -a $D/capture.log
echo CAPTURE_DONE
