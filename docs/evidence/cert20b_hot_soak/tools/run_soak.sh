#!/bin/sh
# CERT20b (AER-6451) orchestrator, run ON the Pi 5 bench as a transient user unit:
#
#   systemd-run --user --unit=cert20b-orch -p RuntimeMaxSec=4h \
#     /bin/sh $HOME/bench-scratch/aer6451/tools/run_soak.sh <run-label>
#
# One continuous run: the live pyEfis checkout (~/pyEfis, whatever it is on) is
# started under soak_probe.py in place of pyefis.service, with the screen
# cycler on, soak_feed.py flying an orbit through the bench fix-gateway and
# soak_thermal.py sampling. It stops when throttling has been active for
# HOT_S, or when the SoC temperature has not set a new high (by more than
# PLATEAU_C) for HOT_S, never before MIN_S, and at MAX_S regardless. The
# analysis takes the cool window from the start and the hot window from the end.
#
# Restore is unconditional: the probe unit's ExecStopPost starts
# pyefis.service again however the probe ends, and this script also stops
# every unit it started on exit. The pyEfis checkout, its config and the
# gateway config are not touched.
set -u
RUN=${1:?run label}
D=$HOME/bench-scratch/aer6451
T=$D/tools
O=$D/out/$RUN
REPO=$HOME/pyEfis
PY=$REPO/.venv/bin/python
MIN_S=${MIN_S:-1800}
MAX_S=${MAX_S:-10800}
HOT_S=${HOT_S:-600}
PLATEAU_C=${PLATEAU_C:-0.5}
WARM_S=${WARM_S:-90}
mkdir -p "$O"
LOG=$O/orch.log
say() { echo "$(date -u +%FT%TZ) $*" >> "$LOG"; }

cleanup() {
    say "cleanup"
    systemctl --user stop cert20b-feed.service cert20b-thermal.service 2>/dev/null
    systemctl --user stop cert20b-probe.service 2>/dev/null
    n=0
    while [ $n -lt 120 ] && ! systemctl --user is-active -q pyefis.service; do
        sleep 2; n=$((n+2))
        [ $n -eq 20 ] && systemctl --user start pyefis.service
    done
    say "pyefis.service $(systemctl --user is-active pyefis.service) MainPID=$(systemctl --user show -p MainPID --value pyefis.service)"
    echo done > "$O/DONE"
}
trap cleanup EXIT
trap 'say "signal"; exit 1' INT TERM

platform() {  # platform <label> <pid>
    "$PY" -c "import sys,json; sys.path.insert(0,'$REPO/tools'); import evidence_sidecar as e; print(json.dumps(e.describe_platform(pid='$2'), sort_keys=True))" > "$O/platform_$1.json" 2>> "$LOG"
}

say "run $RUN start; pyEfis $(git -C $REPO rev-parse HEAD) $(git -C $REPO rev-parse --abbrev-ref HEAD); fix-gateway $(git -C $HOME/fix-gateway rev-parse HEAD)"
say "load $(cat /proc/loadavg) soc $(cat /sys/class/thermal/thermal_zone0/temp) throttled $(vcgencmd get_throttled)"
platform start_idle "$(systemctl --user show -p MainPID --value pyefis.service)"

flock -o -w 900 /tmp/pyefis-bench.lock sh -c '
  echo "owner=AVIONICS issue=AER-6451 mode=soak action=stop-pyefis pid=$$ since=$(date -u +%FT%TZ)" > /tmp/pyefis-bench.lock.owner
  systemctl --user stop pyefis.service' || { say "lock/stop failed"; exit 2; }
say "pyefis.service $(systemctl --user is-active pyefis.service)"

UNTIL=$(( $(date +%s) + MAX_S + 600 ))
systemd-run --user --unit=cert20b-probe -p RuntimeMaxSec=$((MAX_S + 900)) \
  -p WorkingDirectory=$REPO -E QT_QPA_PLATFORM=eglfs \
  -E QT_QPA_EGLFS_KMS_CONFIG=$HOME/eglfs_hdmi.json -E PYTHONPATH=$REPO/src \
  -E SOAK_OUT=$O/probe.csv -E SOAK_DWELL=${DWELL:-15} \
  -p ExecStopPost="/usr/bin/systemctl --user start pyefis.service" \
  "$PY" $T/soak_probe.py >> "$LOG" 2>&1 || { say "probe unit failed to start"; exit 3; }
n=0; PPID_=""
while [ $n -lt 90 ]; do
    PPID_=$(systemctl --user show -p MainPID --value cert20b-probe.service)
    [ -n "$PPID_" ] && [ "$PPID_" != 0 ] && grep -q '^I,' "$O/probe.csv" 2>/dev/null && break
    sleep 2; n=$((n+2))
done
grep -q '^I,' "$O/probe.csv" 2>/dev/null || { say "probe never installed"; exit 4; }
FGW=$(systemctl --user show -p MainPID --value fixgw.service)
say "probe pid $PPID_ fixgw pid $FGW"
systemd-run --user --unit=cert20b-thermal -p RuntimeMaxSec=$((MAX_S + 900)) \
  /usr/bin/python3 $T/soak_thermal.py --out $O/thermal.jsonl --until $UNTIL --pid $PPID_ --pid $FGW >> "$LOG" 2>&1
sleep "$WARM_S"
platform start "$PPID_"
systemd-run --user --unit=cert20b-feed -p RuntimeMaxSec=$((MAX_S + 900)) \
  /usr/bin/python3 $T/soak_feed.py --out $O/roll_writes.csv --until $UNTIL >> "$LOG" 2>&1
T0=$(date +%s)
say "feed started; T0=$T0"
echo "$T0" > "$O/T0"

while :; do
    sleep 30
    now=$(date +%s); el=$((now - T0))
    for u in cert20b-probe cert20b-feed cert20b-thermal; do
        systemctl --user is-active -q $u.service || { say "$u not active at ${el}s"; exit 5; }
    done
    v=$(/usr/bin/python3 - "$O/thermal.jsonl" "$T0" "$HOT_S" "$PLATEAU_C" <<'EOF'
import json, sys
p, t0, hot, tol = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
rows = [json.loads(l) for l in open(p) if l.strip()]
rows = [r for r in rows if r["wall"] >= t0]
now = rows[-1]["wall"]
thr = [r for r in rows if r["throttled"] and int(r["throttled"].split("=")[1], 16) & 0xE]
first_thr = thr[0]["wall"] - t0 if thr else -1
# per-minute mean temperature; the high-water mark before the last HOT_S
mins = {}
for r in rows:
    mins.setdefault(int((r["wall"] - t0) // 60), []).append(r["soc_c"])
m = {k: sum(v) / len(v) for k, v in mins.items() if len(v) >= 10}
cut = (now - t0 - hot) / 60.0
before = [v for k, v in m.items() if k < cut]
after = [v for k, v in m.items() if k >= cut]
plateau = bool(before and after and max(after) <= max(before) + tol)
print("%d %d %.1f %d" % (first_thr, plateau, rows[-1]["soc_c"], len(rows)))
EOF
)
    set -- $v
    echo "el=$el first_thr=$1 plateau=$2 soc=$3 n=$4" > "$O/STATUS"
    if [ "$1" -ge 0 ] && [ $((el - $1)) -ge "$HOT_S" ]; then say "stop: throttled since ${1}s, held ${HOT_S}s"; echo throttle > "$O/STOP_REASON"; break; fi
    if [ "$el" -ge "$MIN_S" ] && [ "$2" = 1 ]; then say "stop: plateau at ${el}s (soc $3)"; echo plateau > "$O/STOP_REASON"; break; fi
    if [ "$el" -ge "$MAX_S" ]; then say "stop: MAX_S"; echo max > "$O/STOP_REASON"; break; fi
done
platform end "$PPID_"
say "load $(cat /proc/loadavg) soc $(cat /sys/class/thermal/thermal_zone0/temp) throttled $(vcgencmd get_throttled)"
