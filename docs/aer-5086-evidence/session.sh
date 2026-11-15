#!/bin/sh
# AER-5086 bench session: enable fixgw onspeed on the feeder pty, fly, grab, revert.
set -u
D=$HOME/bench-scratch/aer5086; C=$HOME/makerplane/fixgw/config
PY=$HOME/pyefis-venv/bin/python
TS=$(date -u +%Y%m%dT%H%M%SZ)
cd "$D" || exit 1
rm -f *.png frames.json live_sweep.json
for f in default.yaml preferences.yaml.custom connections/onspeed.yaml; do cp -p "$C/$f" "$C/$f.bak-aer5086-$TS"; done
echo "backups: $TS"
restore() {
  kill "$FEED" 2>/dev/null
  for f in default.yaml preferences.yaml.custom connections/onspeed.yaml; do cp -p "$C/$f.bak-aer5086-$TS" "$C/$f"; done
  sudo -n systemctl restart fixgw; sleep 5
  echo "restored configs; fixgw $(systemctl is-active fixgw)"
  grep -c ONSPEED "$C/default.yaml" "$C/preferences.yaml.custom"; grep -n "^  load\|^  port" "$C/connections/onspeed.yaml"
}
echo live > "$D/ctl"
setsid "$PY" "$D/feeder.py" "$D/ctl" > "$D/feeder.out" 2> "$D/feeder.err" < /dev/null &
FEED=$!
trap restore EXIT
sleep 2
PTY=$(head -1 "$D/feeder.out"); echo "feeder pid $FEED pty $PTY"
[ -n "$PTY" ] || { cat "$D/feeder.err"; exit 2; }
"$PY" - "$C" "$PTY" <<'PYEOF'
import sys
c, pty = sys.argv[1], sys.argv[2]
p = f"{c}/default.yaml"; s = open(p).read()
assert "  - KNOBSTER_CONFIG\n" in s and "ONSPEED_CONFIG" not in s
open(p, "w").write(s.replace("  - KNOBSTER_CONFIG\n", "  - KNOBSTER_CONFIG\n  - ONSPEED_CONFIG\n", 1))
p = f"{c}/preferences.yaml.custom"; s = open(p).read()
assert "includes:\n" in s and "ONSPEED" not in s
open(p, "w").write(s.replace("includes:\n", "includes:\n  ONSPEED_CONFIG: connections/onspeed.yaml\n", 1))
p = f"{c}/connections/onspeed.yaml"; s = open(p).read()
s = s.replace("  load: no\n", "  load: yes\n").replace("  port: /dev/ttyUSB0\n", f"  port: {pty}\n")
assert "load: yes" in s and pty in s
open(p, "w").write(s)
print("configs patched")
PYEOF
sudo -n systemctl restart fixgw; sleep 6
echo "fixgw $(systemctl is-active fixgw)"
journalctl -u fixgw --since "-15s" --no-pager | grep -i -E "onspeed|traceback|error" | tail -5
sleep 10  # pyEfis is a user unit here and reconnects to fixgw on its own
echo "pyefis $(systemctl --user is-active pyefis)"
"$PY" "$D/driver.py" "$D" "$D/ctl"
echo "driver rc=$?"
