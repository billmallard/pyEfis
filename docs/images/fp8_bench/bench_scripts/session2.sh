#!/bin/sh
# FP8 (AER-809) session 2 start/stop -- session.sh with the reconnecting
# logger and the SYN1 procedure route. Session-only flags, reverted by stop.
#   sh session2.sh flags-on            -> RREF position feed + DATA_RECORDER, fixgw restart
#   sh session2.sh logger <tag>        -> 1 Hz logger to fp8_<tag>.csv
#   sh session2.sh stop                -> logger off, both flags restored from the backups, fixgw restart
set -e
D=$HOME/bench-scratch/aer809; C=$HOME/makerplane/fixgw/config; TS=$(date -u +%Y%m%dT%H%M%SZ)
PY=$HOME/pyefis-venv/bin/python
case "$1" in
flags-on)
  flock -w 300 /tmp/pyefis-bench.lock sh -c "
    cp -p $C/connections/xplane.yaml $C/connections/xplane.yaml.bak-aer809-session-$TS
    cp -p $C/preferences.yaml.custom $C/preferences.yaml.custom.bak-aer809-$TS
    grep -q 'AER-809 FP8 SESSION' $C/connections/xplane.yaml || sed -i '/^    dataref_hz: 10/e cat $D/rref_block.txt' $C/connections/xplane.yaml
    grep -q 'AER-809 FP8 SESSION' $C/preferences.yaml.custom || sed -i '/^  KNOBSTER: true/a\\\\n  # AER-809 FP8 SESSION-ONLY: record the bench flight. REVERT after FP8.\\n  DATA_RECORDER: true' $C/preferences.yaml.custom
    sudo -n systemctl restart fixgw; sleep 10; systemctl is-active fixgw"
  echo "flags on $TS"; grep -c 'AER-809 FP8 SESSION' $C/connections/xplane.yaml $C/preferences.yaml.custom || true ;;
logger)
  cd $D; setsid nohup $PY fp8_logger2.py fp8_$2.csv > logger_$2.out 2>&1 < /dev/null &
  echo "logger started" ;;
stop)
  pkill -f fp8_logger2.py || true
  flock -w 300 /tmp/pyefis-bench.lock sh -c "
    cp -p \$(ls -t $C/connections/xplane.yaml.bak-aer809-session-* | head -1) $C/connections/xplane.yaml
    cp -p \$(ls -t $C/preferences.yaml.custom.bak-aer809-* | head -1) $C/preferences.yaml.custom
    sudo -n systemctl restart fixgw; sleep 10; systemctl is-active fixgw"
  grep -c 'AER-809 FP8 SESSION' $C/connections/xplane.yaml $C/preferences.yaml.custom || true
  echo "stopped $TS" ;;
esac
