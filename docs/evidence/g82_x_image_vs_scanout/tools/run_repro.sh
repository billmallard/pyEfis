#!/bin/sh
# run.sh <label> <n> [repro opts...] -- env passes through. Under the bench lock.
L=$1; N=$2; shift 2
cd ~/bench-scratch/aer5478; mkdir -p out
export DISPLAY=:0
echo "$L $(date -u +%FT%T.%NZ) pyefis_head=$(git -C ~/src/pyEfis rev-parse --short HEAD) pyefis_pid=$(systemctl --user show -p MainPID --value pyefis) env=$(env | grep -E '^(vblank_mode|LIBGL_|QT_XCB_GL|MESA_|BIGREC)' | tr '\n' ' ') opts=$*" >> out/prov.txt
~/pyefis-venv/bin/python repro.py out/$L.app.jsonl $N "$@" &
AP=$!
# wait for the start record to learn the patch position
for i in $(seq 50); do grep -q '"start"' out/$L.app.jsonl 2>/dev/null && break; sleep 0.2; done
XY=$(python3 -c "import json;r=[json.loads(l) for l in open('out/$L.app.jsonl') if '\"start\"' in l][0];print(r['px'],r['py'])")
python3 recorder.py out/$L.rec.jsonl $XY 60 &
RP=$!
if [ -n "$BIGREC" ]; then ffmpeg -loglevel error -f x11grab -draw_mouse 0 -framerate 30 -video_size 648x1004 -i :0.0+1260,36 -pix_fmt gray -f rawvideo - > /dev/null 2>&1 & BP=$!; fi
wait $AP
sleep 1; kill $RP 2>/dev/null; [ -n "$BIGREC" ] && kill $BP 2>/dev/null; pkill -f "x11grab.*32x32" 2>/dev/null
python3 analyze.py out/$L.app.jsonl out/$L.rec.jsonl $L
