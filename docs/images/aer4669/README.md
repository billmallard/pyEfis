# AER-4669 size-scaled water vertex cap: what it costs, what it buys

Measurement only. Nothing here changes a published pack. `build_water_db.py`
gains an opt-in `--large-ring-cap N` (default 0 = off, output unchanged):
an inland ring larger than `--large-ring-area-km2` (default 10) keeps
`32 * sqrt(area / 10)` vertices, up to N, instead of 32. The rule is applied
per ring, so outer rings and island holes are both covered. Measured with
N = 1024, which works out to 32 vertices for a 10 km^2 pond, about 230 for
Mille Lacs (536 km^2), and the 1024 ceiling only for lakes of 10,000 km^2
and up.

## Renders

Each PNG is three `TerrainLayer._render` windows per row (600 x 600 widget,
north up, flat 500 m land, so every blue pixel is polygon fill). This is the
AER-4604 capture method.

- **Columns, left to right:** the published water-na 2026q2r6, a rebuild at
  cap 32, and a rebuild with the size-scaled cap.
- **Top row:** Natural Earth lakes kept, which is today's glass.
- **Bottom row:** OSM alone, which is the glass if the AER-4604 NE-duplicate
  drop also ships.

The rebuilds use Geofabrik `utah` / `minnesota` extracts fetched on
2026-11-02, built with the water-na recipe (`--max-vertices 32
--min-area-km2 0.05 --keep-fclass water reservoir`).

| File | Scene | Base vs scaled |
|------|-------|----------------|
| `mille_lacs_10nm.png` | 46.25 N 93.65 W, 10 NM | 3,855 px differ (NE kept), 5,506 (OSM only) |
| `gsl_10nm.png` | 41.1 N 112.5 W, 10 NM | 98 px / 210 px |
| `gsl_20nm.png` | 41.15 N 112.45 W, 20 NM | 39 px / 96 px |

20 NM is the widest range at which polygons draw over a terrain pack that
ships a water mask (`water_polygon_max_nm`). Past 20 NM, the `.wmask` built
from the same water pack draws instead, so the cap reaches wide ranges
through the mask build.

**Mille Lacs.** The rebuild at cap 32 reproduces the published row exactly:
180 vertices, 10 rings, outer ring 30. The scaled cap takes the outer ring to
225 vertices, and the straight east and south chords become the real shore.

**Great Salt Lake.** The coarse published row (row 1288146: 241 vertices,
14 rings, outer ring 63) is an artifact of the July OSM source, not of the
cap. Today's source fails the hole-verification check at every escalated cap,
so the builder stores the raw rings: 3,749 vertices, outer ring 3,571. That
happens at cap 32 as well. The builder logic that made r6 (`77a728e`) gives
the same 3,749 on today's source, and the builder has had only docs commits
since. So a plain rebuild today fixes the GSL, and the size-scaled cap adds
nothing there. It is still not a guarantee. If a future OSM edit lets the
check pass at cap 64, the GSL goes back to about 63 outer vertices, unless
the scaled cap is on.

The thin east-west line across the lake in the bottom row is the Lucin
Cutoff causeway (about 41.22 N). OSM splits the lake there. It is real, not
a seam.

## Pack size

| | Rows | Inland blob bytes, base -> scaled | File, base -> scaled |
|--|--|--|--|
| Utah rebuild | 997 | 3,982,592 -> 3,996,970 (+0.36%) | 4,272,128 -> 4,292,608 (+0.48%) |
| Minnesota rebuild | 13,676 | 34,743,058 -> 34,817,448 (+0.21%) | 37,990,400 -> 38,068,224 (+0.20%) |

**Full water-na (3,170,426,880 bytes, 1,245,400 inland rows).** This is an
estimate, not a rebuild.

- **+2.9 to +4.8 MB (+0.09% to +0.15%)**, applying the two states' inland
  growth to the pack's 1,337,101,028 inland blob bytes.
- **No more than about +15 MB (+0.47%)** as a pessimistic figure. The pack's
  own stored rings predict +364,770 vertices on 6,075 rings, which is 8.1 MB
  at the measured 22.2 bytes per added vertex. I multiplied that by the worse
  of the two calibrations.

That figure is not a bound. In Minnesota the real delta was 185% of the
prediction, for two reasons:

- A coarse ring's stored area can be far below its source area.
- A finer outer ring can fail hole verification and escalate the row's
  island rings as well. For example, row 13003's holes went from 8-16 to
  74-109 vertices.

A full NA rebuild means downloading about 63 regions and roughly a day of
single-thread build. That belongs to AVIONICS-DATA's publish, if this goes
ahead.

## Timing (Pi 5, the real target)

Run on `pyefis` (Pi 5, `~/pyEfis/.venv`, offscreen, live pyEfis running
alongside). There were 25 reps per variant, interleaved base / scaled so
drift lands on both. Each state rebuild is the whole database.

| Scene | Variant | Polys | Verts | Query cold ms | Render cold ms | Render warm ms |
|--|--|--|--|--|--|--|
| Brainerd lakes, 46.55 N 94.15 W, 20 NM | base | 1751 | 33,981 | 27.7 | 366.9 | 338.1 |
| | scaled | 1751 | 34,500 | 26.3 | 367.1 | 337.8 |
| Mille Lacs, 20 NM | base | 1116 | 21,851 | 16.4 | 286.6 | 267.5 |
| | scaled | 1116 | 22,396 | 16.5 | 286.8 | 267.6 |
| GSL, 20 NM | base | 299 | 19,229 | 6.4 | 195.6 | 189.2 |
| | scaled | 299 | 19,321 | 6.4 | 195.4 | 189.5 |

The median per-rep difference (scaled minus base) is between -1.4 and +0.6 ms
in every column. That is no measurable cost. The added vertices are 0.5% to
2.5% of what is in the window. The render runs on the map's worker thread,
not per frame.

Not measured:

- The SVS (`svs_gl`) draws the same rows as GL triangles. The scaled build
  adds the same 0.5% to 2.5% to those triangles. I did not time it.
- The `.wmask` build reads every polygon once, offline, and its output size
  does not depend on the cap.

## Regenerate

```bash
# 1. Source: Geofabrik extracts, water layer only (pyshp < 3: 3.x raises
#    on the empty shapes these files carry).
curl -L -o utah.zip https://download.geofabrik.de/north-america/us/utah-latest-free.shp.zip
curl -L -o minnesota.zip https://download.geofabrik.de/north-america/us/minnesota-latest-free.shp.zip
# extract gis_osm_water_a_free_1.* from each into src/ut and src/mn

# 2. Builds (water-na recipe), base and scaled, per state.
R="--max-vertices 32 --min-area-km2 0.05 --keep-fclass water reservoir"
for st in ut mn; do
  python tools/build_water_db.py db/${st}_base.sqlite  $R --osm-water src/$st/gis_osm_water_a_free_1.shp
  python tools/build_water_db.py db/${st}_s1024.sqlite $R --osm-water src/$st/gis_osm_water_a_free_1.shp \
      --large-ring-cap 1024 --large-ring-area-km2 10
done

# 3. Renders, Pi timing, full-pack size estimate.
export QT_QPA_PLATFORM=offscreen PYTHONPATH=src
python docs/images/aer4669/measure.py render /path/to/water-na.sqlite db docs/images/aer4669
python docs/images/aer4669/measure.py timing db 25
python docs/images/aer4669/measure.py size   /path/to/water-na.sqlite db
```
