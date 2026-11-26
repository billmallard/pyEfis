#!/bin/sh
C=$HOME/makerplane/fixgw/config
$HOME/pyefis-venv/bin/python - "$C" <<'P'
import sys, re
C = sys.argv[1]
p = C + "/preferences.yaml.custom"
s = open(p).read()
s = s.replace("includes:\n", "includes:\n  # AER-6706 EFB4b bench: revert from ~/bench-scratch/efb4b\n  FPL_EXCHANGE_CONFIG: connections/fpl_exchange.yaml\n", 1)
s = s.replace("enabled:\n", "enabled:\n  # AER-6706 EFB4b bench: revert from ~/bench-scratch/efb4b\n  FPL_EXCHANGE: true\n", 1)
open(p, "w").write(s)
p = C + "/connections/fpl_exchange.yaml"
s = open(p).read()
s2 = re.sub(r"\n  allow: \[\]\n", '\n  allow: ["127.0.0.0/8"]   # AER-6706 bench: this box only\n', s, count=1)
assert s2 != s
open(p, "w").write(s2)
P
flock -w 300 /tmp/pyefis-bench.lock sh -c 'sudo systemctl restart fixgw; sleep 6; systemctl --user restart pyefis.service' 9>&-
sleep 20
echo "fixgw: $(systemctl is-active fixgw) pyefis: $(systemctl --user is-active pyefis) 8080: $(ss -ltn | grep -c ':8080 ')"
