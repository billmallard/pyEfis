# SVS Water Database

The SVS water-polygon overlay reads from a sqlite file produced by
`tools/build_water_db.py` out of vector shapefiles. This doc captures
the data sources, the current build/deploy workflow, the perf
constraints we hit on the first deploy, and the shape of the
download-and-update tool we still need to build.

## Data sources (verified working)

### OSM coastline-derived water polygons (oceans + seas)

- **Source**: https://osmdata.openstreetmap.de/data/water-polygons.html
- **File**: `water-polygons-split-4326.zip`
- **Direct download**:
  <https://osmdata.openstreetmap.de/download/water-polygons-split-4326.zip>
- **Projection**: EPSG:4326 (WGS-84) — required (pyEfis works in
  geographic coordinates)
- **Format**: shapefile (.shp + sidecars), pre-cut into manageable
  chunks
- **Size**: ~620 MB compressed, ~3.4 GB uncompressed (.shp 1.2 GB)
- **Count**: 53,326 shapes, fragmented into 876,554 rings
- **Refresh cadence**: weekly upstream; for our purposes monthly /
  on-demand is fine — coastlines don't move
- **Pi dest dir**: `~/pyEfis/water/`

### Natural Earth 10m physical lakes

- **Source**: https://www.naturalearthdata.com/downloads/10m-physical-vectors/
- **Direct download**:
  <https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_lakes.zip>
- **Size**: ~5 MB zipped, 2.6 MB .shp
- **Count**: 1,355 shapes / 1,597 rings worldwide
- **Coverage**: every major lake on the planet; no inland rivers,
  no farm ponds. Good enough for SVS baseline.
- **Refresh cadence**: Natural Earth releases roughly annually;
  we don't really need to track it

### NOT YET INGESTED — future candidates

- **OSM inland water (lakes / rivers / reservoirs at full OSM
  detail)**: would catch every lake and wider river worldwide.
  Comes from running a full OSM .pbf extract through osmium /
  imposm with the right tag filters. ~10 GB+ world; ~1 GB CONUS.
  Partially in place: `tools/fetch_geofabrik_water.py` ingests
  Geofabrik's per-region `gis_osm_water_a` shapefiles, and for
  regions Geofabrik no longer ships as shapefiles (past its free-shp
  size cap: BC + Nunavut as of 2026-07) it falls back to extracting
  the same layer from the region's `.osm.pbf` with pyosmium
  (issue #104; tag->fclass mapping empirically pinned against the
  real layer — see `water_fclass` in that tool).
- **NOAA GSHHG hierarchical shorelines**: alternate ocean polygon
  set with built-in LOD (full / high / intermediate / low / crude
  resolutions). Could replace OSM for ocean if we want
  pre-decimated tiers without re-running our own decimation.

## Build workflow today

```bash
PYTHONPATH="C:/pylib;src" python tools/build_water_db.py \
    /path/to/water.sqlite \
    --ocean /path/to/water-polygons-split-4326/water_polygons.shp \
    --lake  /path/to/ne_10m_lakes/ne_10m_lakes.shp \
    --max-vertices 32
```

- `--max-vertices N` (default 32) stride-decimates each polygon at
  ingest time. Per-polygon BLOB shrinks from ~50–100 KB (raw OSM
  detail) to ~512 bytes. Critical for runtime perf — see "perf
  notes" below.
- `--ocean` / `--lake` / `--river` / `--osm-water` flags set the
  `kind` field per source; pyEfis uses `kind == 'ocean'` to skip
  the SRTM lookup since ocean = sea level by definition.
- `--text input.txt` is a documented hand-rollable format useful
  for tiny test datasets without pulling pyshp into the runtime
  environment.
- `--waterway path/to/gis_osm_waterways_free_1.shp` imports OSM
  waterway CENTERLINES into the separate `waterway_lines` polyline
  table (rivers as lines, issue #39 — see the section below), not
  the polygon store.

The build is currently driven by hand from the Windows dev box
because the shapefiles are downloaded manually. Resulting sqlite
file is scp'd to the Pi at `/home/wpballard/pyEfis/water/`.

## Multi-ring polygons — island holes (#44)

A multipolygon's interior rings are LAND (islands): the Florida Keys
are holes in the ocean polygons that surround them. The original
ingest emitted every ring as its own filled polygon and tessellated
single-ring only, so an island was painted as water twice over — the
outer ring's fill covered it, and its own coastline became a filled
ocean polygon (KEYW rendered as ocean; issue #44).

The builder now preserves ring topology:

- Rings are classified by winding (shapefile convention, which the
  data preserves: outer rings are clockwise in (lon, lat) = negative
  shoelace signed area; holes counter-clockwise = positive) and each
  hole is grouped under the smallest outer ring containing it.
- One `water_polygons` row is stored per OUTER ring. Its `vertices`
  BLOB holds the outer ring followed by each hole ring; a new
  nullable `rings` BLOB (little-endian ring END offsets, earcut
  convention) records the ring boundaries. `rings` is NULL for
  single-ring rows — the overwhelming majority.
- `triangles` is tessellated hole-aware (earcut's ring list), so the
  GPU fill excludes the islands with no renderer change.
- **Index dtype rule (dense cells):** both the `triangles` and
  `rings` BLOBs are uint16 for rows of <= 65535 total vertices and
  uint32 beyond. The dtype is implied by the row's vertex count
  (which the reader already derives from the `vertices` BLOB length),
  so no schema flag is needed. Before this rule, rows past the uint16
  ceiling silently DROPPED all their holes — the lower Florida Keys
  cell (3,322 island rings, > 65535 vertices at any realistic
  per-ring cap) lost every island, which kept #44 alive at the KEYW
  test-case location.
- **Hole verification (build time):** after tessellation, every hole
  ring's interior (even-odd scanline sample points) is checked
  against the row's fill triangles — decimation can corrupt a ring
  into something self-intersecting or outer-crossing that earcut
  fills instead of subtracting. On failure the per-ring decimation
  cap escalates (doubling to 512, then the raw source rings); if raw
  still fails, fill triangles whose centroid lands in a hole are
  stripped (biased toward land — painting an island as water is the
  dangerous direction). Unresolved rows warn on stderr and
  `import_shapefile` prints escalated / stripped / unresolved counts.
- Safety fallbacks: a single-ring shape imports as an outer whatever
  its winding (Natural Earth / text-format sources); a multi-ring
  shape with no clockwise ring fills every ring (reversed-winding
  source, the pre-#44 behavior); a hole contained by no outer is
  dropped, never filled.
- Decimation (`--max-vertices`) applies PER RING at build time, and
  `WaterDB` never re-decimates multi-ring rows on load — a stride
  across concatenated rings would corrupt both the ring offsets and
  the triangle indices.

Reader/consumer contract: `WaterPolygon.rings` is the decoded offset
list (None on single-ring rows and pre-#44 databases — those stay
fully readable). Triangle-based consumers (the SVS GL water layer)
need no ring handling. Outline/fill consumers must not treat
`vertices` as one drawable ring: fill even-odd per ring (the moving
map's `_draw_water`) or use `WaterPolygon.outer_vertices`.

Old databases keep working against new code (probe-based, like the
`triangles` column; old rows never exceed 65535 vertices, so the
uint16 decode path applies to all of them). New databases read under
OLD code degrade on multi-ring rows (the concatenated vertex list
draws as one outline), and an old reader would mis-decode a dense
row's uint32 blobs as uint16 — deploy the code update FIRST, then
ship the pack rebuild.

## Waterway centerlines — rivers as lines (#39)

Winding rivers cannot be stored as filled polygons: Douglas-Peucker
on a polygon outline cuts chords across the meanders and balloons a
thin channel into a filled lake-blob, which is why the polygon
ingest drops `riverbank` shapes (`--keep-fclass`) and rivers were
simply absent from the SVS. On a POLYLINE the same simplification is
shape-preserving — there is no fill to corrupt — so rivers live in a
dedicated centerline table instead.

`build_water_db.py --waterway <shp>` reads the Geofabrik per-state
waterways layer (`gis_osm_waterways_free_1.shp`, the same bundle the
roads build uses) and writes two additional tables into the water
sqlite:

```sql
CREATE TABLE waterway_lines (
    id INTEGER PRIMARY KEY,
    fclass TEXT NOT NULL,                -- river | canal | stream
    min_lat REAL, max_lat REAL, min_lon REAL, max_lon REAL,
    verts BLOB NOT NULL                  -- little-endian float32
);                                       --   (lat, lon) pairs
CREATE VIRTUAL TABLE waterway_rtree USING rtree(
    id, min_lat, max_lat, min_lon, max_lon
);
```

- **The schema mirrors the highway store 1:1**
  (`highway_lines`/`highway_rtree`, see `highway_db.py` and
  `tools/build_highway_db.py`): same columns, same float32 vertex
  encoding (`highway_db.encode_vertices`), one row per polyline
  part, R-tree indexed for the per-frame bbox query. A future
  waterway reader reuses the proven `polylines_in_range` pattern
  (and its decode) unchanged.
- **Class filter**: `river`, `canal`, `stream` by default (issue
  #39's set, matching the moving map's rivers preset); `drain` and
  `ditch` are dropped as noise at EFIS scale. Override with
  `--waterway-classes`.
- **Decimation**: Douglas-Peucker at `--waterway-tolerance-m`
  (default 40 m, the highway build's default — finer than the
  display resolves). No vertex cap: a polyline row is cheap and a
  cap would flatten long meanders.
- **A shapefile without an `fclass` field fails the build loudly**
  — it means the input is not an OSM waterways layer.
- **Compatibility**: the tables are created in every new build
  (empty when `--waterway` is not given) so readers can probe by
  content. The polygon store is untouched; old readers
  (`WaterDB`) never see the new tables, and old databases without
  them keep working — a waterway reader must treat a missing table
  as "no waterways" (the construct-never-raises convention).
- **Scope**: builder + schema only. Renderer wiring (a
  `waterways_in_range` query and an SVS/moving-map line layer in
  the water color) is the follow-up half of #39.

## Pi-side wiring

`virtual_vfr.yaml` in the screen YAML carries:

```yaml
svs:
    enabled: true
    ...
    water_db_path: /home/wpballard/pyEfis/water/water_capped.sqlite
    water_max_vertices: 32          # optional, defaults to 32
    svs_perf_log: true              # optional, default false
```

WaterDB construction is "missing file means disabled" — there is no
fatal failure if the path is wrong, just no water overlay.

## Perf notes (KSBA flight test, 2026-06-02)

Profiler (svs_perf_log: true) at KSBA looking out over the Pacific
on the GL renderer tier with the FULL un-decimated 1.45 GB OSM DB:

| segment | per-frame | % budget |
|---|---|---|
| **water.query** | **53 ms** | **70%** |
| runways | 6.5 ms | 9% |
| gl_terrain | 3.7 ms | 5% |
| obstacles | 3.2 ms | 4% |
| water.project | 0.04 ms × N | 0.3% |
| water.drawPolygon | 0.06 ms × N | 0.2% |

Diagnosis:

- The vector projection / drawing was trivially fast even with
  100+ polygons in range.
- `water.query` (sqlite SELECT + BLOB decode) was 70% of the
  frame budget.
- Rebuilding with `--max-vertices 32` cut DB from 1.45 GB to
  354 MB but `water.query` stayed at ~53 ms. So the cost wasn't
  reading 50 KB BLOBs — it was the index scan itself.
- The default `idx_bbox` is `(min_lat, max_lat, min_lon, max_lon)`
  — sqlite can only use one inequality predicate efficiently, so
  the planner is essentially scanning all rows with
  `min_lat < lat_upper` and matching the rest in Python.

The proper fix is sqlite's **R-Tree** virtual-table extension —
that's purpose-built for bbox queries and runs sub-millisecond on
this dataset size. Filed as a separate todo; not in the
build_water_db.py first version.

There's also a separate, larger perf mystery: total SVS work
adds up to ~65 ms / frame but pyEfis was running at 2 FPS
(~500 ms / frame). The other 435 ms is happening *outside* the
SVS draw path. Could be the GL FBO blit, Qt's repaint loop on the
new SVS widget, or other instrument paint events being amplified
by something. Needs investigation with a wider-scope profiler.

## What the download-and-update tool needs to do

The tool we still need to build. Open requirements:

1. **Fetch sources** — download OSM water-polygons-split-4326.zip
   and ne_10m_lakes.zip from their canonical URLs. Verify size /
   checksum where the upstream provides one.
2. **Cache locally** — re-running shouldn't re-download if the
   upstream file is unchanged (HEAD request + Last-Modified or
   ETag check).
3. **Extract** — unzip into a working directory.
4. **Build** — invoke `build_water_db.py` with appropriate flags,
   default `--max-vertices 32`.
5. **Validate** — confirm the resulting sqlite has the expected
   table shape, polygon count is plausible, and a sample query
   in a known bbox returns results.
6. **Install** — atomic move into place at the configured
   `water_db_path` so an in-flight pyEfis doesn't see a half-built
   file.
7. **Optional region builds** — CONUS-only build to keep DB small
   (~10–20 MB instead of 354 MB), useful for embedded targets
   with limited storage. Would clip both shapefiles to a bbox at
   ingest.
8. **Future inland-water build** — when we add OSM inland data,
   the tool should also run an OSM extract via osmium/imposm and
   merge into the same DB with `kind=lake` / `kind=river`.
9. **Cron/systemd hook** — schedule a monthly rebuild so the data
   stays current without manual steps.

Probably belongs as `tools/refresh_water_data.py` or a small
script set under `tools/water/`. Pattern can mirror what
`tools/build_airport_db.py` / `tools/build_obstacle_db.py` do for
their FAA NASR / DOF refresh.

## Filed work (followups)

- **R-Tree index for water_polygons** — replace the
  `idx_bbox(min_lat, max_lat, min_lon, max_lon)` B-tree with a
  proper rtree virtual table. Expected to drop `water.query` from
  ~53 ms to <1 ms.
- **Refresh tool** as above.
- **Inland OSM water** ingest pipeline.
- **CONUS-only / region-only** sub-build option.
- **Investigate the missing ~430 ms/frame** outside SVS at KSBA
  with water enabled.
