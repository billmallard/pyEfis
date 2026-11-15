#!/bin/sh
# usage: render.sh <tree-dir> <outdir>
cd "$1" || exit 1
OUT=$2; mkdir -p $OUT
for spec in "KSBA 34.42619166 -119.84149277" "KDFW 32.89723305 -97.03769472" "0C0 42.40247222 -88.63238888"; do
  set -- $spec
  for R in 1 2 5 10; do
    LAT=$(python3 -c "print($2 - 0.25*$R/60.0)")
    QT_QPA_PLATFORM=offscreen timeout 120 ~/pyefis-venv/bin/python tools/render_map_style_evidence.py \
      --data /data/makerplane-data --lat $LAT --lon $3 --track 0 --range $R \
      --styles standard --out $OUT/tmp >/dev/null 2>$OUT/err_$1_$R.log
    echo "$1 $R rc=$?"
    mv $OUT/tmp/map_standard.png $OUT/$1_${R}nm.png 2>/dev/null
  done
done
