#!/bin/sh
$HOME/pyefis-venv/bin/python - <<'P'
from fixgw import netfix
c = netfix.Client("127.0.0.1", 3490); c.connect()
r = lambda k: c.read(k)[1]
n = int(r("FPLCOUNT"))
print("route: %s FPLSEQ %s FPLLDSEQ %s FPLCOUNT %s ids %s" % (r("FPLNAME"), r("FPLSEQ"), r("FPLLDSEQ"), n, " ".join(r("FPL%dID" % i) for i in range(1, n + 1))))
print("import: FPLIMPSEQ %s FPLIMPDONE %s" % (r("FPLIMPSEQ"), r("FPLIMPDONE")))
c.disconnect()
P
