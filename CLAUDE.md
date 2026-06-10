# CLAUDE.md

Orientation for Claude sessions working on the **SVS (Synthetic Vision System)** in pyEfis.

## What this is

pyEfis is the **Python EFIS** for the MakerPlane open-source aircraft. It's a PyQt6 cockpit display that consumes flight data from a `fix-gateway` companion process over TCP. The SVS — the terrain-renderer that lives in the AI (attitude indicator) widget — is the active feature focus on this branch.

## Where this repo lives

- Working tree: `d:/Users/wpballard/Documents/github/MAOS/makerplane/pyEfis/`
- Active branch: **`svs-renderer`** (on `origin = billmallard/pyEfis`, the user's fork)
- Upstream: `makerplane/pyEfis` — **do not push or open PRs upstream without explicit authorisation.** This is the user's standing instruction.
- When eventually opening an upstream PR, note "please use merge commit, not squash" in the PR body — GitHub's squash merge has had defects during this period.

## Running things

The user's machine has Python deps installed in `C:\pylib` rather than the default site-packages, so `PYTHONPATH` must include it.

**Pi 5 test hardware:** `ssh pyefis` (key auth already configured) reaches the
Raspberry Pi 5 test unit. It is Claude's to use freely for on-target testing —
GL validation, perf baselines, harness runs on eglfs.

**Unit tests:**
```bash
PYTHONPATH="C:/pylib;src" python -m pytest tests/instruments/ai/test_svs.py --no-cov -q
```

There's one pre-existing failing test (`TestTileLoading::test_void_values_replaced_with_zero`) that pre-dates this work. Deselect it:
```bash
--deselect tests/instruments/ai/test_svs.py::TestTileLoading::test_void_values_replaced_with_zero
```

**Visual harness (no gateway needed; uses mock_db):**
```bash
SVS_RENDERER=polar SVS_LAT=34.4275 SVS_LON=-119.8546 SVS_ALT=500 SVS_HEAD=87 \
SVS_RANGE=8 SVS_AUTO_RANGE=false PYTHONPATH="C:/pylib;src" \
python tests/visual_svs_test.py
```
Other env vars: `SVS_PITCH`, `SVS_ROLL`, `SVS_GRID_LINES`, `SVS_CIFP_PATH`, `SVS_NASR_PATH`, `SVS_DOF_PATH`. The harness auto-discovers data files at `pyEfis/cifp/`, `pyEfis/nasr/airports.sqlite`, `pyEfis/dof/obstacles.sqlite` if present.

For background launches via the harness (so the user can interact with the window while we continue), use `run_in_background: true` and report the task ID.

## Data dependencies (all gitignored, user-supplied)

| Data | Path | Source | Used by |
|------|------|--------|---------|
| SRTM3 terrain tiles | `D:/EarthData/srtm3/<NSdir>/<tile>.hgt` | NASA SRTM v3 | Terrain elevation sampling |
| FAA NASR CSVs | `pyEfis/nasr/APT_*.csv` + `airports.sqlite` | FAA NASR cycle | Airport / runway data (preferred) |
| FAA CIFP | `pyEfis/cifp/FAACIFP18` + `index.bin` | FAA CIFP cycle | Fallback airport data (also used by VVfr) |
| FAA DOF | `pyEfis/dof/DOF.CSV` + `obstacles.sqlite` | FAA DOF (56-day cycle) | Obstacles (towers, antennas) |

Build the sqlite files with `tools/build_airport_db.py` and `tools/build_obstacle_db.py`.

## Architecture map

The SVS lives in [src/pyefis/instruments/ai/](src/pyefis/instruments/ai/):

- **[svs.py](src/pyefis/instruments/ai/svs.py)** — `SVSRenderer`. The whole terrain pipeline:
  - Two renderer tiers: `cpu_sparse / cpu_dense / cpu_ultra` (legacy rectangular lat/lon grids) and `polar` (forward fan with radial-warp LOD — current default).
  - Vectorised per-cell shade-key computation; vertex iteration only over visible cells grouped by colour bucket.
  - `_draw_runways` paints the runway quad and, when within `detail_distance_nm`, `_draw_runway_markings` adds Tier C surface markings per FAA AC 150/5340-1L (threshold bars, centreline, designators via `QTransform.quadToQuad` perspective, aiming point, TDZ for PIR, side stripes, chevrons).
  - `_draw_obstacles` projects FAA DOF towers/antennas as vertical poles, colour-coded by lighting and conflict.
  - Near-airport terrain coloring collapses to a 2-colour green/magenta scheme inside `airport_proximity_nm` so a normal approach doesn't paint the screen red.
- **[airport_db.py](src/pyefis/instruments/ai/airport_db.py)** — `NASRAirportDB` (preferred sqlite) and `CIFPAirportDB` (fallback via `pyavtools.CIFPObjects`). `make_airport_db(config)` picks the best available.
- **[obstacle_db.py](src/pyefis/instruments/ai/obstacle_db.py)** — `ObstacleDB`, sqlite-backed range query for DOF records.
- **[ai/__init__.py](src/pyefis/instruments/ai/__init__.py)** — the host AI widget. `SVSRenderer` is wrapped by a small `QGraphicsItem` factory (`make_svs_item` in `svs.py`) so SVS participates in scene z-order: default `z=0.5` sits between the sky/land background (z=0) and the pitch ladder (z=1).

## Code conventions visible in this code

- **Graceful FIX-key init**: when a FIX-database key the AI needs is missing (e.g. `TRACK` from `fix-gateway`), the constructor logs a warning and leaves the related flag in failed state rather than raising. Pattern at `ai/__init__.py` `__init__` (try/except around `fix.db.get_item`). Apply the same pattern when adding new FIX-key consumers.
- **Construct-never-raises database loaders**: `AirportDB`/`ObstacleDB` accept missing/unreadable files; `.ready` reports the state and queries yield nothing. Mirror this when adding new data backends — never let a missing data file break the renderer.
- **Sentinel for ocean/void**: `_WATER_SENTINEL = -9999.0` marks ocean cells in elevation arrays; the shade-key bucket 4 picks them up as water-blue. Don't substitute plain `0.0` for missing-data — coastal interpolation needs the magnitude to detect water.
- **Projection unified through `_project_point`**: every world-space marker we draw (runway corners, threshold bars, designator quads, obstacle poles, airport flags) is projected via `SVSRenderer._project_point(lat, lon, elev_ft, ...)`. Reuse it; don't reimplement the perspective math.
- **No emojis in code or commit messages.** The user hasn't asked for them.

## Documentation

- [docs/svs_rendering.md](docs/svs_rendering.md) — tiers, polar config, runway-marking notes
- [docs/svs_planning.md](docs/svs_planning.md) — design rationale; original Issue #28 NASR-import plan (now shipped)
- [docs/svs_hardware_options.md](docs/svs_hardware_options.md) — Pi 5 vs N100 vs Compulab vs Onlogic; user has Pi 5 hardware on order for in-flight testing

## Issues open against `billmallard/pyEfis`

- **#32** — Option B (elevation-aware) for airport-proximity terrain coloring; Option A is shipped
- **#33** — FPM and pitch-ladder symbology occluding the runway on stabilized approach (not blocking; pattern matches every PFD-with-FPM)
- **#34** — DOF obstacles (shipped 2026-05-24)
- **#35** — OSM-based major-highway overlays (bigger lift; queued after obstacles)
- **#36** — Move airport identifier inside the flag body (readability polish)

## Things to remember in the moment

- The user keeps multiple visual-harness windows running in parallel for comparison. We typically close them as `task-notification` events arrive; nothing else action-required.
- Don't run `cmd /c cd` then a git command — `git` already operates on the working tree; the compound triggers a permission prompt on this machine.
- The user values commit-history granularity. Bundled commits are acceptable when files genuinely overlap, but a focused commit per feature is preferred when it can be split cleanly.
