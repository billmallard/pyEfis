F=~/pyefis-venv/bin/fixgwc; P=$(pgrep -f bin/pyefis | head -1)
w(){ $F -x "write $1 $2" >/dev/null; sleep 0.2; }
turn(){ k=$1; n=$2; i=0; while [ $i -lt $n ]; do w $k 1; i=$((i+1)); done; }
push(){ w BTN3 True; w BTN3 False; sleep 0.6; }
letter(){ # $1 = alphabet index (A=0); from blank, +1 reaches A
  turn ENC3 $(( $1 + 1 )); }
ident(){ first=1; for c in "$@"; do [ $first = 1 ] || w ENC4 1; first=0; letter $c; done; push; sleep 1; }
shot(){ rm -f /tmp/pyefis_screenshot.png; kill -USR1 $P; sleep 2; cp /tmp/pyefis_screenshot.png ~/bench-scratch/aer-810/$1.png; }
rd(){ for k in FPLCOUNT FPLSEQ FPL1ID FPL2ID FPL3ID FPL4ID; do printf "%s=%s " $k "$($F -x "read $k" 2>&1 | tail -1)"; done; echo; }
echo "before: $(rd)"
DISPLAY=:0 xdotool mousemove 403 972 click 1; sleep 4
DISPLAY=:0 xdotool mousemove 1345 13 click 1; sleep 2
w ENC3 1; push                     # highlight, take control
turn ENC3 2; push                  # KSBA row -> ADD WPT
ident 10 3 0 11                    # K D A L
echo "after KDAL: $(rd)"
turn ENC3 3; push                  # KSBA, KDAL rows -> ADD WPT
ident 10 6 15 12                   # K G P M
echo "after KGPM: $(rd)"
sleep 1; shot fix_after_reentry
