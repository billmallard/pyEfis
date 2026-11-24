#!/bin/sh
# AER-6346: CAS3 look on the Beelink. A private fix-gateway (dev, own port)
# and a second pyEfis from the PR branch, windowed over the live display for
# about a minute per placement; the live services and checkouts are untouched.
set -e
D=$HOME/bench-scratch/aer6346
rm -rf "$D"; mkdir -p "$D"
git clone -q --depth 1 -b aer-6346/cas-window https://github.com/billmallard/pyEfis "$D/pyefis"
git clone -q --depth 1 -b dev https://github.com/billmallard/fix-gateway "$D/fgw"
echo "pyEfis $(git -C $D/pyefis rev-parse --short HEAD) fix-gateway $(git -C $D/fgw rev-parse --short HEAD)"
cd "$D/pyefis"
export DISPLAY=:0 QT_QPA_PLATFORM=xcb
for P in A B C; do
  timeout 200 "$HOME/pyefis-venv/bin/python" docs/aer-6346-evidence/bench.py \
    --fgw "$D/fgw" --out "$D/out" --render-only --placement $P --port 34991 \
    > "$D/render-$P.log" 2>&1 || echo "render $P rc=$?"
  grep -E "drawn|RESULT" "$D/render-$P.log" | sed "s/^/$P /"
done
ls "$D/out"
