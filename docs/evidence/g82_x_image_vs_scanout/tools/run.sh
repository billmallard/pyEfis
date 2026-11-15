#!/bin/sh
# run.sh <label> <cycles>: G79 recorder + cycles on the isolated G82 stack.
# The caller holds the bench lock (on-box holder, ../HOLD).
L=$1; N=$2; cd ~/bench-scratch/aer5478/g79
[ -f ../HOLD ] && grep -q held ../hold.log && ! grep -q released ../hold.log || { echo "lock holder not live"; exit 9; }
prov() { echo "$1 $(date -u +%FT%T.%NZ) stack_head=$(git -C ../stack/pyEfis rev-parse --short HEAD) pyefis=$(pgrep -f "aer5478/stack/pcfg" | head -1) env=$(tr '\0' '\n' < /proc/$(pgrep -f "aer5478/stack/pcfg" | head -1)/environ | grep -E '^(vblank_mode|LIBGL_|QT_XCB_GL|MESA_|QT_)' | tr '\n' ' ') load=$(cut -d' ' -f1-3 /proc/loadavg)" >> prov_$L.txt; }
prov start
mkdir -p glass_$L
setsid -f ~/pyefis-venv/bin/python glassrec.py glass_$L 1260 36 648 1004 30 </dev/null >glass_$L/rec.err 2>&1
[ -n "$KMS" ] && { mkdir -p glass_${L}k; setsid -f ~/pyefis-venv/bin/python kmsrec.py glass_${L}k 1260 36 648 1004 30 </dev/null >glass_${L}k/rec.err 2>&1; }
sleep 2
python3 cycle.py $L $N
sleep 3
pkill -f "glassrec.py glass_$L"; [ -n "$KMS" ] && sudo -n pkill -f "kmsgrab"
prov end
cp /tmp/g79_probe.log probe.log
~/pyefis-venv/bin/python analyze.py . $L > analyze_$L.txt
tail -7 analyze_$L.txt; cp probe.log probe_$L.log
[ -n "$KMS" ] && { ln -sf sends_$L.jsonl sends_${L}k.jsonl; ~/pyefis-venv/bin/python analyze.py . ${L}k > analyze_${L}k.txt; echo "== scanout"; tail -7 analyze_${L}k.txt; }
 cat prov_$L.txt
