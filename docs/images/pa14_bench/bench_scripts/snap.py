"""snap.py OUT.json: snapshot the editor-published route block (slots + segment table) off the live bus."""
import json, sys
from nfx import NFX
SLOT = ("ID", "LAT", "LON", "TYPE", "PT", "CRS", "DST", "ALT", "SPD", "SGI", "FLAGS", "CTRLAT", "CTRLON", "TURN", "TA")
SEG = ("KIND", "ID", "ENT", "EXT", "FIRST", "LAST")
c = NFX()
count = int(float(c.read("FPLCOUNT")[0] or 0)); segcnt = int(float(c.read("FPLSEGCNT")[0] or 0))
snap = {"FPLCOUNT": count, "FPLSEGCNT": segcnt}
for k in ("FPLNAME", "FPLAPRTYPE", "FPLDBCYC", "FPLSEQ", "FPLLDSEQ", "FPLSTATE", "FPLACTLEG", "MAGVAR"):
    snap[k] = c.read(k)[0]
snap["slots"] = [{f: c.read(f"FPL{i}{f}")[0] for f in SLOT} for i in range(1, count + 1)]
snap["segs"] = [{f: c.read(f"FPLS{k}{f}")[0] for f in SEG} for k in range(1, segcnt + 1)]
json.dump(snap, open(sys.argv[1], "w"), indent=1)
for i, s in enumerate(snap["slots"], 1):
    print(i, s["ID"] or "-", s["PT"], s["SGI"], s["FLAGS"], s["ALT"], s["CRS"], s["DST"], s["TURN"], s["TA"], "%.5f %.5f" % (float(s["LAT"]), float(s["LON"])))
for k, s in enumerate(snap["segs"], 1):
    print("S%d" % k, s)
print({k: v for k, v in snap.items() if k not in ("slots", "segs")})
