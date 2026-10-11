#!/bin/sh
# AER-3036 / AER-808: FP7 on-glass captures on the Beelink, #285 staged.
# Run under the bench lock: flock -o -w 900 /tmp/pyefis-bench.lock sh fp7_glass.sh
# Snapshots every config file and FIX key it touches and restores them on exit.
set -u
W=$HOME/bench-scratch/aer3036
mkdir -p "$W/bak" "$W/out"
C=$HOME/makerplane/pyefis/config
G=$HOME/makerplane/fixgw/config
D=$HOME/src/pyEfis/docs/images/fp7_hsi
PY=$HOME/pyefis-venv/bin/python
export DISPLAY=:0

cp -p "$C/main/default.yaml" "$W/bak/default.yaml"
cp -p "$C/screens/flightplan.yaml" "$W/bak/flightplan.yaml"
cp -p "$G/flightplan_state.json" "$W/bak/flightplan_state.json"
cp -p "$G/persist_state.json" "$W/bak/persist_state.json"

# Prior values of every key written below.
PYTHONPATH=$D $PY - > "$W/bak/keys.txt" <<'EOF'
from fixio import Fix
f = Fix()
for k in ["LAT", "LONG", "TRACK", "MAGVAR", "GS", "GPSSRC", "NAVSRC", "FPLCOUNT", "FPLNAME", "FPLSEQ"]:
    print(k, f.r(k)[0], f.r(k)[1])
EOF
cat "$W/bak/keys.txt"

restore() {
    echo "== restore"
    [ -n "${FEED:-}" ] && kill "$FEED" 2>/dev/null; wait 2>/dev/null
    cp -p "$W/bak/default.yaml" "$C/main/default.yaml"
    cp -p "$W/bak/flightplan.yaml" "$C/screens/flightplan.yaml"
    # Re-publish the plan that was stored (KGPM-KGPM, mode NONE): load_route
    # resets the engine to NONE, so this both clears the ACT and puts the
    # stored route back. Then the scalar keys.
    PYTHONPATH=$D W=$W $PY - <<'EOF'
import json, os
from fixio import Fix
W = os.environ["W"]
f = Fix()
st = json.load(open(W + "/bak/flightplan_state.json"))
for i, wp in enumerate(st["route"], 1):
    f.w("FPL%dID" % i, wp["id"]); f.w("FPL%dLAT" % i, wp["lat"])
    f.w("FPL%dLON" % i, wp["lon"]); f.w("FPL%dTYPE" % i, wp["type"])
f.w("FPLCOUNT", len(st["route"])); f.w("FPLNAME", st["name"])
f.w("FPLSEQ", int(float(f.r("FPLSEQ")[0] or 0)) + 1)
prior = dict(l.split()[:2] for l in open(W + "/bak/keys.txt") if len(l.split()) >= 2)
for k in ["MAGVAR", "GS", "GPSSRC", "NAVSRC", "TRACK", "LAT", "LONG"]:
    if prior.get(k, "None") != "None":
        f.w(k, prior[k])
import time; time.sleep(1.5)
for k in ["FPLSTATE", "FPLNAME", "FPLCOUNT", "NAVSRC", "GPSSRC", "LAT", "LONG"]:
    print("after", k, f.r(k))
EOF
    sleep 2
    cp -p "$W/bak/persist_state.json" "$G/persist_state.json"
    echo "-- state file now:"; python3 -c "import json;d=json.load(open('$G/flightplan_state.json'));print(d['name'],d['mode'],d['act_leg'],len(d['route']))"
    cat "$G/persist_state.json"; echo
    diff -q "$W/bak/default.yaml" "$C/main/default.yaml" && diff -q "$W/bak/flightplan.yaml" "$C/screens/flightplan.yaml" && echo "config restored"
    systemctl --user restart pyefis.service; sleep 15
    echo "pyefis: $(systemctl --user is-active pyefis.service)"
}
trap restore EXIT

# Route + engine selects, from the FP7 HSI driver's route.
PYTHONPATH=$D $PY - <<'EOF'
import time
from fixio import Fix
from hsi_chain_points import ROUTE
f = Fix()
for i, (ident, la, lo, ty) in enumerate(ROUTE, 1):
    f.w("FPL%dID" % i, ident); f.w("FPL%dLAT" % i, la); f.w("FPL%dLON" % i, lo); f.w("FPL%dTYPE" % i, ty)
f.w("FPLCOUNT", len(ROUTE)); f.w("FPLNAME", "KSBA-KSMX")
f.w("FPLSEQ", int(float(f.r("FPLSEQ")[0] or 0)) + 1)
f.w("MAGVAR", 0.0); f.w("GS", 120.0); f.w("GPSSRC", 0); f.w("NAVSRC", 2)
time.sleep(0.5)
f.w("FPLCMD", "901 ACT 2"); time.sleep(0.5)
print("ACT ack", f.r("FPLCMDACK"))
EOF

# Keep the synthetic position fresh: 0.5 nm right of the KSBA-GVO midpoint.
PYTHONPATH=$D timeout 300 $PY - <<'EOF' &
import time
from fixio import Fix
from hsi_chain_points import points
f = Fix()
_, pos, _ = points()[1]
n = 0
while True:
    n += 1
    f.w("LAT", pos[0] + n * 1e-9); f.w("LONG", pos[1]); f.w("TRACK", 289.0)
    time.sleep(0.5)
EOF
FEED=$!
sleep 3

dump() {
    PYTHONPATH=$D $PY - <<'EOF'
from fixio import Fix
f = Fix()
for k in ["FPLSTATE", "FPLACTLEG", "WPFROM", "WPNAME", "WPNEXT", "FPLCRS", "FPLXTK",
          "COURSE", "CDI", "TOFROM", "WPDIS", "WPETE", "NAVSRC", "GPSSRC", "LAT", "LONG"]:
    print(k, *f.r(k))
EOF
}

shot() {  # $1 = screen, $2 = out name
    sed -i "s/^\(  defaultScreen:\).*/\1 $1/" "$C/main/default.yaml"
    systemctl --user restart pyefis.service
    sleep 18
    # Boot lands on the NAVIGATION DATA status screen; tap Continue.
    xdotool mousemove 402 971 click 1; sleep 8
    xdotool mousemove 1919 1079
    echo "pyefis ($1): $(systemctl --user is-active pyefis.service)"
    journalctl --user -u pyefis.service --since "-25s" --no-pager | grep -i -E "traceback|not found" || echo "journal: clean"
    dump > "$W/out/$2.keys.txt"
    ffmpeg -loglevel error -y -f x11grab -video_size 1920x1080 -i :0 -frames:v 1 "$W/out/$2.png"
    ls -l "$W/out/$2.png"
}

# #285's stock flight-plan screen, which carries the chip.
cp "$HOME/src/pyEfis/src/pyefis/config/screens/flightplan.yaml" "$C/screens/flightplan.yaml"
shot PFD fp7_pfd_hsi_gps
shot FLIGHTPLAN fp7_flightplan_nav_status
cat "$W/out/fp7_flightplan_nav_status.keys.txt"
