# Handoff: ship the wide-range map performance work to all users

Status: 2026-07-10. The wide-range moving-map performance work (terrain mosaic +
water range-cap + Great Lakes) is **proven and live on Bill's bench Pi only**.
This doc is what a fresh thread needs to get it to every user. Companion:
`map_wide_range_perf_plan.md` (the profiling + design), `terrain_mip_pyramid.md`,
makerplane-data `docs/terrain.md`.

## 1. What's done, and exactly where it lives

**Code — pushed to `billmallard/pyEfis` branch `dev`** (NOT master/release):

| commit | what |
|---|---|
| `f2a48c9` | `build_terrain_mips.py` parallelized (`--jobs`) |
| `44e8e59` | terrain **mosaic**: `tools/build_terrain_mosaic.py`, `TileCache.get_mosaic`, `TerrainLayer._sample_mosaic`, `tools/bench_map_terrain.py`, `docs/map_wide_range_perf_plan.md` |
| `2623de8` | water overlay hard range-cap (superseded by a652de1) |
| `a652de1` | `WaterDB.polygons_in_range(drop_ocean=)`; water tiered by range |
| `7fa3849` | range-scaled wide-range lake size floor (Great Lakes above 300 NM) |

**Data — on the bench Pi only, NOT in packs:**
- Terrain mosaics `/data/makerplane-data/terrain/tiles/.mip/mosaic/L{4,5,6}.{hgt,json}`
  built on-device with `build_terrain_mosaic.py` (CONUS extent; ~9/36/143 MB).
- No "big water" index exists yet (proposed, §3.2).

**Deployment reality:** the bench Pi runs a **patched** `~/pyEfis` (`git apply`,
base `bcc11a4`) with `.bak-pre-mosaic` backups, not a clean `dev` checkout. Other
devices have **none** of this.

## 2. The gap: what "deployed to all users" requires

Two independent things must reach a user's device:
1. **The render code** — needs to land on the branch users actually run
   (`master` / a release), then eventually the upstream pyEfis PR.
2. **The mosaic data** — a device must have `.mip/mosaic/` beside its `.mip` tree,
   or `get_mosaic` returns None and it stays slow. **This is the crux** and drives
   the main design decision below.

## 3. Work items

### 3.1 Get the mosaic onto every device — DECISION FIRST
The mosaic is a **whole-extent stitched file per level**, but terrain packs are
**per-region** and devices **union** whatever regions they opted into. So:

- **Option A — ship mosaics in the packs.** Awkward: per-region mosaic pieces
  don't union into one file; a device with us-west+us-central would need a mosaic
  covering exactly its union. You'd ship pieces and stitch on-device anyway.
- **Option B — build the mosaic ON THE DEVICE after `pyefis-data update`
  (RECOMMENDED).** Exactly how the bench Pi got it. `build_terrain_mosaic.py`
  already ships in `pyEfis/tools`; the device runs it against its unioned `.mip`
  tree (fast — 1.2 s for CONUS on the Pi). Naturally handles any region
  combination and re-runs when regions change. No pack/pipeline change.

**Recommended: Option B.** Implementation:
- Add a post-update hook to the `pyefis-data` updater: after a terrain pack is
  unzipped, run the mosaic build (or invoke `build_terrain_mosaic` as a library).
- Make it **idempotent/stale-aware**: build only if `.mip/mosaic/` is missing or
  older than the newest `.mip` tile (so it re-runs after a region add, skips
  otherwise). A startup check in `TerrainLayer.configure` is an alternative/backup
  trigger.
- Needs numpy (pyEfis already has it). Guard failures (mosaic absent ⇒ existing
  per-tile fallback still works).

### 3.2 (Optional) big-water index — instant wide-range water
Wide-range water is currently query-bound (~2.3 s @ 2500 NM: SQLite scans a
2.15 M-polygon R-Tree over a huge bbox). To make it instant, build a **pre-filtered
side table** of only large bodies (`bbox diag >= ~0.5°`, ~46k rows) with its own
R-Tree; `WaterDB.polygons_in_range` queries it when `drop_ocean`/wide. Same
on-device-vs-pack decision as §3.1 — recommend building it on-device from
`water.sqlite` post-update (a one-time `CREATE TABLE … WHERE size>=? ` + rtree).
Deferred: current 0.35–2.5 s is smooth enough (Bill signed off); do this only if
wide-range water instantness is wanted.

### 3.3 Branch promotion
Render code is on `dev`. Promote `dev → qa → master` (forward-only, per
`makerplane-data/docs/environments.md`). **Caution:** master promotion was being
held to protect the open **upstream pyEfis PR #274** — check that's resolved
before promoting, or cherry-pick the map commits onto a clean branch for the
upstream PR. Final reach = an upstream PR to Phil Birkelbach's pyEfis.

### 3.4 Tests
Add unit coverage (only the offscreen bench guards this today):
- `get_mosaic` / `_sample_mosaic`: build a tiny 2-tile mosaic in a tmp tree,
  assert the mosaic sample matches the per-tile sample (the 0.3–0.9 m check we did
  by hand) and that absent-mosaic falls back.
- Water tiering: assert `drop_ocean` + range-scaled floor reduce the poly set
  above `_WATER_FULL_MAX_NM`.
Existing `tests/instruments/test_moving_map.py` is green (9) incl. the water fake
updated for the `drop_ocean` kwarg.

### 3.5 Clean-device end-to-end verification
The real proof for *other* users: on a **clean** device (not the patched bench),
`pyefis-data update` → confirm `.mip/mosaic/` gets built (§3.1) → pinch to
nationwide → verify ~0.2 s render (use `tools/bench_map_terrain.py --water <db>`
on-device; it must exercise water, that's how the 30 s hid originally).

### 3.6 Reconcile the bench Pi (housekeeping)
Once the code is on master, replace the bench Pi's patched `~/pyEfis` with a clean
checkout (backups `.bak-pre-mosaic` exist). Not urgent — it works as-is.

## 4. Reference (so the next thread has the keys)

- **Bench Pi:** `ssh wpballard@10.110.10.189` (alias `pyefis` resolves flakily —
  use the IP; `scp` is broken on the workstation, use `cat file | ssh … 'cat >…'`).
  pyEfis is a **user** service: `systemctl --user restart pyefis.service`
  (set `XDG_RUNTIME_DIR=/run/user/1000`; not sudo, not the system service). Deps in
  `~/pyEfis/.venv`; run tools with `.venv/bin/python … PYTHONPATH=src
  QT_QPA_PLATFORM=offscreen`. Tile tree `/data/makerplane-data/terrain/tiles`
  (CONUS only, lat24-49/lon-125..-66); water `/data/makerplane-data/water/current/water.sqlite`.
- **Workstation:** GLO-30 `.hgt` tree `D:\EarthData\glo30hgt` (+ full-NA mosaics
  under `.mip/mosaic`); deps on `C:\pylib` (`PYTHONPATH="C:/pylib;src"`).
- **Key constants** (`map/layers/terrain.py`): `_WATER_FULL_MAX_NM=300`,
  `_WATER_WIDE_DIAG_PER_NM=0.001`, `_WATER_WIDE_DIAG_MAX=3.0`; mip clamp `0..6`.
- **Water DB fact:** all rows `kind='water'`, `elev_ft=NULL` — size is the only
  discriminator (don't rely on the schema docstring's ocean/lake/river).
- **Bench:** `tools/bench_map_terrain.py --tiles <tree> --water <db> --lat --lon
  --ranges … --repeat 3` — offscreen render decomposition (sample/palette/rest),
  cold vs warm.

## 5. Recommended order
1. §3.1 Option B — on-device mosaic build after update (the one thing that gives
   every user the terrain win). Verify §3.5 on a clean device.
2. §3.4 tests, §3.3 branch promotion (mind PR #274), upstream PR.
3. §3.2 big-water index only if wide-range water instantness is wanted.
4. §3.6 reconcile the bench Pi.
