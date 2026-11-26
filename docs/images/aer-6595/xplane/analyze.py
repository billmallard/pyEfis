"""SVSFLOOR1 survey: X-Plane ground (ALT - AGL) against the surface the SVS
draws (NASR runway polygon, svs.py geometry) and GLO-30, over each runway."""
import csv, math, sys, statistics as st
sys.path.insert(0, "src")
from pyefis.instruments.ai.airport_db import NASRAirportDB
from pyefis.instruments.ai.svs import TileCache
from pathlib import Path
db = NASRAirportDB("/data/makerplane-data/navdata/current/airports.sqlite")
tiles = TileCache(Path("/data/makerplane-data/terrain/tiles"))
for name in sys.argv[1:]:
    icao = name.split("-")[0].upper()
    rows = [r for r in csv.reader(open(f"xp/{name}/agl.csv"))]
    lat0, lon0 = float(rows[len(rows)//2][1]), float(rows[len(rows)//2][3])
    aps = [a for a in db.airports_in_range(lat0, lon0, 60) if a.icao == icao]
    if not aps:
        print(name, "airport not found"); continue
    ap = aps[0]
    per = {}
    for r in rows:
        lat, lon, alt, agl = float(r[1]), float(r[3]), float(r[5]), float(r[7])
        c = math.cos(math.radians(lat))
        for w in ap.runways:
            dl = w.thr2_lat - w.thr1_lat; dm = (w.thr2_lon - w.thr1_lon) * c
            L2 = dl*dl + dm*dm
            pl = lat - w.thr1_lat; pm = (lon - w.thr1_lon) * c
            f = (pl*dl + pm*dm) / L2
            off = abs(pl*dm - pm*dl) / math.sqrt(L2) * 364491.0
            if 0 <= f <= 1 and off <= w.width_ft / 2:
                nasr = w.thr1_elev_ft + f * (w.thr2_elev_ft - w.thr1_elev_ft)
                glo = tiles.elevation(lat, lon) * 3.28084
                per.setdefault(w.name, []).append((alt - agl, nasr, glo, agl, f))
    for rw, s in per.items():
        d = [x[0] - x[1] for x in s]; g = [x[2] - x[1] for x in s]; xg = [x[0] - x[2] for x in s]
        print(f"{icao} {rw}: n={len(s)} f={min(x[4] for x in s):.2f}-{max(x[4] for x in s):.2f} "
              f"AGL {min(x[3] for x in s):.0f}-{max(x[3] for x in s):.0f} ft | "
              f"XP-NASR med {st.median(d):+.1f} min {min(d):+.1f} max {max(d):+.1f} | "
              f"GLO30-NASR med {st.median(g):+.1f} max {max(g):+.1f} | XP-GLO30 med {st.median(xg):+.1f}")
