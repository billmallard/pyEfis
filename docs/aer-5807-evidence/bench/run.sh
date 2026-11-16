#!/bin/sh
# AER-5807 bench run: private gateway on 127.0.0.1:3492, the scripted
# source, and the real panel. Touches no live service, checkout or config.
#   run.sh <fix-gateway clone> <pyEfis clone> <out dir> <layout> <size>
set -u
FGW=$1; PYEFIS=$2; OUT=$3; LAYOUT=${4:-full}; SIZE=${5:-640x260}
PY=${PY:-python3}
mkdir -p "$OUT"
CFG="$OUT/cfg"
rm -rf "$CFG"; cp -r "$FGW/src/fixgw/config" "$CFG"
cp "$PYEFIS/docs/aer-5807-evidence/bench/bench.yaml" "$CFG/bench.yaml"
HERE="$PYEFIS/docs/aer-5807-evidence/bench"
PYTHONPATH="$FGW/src" $PY "$FGW/fixGw.py" --config-file "$CFG/bench.yaml" \
    > "$OUT/fixgw.log" 2>&1 &
echo $! > "$OUT/fixgw.pid"
sleep 4
$PY "$HERE/ap_source.py" --port 3492 --run-s 40 --log "$OUT/source.jsonl" &
echo $! > "$OUT/source.pid"
QT_QPA_PLATFORM=offscreen PYTHONPATH="$PYEFIS/src" $PY "$HERE/drive.py" \
    --port 3492 --out "$OUT" --layout "$LAYOUT" --size "$SIZE"
RC=$?
kill "$(cat "$OUT/source.pid")" 2>/dev/null
kill "$(cat "$OUT/fixgw.pid")" 2>/dev/null
echo "RC=$RC"
