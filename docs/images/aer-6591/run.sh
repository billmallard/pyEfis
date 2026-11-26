#!/bin/sh
# run.sh <dev|branch>: SITL + mavlink plugin in a private fixgw (fix-gateway dev,
# netfix 127.0.0.1:3492), and pyEfis from pye-<side> on a copy of the live
# config with the map in caution mode, fullscreen over the kiosk. Run under
# the bench lock (flock -o).
S=~/bench-scratch/aer6591; L=$1; cd $S/sitl || exit 1
rm -rf $S/out/$L; mkdir -p $S/out/$L/png
cat > $S/start_pyefis_$L.sh <<EOS
#!/bin/sh
PYTHONPATH=$S/pye-$L/src DISPLAY=:0 QT_QPA_PLATFORM=xcb setsid -f ~/pyefis-venv/bin/python -m pyefis.main --config-file $S/pcfg/default.yaml >"\$1" 2>&1 </dev/null
EOS
chmod +x $S/start_pyefis_$L.sh
export BARO_NETFIX_PORT=3492 BARO_SETTLE=3
export BARO_ON_SERVER="$S/start_pyefis_$L.sh $S/out/$L/pyefis.out; sleep 15"
export BARO_ON_SAMPLE="DISPLAY=:0 ffmpeg -loglevel error -y -f x11grab -draw_mouse 0 -i :0.0 -frames:v 1 $S/out/$L/png/\$1.png"
echo "side=$L fgw=$(git -C $S/fgw-dev rev-parse --short HEAD) pyefis=$(git -C $S/pye-$L rev-parse --short HEAD) arduplane=$(cat firmware-version.txt | head -1) start=$(date -u +%FT%TZ)" > $S/out/$L/prov.txt
~/pyefis-venv/bin/python baro_session.py $S/fgw-dev $S/out/$L/session
pkill -f "aer6591/pcfg/default.yaml" ; sleep 1
pgrep -af "aer6591" | grep -v "pgrep\|run.sh" || echo "stack down"
echo "end=$(date -u +%FT%TZ)" >> $S/out/$L/prov.txt
