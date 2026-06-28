# CLAUDE.md

Orientation for Claude sessions working on the **SVS (Synthetic Vision System)** in pyEfis.

## What this is

pyEfis is the **Python EFIS** for the MakerPlane open-source aircraft. It's a PyQt6 cockpit display that consumes flight data from a `fix-gateway` companion process over TCP. The SVS — the terrain-renderer that lives in the AI (attitude indicator) widget — is the active feature focus on this branch.

## Where this repo lives

- Working tree: `d:/Users/wpballard/Documents/github/MAOS/makerplane/pyEfis/`
- Active branch: **`gpu-required`** (on `origin = billmallard/pyEfis`, the user's fork). Older docs/memory say `svs-renderer` — stale.
- Upstream: `makerplane/pyEfis` — **do not push or open PRs upstream without explicit authorisation.** Standing instruction.
- When opening an upstream PR, note "please use merge commit, not squash" — GitHub's squash merge has had defects during this period.

## Current upstream contribution (in flight)

- **PR #274** — `billmallard:gpu-required → makerplane/pyEfis:master`, the whole SVS contribution (~206 commits). **CI is green.** I have READ on the makerplane org, so it's a cross-fork PR a maintainer merges; I offered an integration-branch workflow in a PR comment (maintainer makes a branch, I retarget the base). **Pushing to `gpu-required` auto-updates this PR and re-runs its CI.**
- Companion **fix-gateway PR #203** wires the X-Plane feed (RREF nav → HSI COURSE/CDI). Its `send:` (FIX→X-Plane throttle/mixture) block is DISABLED by default — it commanded the engine closed once it reached X-Plane's real port.
- NOTE: this CLAUDE.md is committed on `gpu-required` and currently rides in PR #274, with local/ssh specifics — consider gitignoring it out of the upstream PR.

## Running things

The user's machine has Python deps installed in `C:\pylib` rather than the default site-packages, so `PYTHONPATH` must include it.

**Pi 5 test hardware:** `ssh pyefis` (key auth already configured) reaches the
Raspberry Pi 5 test unit. It is Claude's to use freely for on-target testing —
GL validation, perf baselines, harness runs on eglfs.

**Unit tests:**
```bash
PYTHONPATH="C:/pylib;src" python -m pytest tests/instruments/ai/test_svs.py --no-cov -q
```

The full suite runs clean in CI (Linux). On Windows a handful fail environmentally (weston, some path-order tests) — not real; trust CI. `tests/visual_svs_test.py` is a MANUAL harness (it calls `app.exec()` at import) excluded via `addopts --ignore` — never let pytest collect it or the run hangs forever. SVS deps are an extra: `pip install -e .[qt,svs]` (numpy + PyOpenGL).

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

**On the Pi (runtime) the data lives under `/data/makerplane-data/`** (installed by the makerplane-data updater), NOT the PC paths above: terrain `terrain/tiles/N##/N##W###.hgt` (**GLO-30**, 3601², big-endian `>i2`); water `water/current/water.sqlite` (`water_polygons` table; vertices `<f8` lat/lon pairs; `kind` = ocean|water). The fix-gateway runtime config is at `~/makerplane/fixgw/config/` and is **not git-managed** — the only un-versioned deployed state.

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

- **#33** — FPM / pitch-ladder symbology occluding the runway on stabilized approach (matches every PFD-with-FPM)
- **#39** — rivers-as-lines (rivers are dropped as polygon blobs; render OSM waterway lines instead)
- **#40** — water build: include wetlands/bays so receded-lake shorelines match sim/chart (Farmington Bay shows land vs X-Plane water — a data-extent boundary, not a bug)
- **#44** — BUG: ocean fills island holes — `build_water_db` emits each multipolygon ring as a separate FILLED polygon, so islands (Florida Keys / KEYW) get painted as ocean. Confirmed visually.
- Test cases (label `test-case`): **#41** (GSL/Farmington Bay), **#43** (KEYW island vs ocean).
- (Also open: #32 elevation-aware proximity coloring, #38 PAPI adoption, #26, #29.)

## Things to remember in the moment

- The user keeps multiple visual-harness windows running in parallel for comparison. We typically close them as `task-notification` events arrive; nothing else action-required.
- Don't run `cmd /c cd` then a git command — `git` already operates on the working tree; the compound triggers a permission prompt on this machine.
- The user values commit-history granularity. Bundled commits are acceptable when files genuinely overlap, but a focused commit per feature is preferred when it can be split cleanly.
- **Log a manual test case for EVERY visual edge case** (label `test-case`; "Visual / SVS Test Case" template lives on branch `test-case-templates`, needs merging to master to activate). #41/#43 are the first two. Always record heading + whether the feature is inside the ±70° forward fan.
- **SVS rendering facts that masquerade as bugs:** terrain is a **±70° forward fan** (`POLAR_DEFAULTS fov_deg: 140`) — features behind/beside you aren't drawn (check heading vs bearing-to-feature FIRST). **No depth test** — overlays paint on top of terrain in painter's order (no z-fighting). Inland water with `elev_ft=NULL` is drawn at the terrain elevation sampled at **vertex 0 only** (`_collect_water_sync`). GLO-30 flattens lakes to their surface (valid, not void).
- **Don't trigger the SIGUSR1 screenshot while the user is flying:** `kill -USR1 <pid>` → `/tmp/pyefis_screenshot.png` grabs `gui.mainWindow` (the HSI window, not the SVS) AND blanks the live SVS GL widget. It's a broken handler.
- **Diagnose water/terrain from the DATA, not the GUI** (no pyavtools needed): query `/data/makerplane-data/water/current/water.sqlite` directly + ray-cast point-in-polygon for "over mapped water?"; sample GLO-30 raw (`np.fromfile(dtype=">i2").reshape(3601,3601)`, void ≤ -1000). This root-caused both the GSL "missing water" (forward fan — lake was behind) and KEYW (#44) entirely from the data side.

## Lessons learned

### SVS performance is collection-bound, not draw-bound (issue #74)
The low-altitude approach stutter was the three **spatial-data collectors** — `obstacles_in_range`, `polylines_in_range` (highways), `polygons_in_range` (water) — running as Python DB scans on async worker threads, **not** the GL drawing (`paintEvent` + the cached overlays are cheap). Each had its own worker with an independent busy check, so when a position key rolled over all three fired together and their **GIL-held** Python bursts stacked into one render-stalling spike (~42% of py-spy samples; any two ~28% was smooth, all three was not). Worst **≤500 ft AGL near populated airports** (most features in range). Fixed by a shared `_collect_slot` lock that serialises the collectors (peak ~42%→~14%, no feature loss) + `_los_masked_batch`, which vectorises the per-vertex terrain LOS (the #73 regression) into one batched `_sample_elevations` call.
- **When SVS stutters, profile the collectors, not the renderer** — don't theorise from the GUI.
- **Any per-feature work on a collect worker must be vectorised numpy** — a Python per-element loop holds the GIL and stalls the 30 FPS render (`_los_masked` per vertex was the trap).
- Issue #74 is the standing low-level perf test case.

### Live profiling on the Pi
`~/pyefis-data-venv/bin/py-spy record --pid $(pgrep -f pyEfis.py) --duration 30 --rate 200 --format raw --output /tmp/x.raw --idle` during the descent (needs sudo for ptrace), then aggregate the folded stacks by leaf and by keyword (collectors vs `paintEvent`).

### Deploying code to the Pi (not git-pull)
The Pi runs its own checkout at `~/pyEfis` as **systemd user service `pyefis.service`** (fix-gateway = `fixgw.service`). Its git HEAD is stale (`gpu-required`@#71) because deploys happen by **scp/patch, not pull** — the working `svs.py` is ahead of HEAD. Deploy a change as a patch and validate the baseline first: `git -C local diff -- <file> > p.patch` -> scp -> `git -C ~/pyEfis apply --check p.patch` (must report OK) -> `apply`. Restart with `systemctl --user restart pyefis` (the SVS can take ~90 s to stop on SIGTERM); verify `is-active` + `NRestarts=0` + journal for traceback/segfault. Back up the file you replace.

### Runtime config lives outside the checkout
pyEfis reads config from `~/makerplane/pyefis/config` (NOT the git tree). Active screen = `main/default.yaml:defaultScreen` resolved through `preferences.yaml.custom` (`SCREEN_*` map) — currently `screens/managed.yaml`, with the SVS layer paths (`water_db_path`/`highway_db_path`/`dof_db_path`) inline there. Editing the checkout or a `.dist` does nothing; edit the active tree and restart. (Same pattern for fix-gateway: `~/makerplane/fixgw/config/preferences.yaml` base + `preferences.yaml.custom` override.)

### fix-gateway has no source arbitration
Two plugins writing the same FIX key = last-writer-wins (they fight). `xplane` and `stratux` both write attitude/position — running both gives a flickering mix; enable exactly one source per key. Real source-selection + a SIM/FLIGHT interlock are still TODO (see `MAOS-DESIGN/docs/AVIONICS_STACK_ROADMAP.md` sections 8-9).

### Methodology
Don't converge early. The first read on this stutter ("an X-Plane artifact") was wrong; the user was right it was new. Profile + A/B (disable layers, re-fly) before concluding, and treat "it worked before" as data, not noise.
