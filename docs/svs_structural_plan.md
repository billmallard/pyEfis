# SVS structural improvement plan

Phased implementation plan for the recommendations in
[../STRUCTURAL_REVIEW.md](../STRUCTURAL_REVIEW.md). Covers the five core
structural moves, the Copernicus GLO-30 terrain transition, and the
next-level features (visual polish, ADS-B traffic, highway-in-the-sky,
chart/satellite draping).

Branch: `gpu-required` (forked from `svs-renderer` at the Phase 4b tip).

## How to work this plan (read first — especially if you are a fresh agent)

- **Read [../CLAUDE.md](../CLAUDE.md) before touching anything.** It has
  the run/test commands, the `PYTHONPATH="C:/pylib;src"` requirement on
  the Windows dev machine, the pre-existing failing test to deselect, the
  visual-harness env vars, and the standing rules (no pushes/PRs to
  upstream `makerplane/pyEfis`; no emojis in code or commits).
- **One phase per work session** is the intended granularity. Each phase
  is independently committable and leaves the tree releasable. Within a
  phase, prefer one focused commit per checklist group.
- **Tick the checkboxes in this file as you complete steps** and commit
  the plan-file update together with (or immediately after) the work, so
  a successor agent can see exactly where things stand.
- **Verify before and after**: run the unit tests and at least one
  visual-harness pose (poses table below) before starting a phase, so you
  know which breakage is yours.
- Line numbers cited here are accurate as of the branch point
  (`b160c1c`) and will drift — search for the symbol names instead.
- Forward-only migration, same policy as the overlays-to-GPU plan: no
  feature flags for old-vs-new paths, revert via git if a phase regresses.

### Standard verification commands

Unit tests (Windows dev machine, bash):

    PYTHONPATH="C:/pylib;src" python -m pytest tests/instruments/ai/ --no-cov -q \
      --deselect tests/instruments/ai/test_svs.py::TestTileLoading::test_void_values_replaced_with_zero

Visual harness (no gateway needed):

    SVS_RENDERER=opengl SVS_LAT=34.4275 SVS_LON=-119.8546 SVS_ALT=500 \
    SVS_HEAD=87 SVS_RANGE=8 SVS_AUTO_RANGE=false \
    PYTHONPATH="C:/pylib;src" python tests/visual_svs_test.py

### Reference poses for visual checks

| Name              | LAT     | LON       | ALT   | HEAD | Exercises                          |
|-------------------|---------|-----------|-------|------|------------------------------------|
| KSBA offshore     | 34.4275 | -119.8546 | 500   | 87   | water, coastline, short final      |
| KASE short final  | 39.2282 | -106.8723 | 8300  | 151  | mountain terrain, runway markings  |
| KASE 10k MSL      | 39.20   | -106.85   | 10000 | 150  | terrain shading, range             |
| DFW metro         | 32.90   | -97.04    | 2500  | 175  | many airports, obstacles, perf     |

When a phase says "golden poses", it means screenshots at these four.

### Cross-phase dependency map

    P0 baseline ──> P1 finish overlays ──> P2 delete CPU era ──> P3 unified camera ──> P5 GL viewport
                                                              └─> P7 polish (MSAA/haze, after P3)
    P4 frame clock        — independent, any time after P0
    P6 GLO-30 terrain     — independent, any time after P0
    P8 scenery packs      — after P3 (wants ENU vertex format)
    P9 traffic + HITS     — after P3 (wants unified camera); gateway work in parallel
    P10 chart draping     — after P6 (shares texture-patch infrastructure)

---

## Phase 0 — Baseline and guardrails (½ day)

Goal: lock in "known good" before the deletions begin.

- [x] Capture golden screenshots at the four reference poses with
      `SVS_RENDERER=opengl`, store under `tests/golden/` (or document the
      external location if too large for the repo). Plus a Pi 5 on-target
      capture of the DFW pose (`dfw_metro_pi5.png`).
- [x] Run the unit suite; record the pass/fail inventory in the commit
      message so later phases can diff against it. (124 pass / 4
      pre-existing Windows path-separator failures in test_virtualvfr /
      1 GL-context skip / 1 standing deselect — details in the baseline
      doc.)
- [x] With `svs_perf_log: true`, record per-segment timings at the DFW
      pose into `docs/perf_baseline_gpu_required.md` (frame.svs_total,
      water, runway.*, obstacles, gl_terrain). Recorded on BOTH Windows
      and Pi 5 (eglfs, on-target via `ssh pyefis`).
- [x] Grep for config keys the later phases will remove
      (`renderer:`, `quality_control`, `gl_overlay_perspective`) and note
      every YAML file in the repo / user config that uses them. (Only
      `renderer:` is used anywhere — the Pi's local virtual_vfr.yaml;
      the other two appear in no YAML. See baseline doc.)

P0 additionally surfaced and fixed two pre-existing bugs that blocked a
valid baseline (details in the baseline doc): the desktop-GL
`glLineWidth(2.0)` failure that silently downgraded every Windows
"opengl" run to polar, and the eglfs startup crash from the SVS
QGraphicsItem riding a destroyed scene down. The harness also gained
`SVS_WATER_PATH` / `SVS_PERF_LOG` / `SVS_ANIMATE` / `SVS_SCREENSHOT`
support, which later phases should use for their verification steps.

Done when: goldens + perf baseline committed; test inventory recorded.
**STATUS: COMPLETE (2026-06-10).**

## Phase 1 — Finish overlays-to-GPU: airport flags + identifier text (½–1 day)

This is Phase 5 of [svs_overlays_to_gpu_plan.md](svs_overlays_to_gpu_plan.md),
unchanged in scope. It must land before the CPU deletion phase because
`_draw_runways` (the last CPU overlay) only exists to draw the flags.

- [x] Add `_collect_airport_flags` to `SVSRenderer`: pole = line segment
      vertices; flag rectangle = quad of triangles; identifier text =
      glyph quads reusing the Phase 4b atlas. Follows the collect/cache
      pattern (1 s TTL, coarsened position key + ppd).
- [x] Billboard decision: **billboard-by-distance** — world sizes derived
      from airport distance at collect time so the flag projects to
      ~constant pixels. Under roll the flags stay world-horizontal (bank
      with the terrain) instead of the old screen-aligned behaviour;
      judged more natural for an SVS scene.
- [x] Draw them in `_render_overlays` after the designator text pass.
- [x] Delete `_draw_runways` entirely (it only drew flags by this point)
      and both call sites. `airports.flag` went from ~34 CPU calls/frame
      to one GL pass at 0.20 ms/frame; Windows frame.svs_total dropped
      8.45 -> ~6.4 ms at the DFW pose.
- [x] Issue #36: done — identifier renders in black INSIDE the yellow
      flag body, flag sized to fit the label.

Done when: flags + identifiers render via GL at all four golden poses;
no QPainter overlay work remains in the SVS frame path; unit tests pass.
**STATUS: COMPLETE (2026-06-10).** Goldens refreshed post-P1 (flag
appearance intentionally changed); test inventory unchanged
(124 pass / 4 pre-existing). Pi on-target validation: PASSED
2026-06-10 (eglfs worktree run at DFW after P2 — flags + inline
identifiers render on ES, frame.svs_total 10.1 ms vs 11.25 ms at P0,
no UNAVAIL/fallback).

## Phase 2 — GL required: delete the CPU rendering era (1–2 days)

Goal: one renderer, one implementation of every visual decision. This is
the phase the branch is named for.

Deletion list (all in `src/pyefis/instruments/ai/svs.py` unless noted):

- [x] The rectangular CPU tiers: `GRID_SIZES`, the `cpu_sparse/dense/ultra`
      branches in `draw()`, the shade-table construction, the vectorised
      cell/edge bucketing and QPainterPath fill/grid-line loops.
- [x] The polar CPU rasteriser (the entire non-GL tail of `draw()`).
- [x] `_QualityController` and all `self._quality` consumers;
      `detail_distance_nm` is a plain config value now.
- [x] `_project_polygon_clipped`, `_runway_polygon_corners`, `Qt_NoPen`,
      the `_AIRPORT_DB` hand-coded KASE dict and its fallback branch in
      `_airports_in_range`, the `SVSGraphicsItem` placeholder class.
- [x] The `renderer:` config key: accepted and ignored with a
      deprecation log line; removed from docs.

Failure policy (replaces the polar fallback — decide and implement):

- [x] Implemented: any GL init/draw failure sets
      `SVSRenderer.gl_failed`, draw() becomes a no-op, and the AI
      widget annunciates amber **SVS UNAVAIL** centred in the upper
      viewport. One-shot, never re-attempts GL. Covered by
      `TestSVSGLFallback` (init failure, draw failure, no-retry).

Restructure while the file is open (pure moves, no behaviour change):

- [ ] **DEFERRED to a later session** (token budget): split into a
      package `src/pyefis/instruments/ai/svs/` with `__init__.py`
      (SVSRenderer facade + make_svs_item), `geometry.py` (pure
      collectors, no Qt), `gl.py`, `tiles.py`, `perf.py`. Keep
      `from pyefis.instruments.ai.svs import SVSRenderer` working.
      Nothing else in P3+ depends on this — pick it up any time.
- [x] Fix the per-frame airport query: `SVSGLRenderer._near_airport`
      now delegates to `SVSRenderer.near_airport` (1 s TTL cached
      boolean).
- [x] Update `docs/svs_rendering.md`: tier table replaced by the
      GL-required section; fallback section now documents UNAVAIL.

Done when: golden poses unchanged vs Phase 0 (pixel-identical not
required — GL path was already the default — but no visual regressions);
`svs.py` equivalent drops to roughly half its size; a forced GL failure
(e.g. env var or monkeypatched context) shows the UNAVAIL annunciation;
unit tests updated and passing.
**STATUS: COMPLETE except the deferred package split (2026-06-10).**
svs.py 2419 -> 1791 lines (and P1 had added ~120 of flag collector to
the old count). DFW visual check identical to the post-P1 golden.
Suite: 104 pass (20 tests deleted with their subjects: TestPolarTier,
TestProjectPolygonClipped, TestQualityController; GL-fallback tests
rewritten to UNAVAIL semantics) / same 4 pre-existing failures.

## Phase 3 — Unified camera: one VP matrix, ENU metres (2–3 days)

Goal: collapse six projection implementations into one; fix float32
precision; delete the CPU near-plane clipper; add earth curvature.
STRUCTURAL_REVIEW.md section 2 is the design rationale.

Design decisions to lock in (do these first, in a short design note
committed to this file or as comments):

- [ ] **Local origin**: the heightmap patch SW corner (already tracked as
      `_patch_origin`). All ENU coordinates are metres east/north/up of
      that origin; magnitudes stay < ~250 km so float32 is mm-precise.
      Origin changes exactly when the patch rebuilds (half-degree
      crossings) — every cached vertex buffer must be invalidated on
      origin change (add origin to the cache keys).
- [ ] **Matrix**: CPU builds `u_vp = P(fov from pixels_per_deg, viewport)
      @ R_roll @ R_pitch @ R_heading @ T(-aircraft_enu)` once per frame
      with numpy (float64, downcast at upload). FOV definition: preserve
      the current `pixels_per_deg` semantics — scale chosen so small
      angles map to the same pixels as today, which keeps the pitch
      ladder and FPM aligned without touching the AI widget.
- [ ] **Units**: collectors emit metres. `geometry.py` gets one
      conversion helper (`latlon_to_enu(origin, lat, lon, elev_ft)`);
      the scattered `111139.0 / 364491.0 / 3.28084` constants collapse
      into it.

Implementation steps:

- [ ] Add `camera.py` to the svs package: builds the VP matrix; unit-test
      it standalone (known pose → known screen position for a handful of
      points, including behind-camera w<=0 cases).
- [ ] Terrain vertex shader: keep the polar-fan generation (t, az →
      bearing → ENU offsets in metres, heightmap sample for up), then
      `gl_Position = u_vp * vec4(enu, 1.0)`. Delete the per-vertex
      pitch/roll trig and the screen-pixel math.
- [ ] Overlay + text shaders: vertex stage becomes
      `gl_Position = u_vp * vec4(a_pos_m, 1.0)` (plus UV passthrough for
      text). Delete the legacy atan2 branch and the `u_use_perspective`
      uniform/config key.
- [ ] Collectors emit ENU float32 instead of (lat°, lon°, ft). Water and
      runway data still *store* lat/lon in sqlite — conversion happens in
      the collect step against the current origin.
- [ ] Delete `_filter_behind_camera_triangles` and its call sites — GL
      w-clipping handles the near plane under true perspective. Verify
      the near field at KASE short final and a low pass directly over a
      runway: no wedge artifacts, and the ~50 m foreground gap the CPU
      clipper imposed should be gone (runway surface visible under the
      nose).
- [ ] `_project_point` survives only if the airport flags chose
      screen-billboard sizing in Phase 1 and need a CPU projection — if
      so, reimplement it as `camera.project(enu)` using the same matrix
      so there is exactly one projection. Otherwise delete it.
- [ ] **Earth curvature**: in the terrain vertex shader (and in the
      collectors for overlay elevations), apply
      `up -= dist_m^2 / (2 * 6371000.0)`. Gate behind a config key
      `earth_curvature: true` default on, so an A/B screenshot is easy.
      Verify: at 10,000 ft the horizon line sits ~1.75 deg below the
      zero-pitch line (vs 0 deg flat-earth) and distant ridges drop.

Done when: terrain and overlays are *pixel-aligned* (runway sits exactly
on its terrain footprint at all four poses — previously only
approximately); near-field artifacts gone; all projection math lives in
`camera.py` + one shader vertex stage; unit tests for camera.py pass;
`u_use_perspective`, the CPU clipper, and the atan2 shader branch are gone.

## Phase 4 — Frame clock + pose interpolation (1–2 days)

Goal: fixed display cadence, smooth motion between FIX updates, bounded
CPU. STRUCTURAL_REVIEW.md section 3. Independent of P1–P3; can be done
any time, by a separate session.

- [ ] Add a `PoseSource` class (suggest `src/pyefis/instruments/ai/pose.py`):
      subscribes to LAT/LONG/ALT/PITCH/ROLL/HEAD (+ GS, TRACK, VS when
      published), timestamps each update, and exposes `sample(now)`
      returning an interpolated/extrapolated pose. v1 algorithm:
      dead-reckon lat/lon from GS+TRACK since the last GPS fix (cap
      extrapolation at ~2 s, then hold); ALT extrapolated from VS the
      same way; attitude passthrough (AHRS rates are near display rate
      already). Pure-Python, no Qt — unit-test with synthetic update
      sequences (1 Hz GPS, 25 Hz attitude).
- [ ] AI widget: FIX slots write into PoseSource (or plain attrs) and no
      longer call `self.update()`. A `QTimer` at `frame_rate` (config
      key, default 30) samples the pose and calls `update()`. The timer
      can skip the repaint when the sampled pose is unchanged and no SVS
      data is dirty (parked aircraft → near-zero CPU).
- [ ] Old/bad/fail flags on the pose FIX items still trigger immediate
      repaint (flag changes are alerts, not motion).
- [ ] Harness support: add `SVS_SIM_MOTION=1` (or similar) to
      `tests/visual_svs_test.py` to feed scripted 1 Hz position updates
      with GS/TRACK so smoothness is observable without a gateway.
- [ ] Measure: with the harness simulating 1 Hz GPS, confirm visually
      smooth 30 Hz terrain motion; with the timer at 30 Hz, confirm main
      thread CPU is bounded (compare against Phase 0 baseline).

Out of scope (note for later): applying the same pattern to tapes/HSI.
This phase touches only the AI widget.

Done when: AI repaints at a fixed configurable rate; terrain glides
through simulated 1 Hz GPS updates; pose unit tests pass; no FIX
`valueChanged` handler in the AI calls `update()` directly.

## Phase 5 — GL viewport compositing: kill the FBO readback (1–2 days)

Goal: remove the per-frame `fbo.toImage()` (glReadPixels sync) +
`drawImage` blit. STRUCTURAL_REVIEW.md section 4. Do after P3.

- [ ] Set `QApplication` attribute `AA_ShareOpenGLContexts` at startup
      (src/pyefis/main.py, before the app is constructed).
- [ ] Give the AI's QGraphicsView a `QOpenGLWidget` viewport. Verify the
      QPainter-drawn scene items (pitch ladder, FPM, bank markers) render
      identically through Qt's GL paint engine — this is the main risk;
      check text rendering and thin lines specifically.
- [ ] In `_SVSGraphicsItem.paint`: `painter.beginNativePainting()`, make
      the SVS GL resources current on the *widget's* context (shared), 
      render terrain + overlays directly to the default framebuffer with
      scissor/viewport set to the AI rect, `endNativePainting()`.
      Alternative if state-leak problems appear: keep rendering into the
      offscreen FBO but composite it as a textured quad — still zero
      readback.
- [ ] Delete the `fbo.toImage()` path; keep an FBO-capture hook only for
      the SIGUSR1 screenshot feature and golden-image tests
      (`QOpenGLWidget.grabFramebuffer`).
- [ ] Pi 5 validation pass (eglfs): this phase is the most
      platform-sensitive in the plan. Test on the Pi before declaring
      done; capture perf numbers vs the Phase 0 baseline at DFW.

Done when: no glReadPixels in the per-frame path (verify via perf log —
the readback segment disappears); golden poses unchanged; Pi 5 run clean;
measured frame cost drop recorded in the perf doc.

## Phase 6 — Copernicus GLO-30 terrain (2–3 days, independent)

Goal: global coverage (fixes the >60°N hole — Yukon/NWT/Nunavut) and
30 m resolution. STRUCTURAL_REVIEW.md "30 m terrain" section.

- [ ] `tools/fetch_glo30.py`: download 1°×1° Copernicus GLO-30 GeoTIFF
      tiles (AWS Open Data bucket, no auth) for a bbox, convert each to
      the existing HGT layout at 3601×3601 int16 big-endian (or a sibling
      format — see next step). Reuse/extend the SRTM downloader work in
      the `faa-cifp-data` repo if convenient, but the converter lives
      here. GeoTIFF reading: prefer `rasterio` if available in C:/pylib /
      on the Pi; otherwise GDAL CLI invocation; document the dependency.
- [ ] Runtime tile support: detect tile resolution from file size
      (1201² × 2 = 2,884,802 bytes vs 3601² × 2 = 25,934,402) in
      `load_tile` / `tiles.py`; carry samples-per-tile through
      `elevation_at`, `_sample_elevations`, and the GL patch builder
      instead of the `SRTM3_SAMPLES` constant. Mixed-resolution tile
      trees must work (GLO-30 where downloaded, SRTM3 elsewhere).
- [ ] GPU memory experiment (do this BEFORE wiring 1-arc-sec into the
      patch): a 2×2° patch at 3601/deg in R32F is ~207 MB. Try, in order:
      (a) `GL_R16` normalized via `EXT_texture_norm16` (Mesa V3D exposes
      it) storing metres+1000 offset — 104 MB, still big;
      (b) half-degree patch rebuild (1.5°×1.5° coverage) at R16 — ~58 MB;
      (c) two-level scheme — 1-arc-sec inner patch + 3-arc-sec outer
      patch, two samplers, vertex shader picks by distance. Record
      upload times and FPS on the Pi 5 in the perf doc; pick the simplest
      one that fits. (a)+(b) combined is the expected landing spot.
- [ ] Water sentinel: GLO-30 has no voids over ocean (it has values);
      the `is_water` detection (`elev == 0.0` + missing-tile sentinel)
      still works for ocean but verify coastlines at KSBA against the
      Phase 0 golden; the water-polygon overlay does the real work
      anyway.
- [ ] Verify a >60°N pose renders terrain: Whitehorse CYXY
      (60.71, -135.07, ALT 4500, HEAD 130).

Done when: CYXY shows real terrain; KASE/KSBA goldens look the same or
better (sharper relief); Pi 5 frame time within budget with the chosen
texture scheme; docs/svs_rendering.md updated with the data source and
fetch instructions.

## Phase 7 — Visual polish: MSAA + distance haze (½–1 day, after P3/P5)

- [ ] MSAA: 4× samples on the SVS render target (FBO format sample count,
      or the QOpenGLWidget surface format after P5). Verify on V3D; fall
      back to no-MSAA silently if unsupported.
- [ ] Distance haze: fragment-shader fog on terrain + water,
      `mix(color, u_horizon_color, 1.0 - exp(-d / u_haze_dist))` with
      per-fragment distance passed from the vertex stage. Config keys
      `haze: true`, `haze_distance_nm` (default ~40). Horizon colour
      should match the AI sky/ground boundary tones so the terrain fades
      into the existing horizon rather than a foreign colour.
- [ ] Do NOT fog the runway markings/designators/obstacle poles beyond
      what terrain gets — they are awareness symbology; fog terrain and
      water only, or fog symbology at half strength. Decide by eye at the
      KASE 10k pose and document the choice.

Done when: A/B screenshots at KASE 10k and KSBA committed to the perf
doc; jaggies visibly reduced; far terrain fades naturally.

## Phase 8 — Scenery packs: build-time geometry + unified data layer (3–5 days, optional/deferrable)

Goal: per-frame Python approaches zero; one data pipeline. This is the
largest lift and the most deferrable — the 1 s collect caches are an
acceptable interim. STRUCTURAL_REVIEW.md section 5.

- [ ] Design a pack schema first (commit the design before code): one
      sqlite per region with layers (water / runways / markings /
      designator-quads / obstacles / flags), geometry stored as
      ready-to-upload float32 ENU-metre blobs keyed by 0.25° spatial
      tile + the tile's own local origin, plus a manifest table
      (source product, AIRAC/DOF cycle, effective dates, schema version).
- [ ] Extend the existing build tools (`build_airport_db.py`,
      `build_obstacle_db.py`, `build_water_db.py` / `fetch_geofabrik_water.py`)
      to emit the pack format; the marking/designator emission code in
      `geometry.py` moves into the build tools (it stops being runtime
      code).
- [ ] Runtime: a `SceneryCache` that owns resident GPU buffers per tile;
      per frame = set-difference of in-range tile ids vs resident, async
      upload of missing tiles (worker thread feeding a main-thread upload
      queue), draw resident buffers. The five collect/TTL caches in
      SVSRenderer are deleted.
- [ ] Out-of-cycle annunciation: if today's date is past the pack's
      effective-to date, show a small "DATA" amber flag (config-gateable).

Done when: frame path contains no sqlite queries and no geometry
emission; cache-miss frame hitches (visible in the perf log as 1 Hz
spikes today) are gone; pack rebuild documented end-to-end.

## Phase 9 — ADS-B traffic + highway-in-the-sky (2–4 days, after P3)

Traffic (cross-repo: needs fix-gateway work first):

- [ ] Investigate what the fix-gateway `stratux` plugin publishes for
      GDL90 traffic reports today (repo:
      `../fix-gateway`, plugin `stratux`). If traffic isn't published,
      define FIX keys (e.g. indexed `TRAFFIC<n>` group carrying lat, lon,
      alt, track, GS, callsign, age) and implement gateway-side. This is
      a separate repo/branch/commit stream — do not mix into pyEfis
      commits.
- [ ] pyEfis side: subscribe to the traffic keys (graceful-missing-key
      pattern per CLAUDE.md), maintain a target table with staleness
      expiry, render each target as a billboarded textured quad (diamond
      symbology, filled/hollow by threat, relative-altitude label via
      the glyph atlas) through the overlay pipeline. Cap at nearest ~20
      targets.
- [ ] Visual harness: synthetic traffic injection env var for testing
      without hardware.

Highway-in-the-sky:

- [ ] Source the active flight plan (VirtualVfr / FMS module — survey
      what pyEfis exposes today; if nothing routes a plan to the AI,
      define the minimal interface and note FMS work separately).
- [ ] Render HITS as a series of magenta rectangular frames (4 thin
      quads each) along the leg at fixed along-track spacing (~0.5 NM),
      at leg altitude; reuse the flat-color overlay shader unchanged.
- [ ] Gate behind config `hits: true`, default off until flight-tested.

Done when: synthetic traffic renders correctly at the DFW pose; HITS
frames track a two-leg test plan; both degrade silently when their data
sources are absent.

## Phase 10 — Chart/satellite draping (3–4 days, after P6)

Full design in STRUCTURAL_REVIEW.md "Chart/satellite draping". Summary
execution order:

- [ ] Build tool `tools/build_chart_pack.py`: ingest user-supplied
      georeferenced rasters (FAA sectional GeoTIFFs public domain;
      Canadian VNC user-supplied due to NavCanada licensing; Sentinel-2
      cloudless for the global satellite layer), `gdalwarp` to
      equirectangular, slice to 1°×1° tiles at 2048 px/deg, pre-compress
      ETC2 (KTX2 container or raw ETC2 blobs in sqlite).
- [ ] Runtime: chart patch texture alongside the heightmap patch, same
      half-degree rebuild trigger, same UV (the terrain vertex shader
      already computes it — pass to fragment as varying).
- [ ] Fragment shader mode switch (uniform): clearance (current) /
      draped / hybrid. Hybrid = draped base modulated by Lambertian
      intensity, with WARNING/CONFLICT tint blended on top when
      clearance is low — the terrain-awareness function must survive
      draping. Skip water polygons in draped modes.
- [ ] Night dimming multiplier on the draped output (config key; charts
      are mostly white paper).
- [ ] HMI action + screen YAML key for mode selection, following the
      existing config patterns.

Done when: KSBA pose renders draped sectional and draped satellite with
correct georegistration (runway footprint on the chart aligns with the
GL runway polygon); hybrid mode shows magenta tint on conflicting
terrain; mode switching works from config.

---

## Appendix — app-level cleanup (outside SVS, take opportunistically)

- [ ] `FixItemMixin` base for instruments: encapsulate the
      `fix.db.get_item` / `valueChanged` / `oldChanged` / `badChanged` /
      `failChanged` + graceful-missing-key boilerplate that all ~43
      instruments hand-roll. Migrate instruments incrementally — AI
      first (it gains the most), then one instrument per commit as
      touched for other reasons. Do not big-bang this.

## Effort summary

| Phase | Scope                                  | Est.     |
|-------|----------------------------------------|----------|
| 0     | Baseline & guardrails                  | 0.5 d    |
| 1     | Finish overlays (flags + text)         | 0.5–1 d  |
| 2     | Delete CPU era, module split           | 1–2 d    |
| 3     | Unified camera, ENU, curvature         | 2–3 d    |
| 4     | Frame clock + pose interpolation       | 1–2 d    |
| 5     | GL viewport, kill readback             | 1–2 d    |
| 6     | Copernicus GLO-30                      | 2–3 d    |
| 7     | MSAA + haze                            | 0.5–1 d  |
| 8     | Scenery packs (deferrable)             | 3–5 d    |
| 9     | Traffic + HITS                         | 2–4 d    |
| 10    | Chart/satellite draping                | 3–4 d    |

Core structural work (P0–P5): ~7–11 days. Everything: ~17–28 days.
