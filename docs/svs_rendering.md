# SVS Rendering Tiers and Resolution

Notes on the SVS terrain renderer's grid resolution, why it matters, and the
path to native-resolution rendering.

## GL-required

As of the gpu-required branch (P2 of docs/svs_structural_plan.md) the
CPU rendering tiers (cpu_sparse / cpu_dense / cpu_ultra / polar) are
deleted. The only renderer is the GPU pipeline in svs_gl.py — the
polar-fan heightmap mesh plus every overlay (water, obstacles, runways,
markings, designators, airport flags). The `renderer:` config key is
accepted and ignored (deprecation warning) for config compatibility.

If a GL context cannot be created, or any GL draw fails, the SVS
disables itself permanently for the process and the AI widget
annunciates **SVS UNAVAIL** in amber. There is no CPU fallback: a
silently degraded terrain picture that omits obstacles is worse than
an honest absence.

The polar mesh parameters (n_range, n_az, fov_deg, radial_warp,
r_min_nm) are accepted in config for backward compatibility but are
**dead** — nothing in `src/pyefis` reads them (confirmed AER-1478, and
deleted from `SVSRenderer.__init__`/`POLAR_DEFAULTS`). The GL fan has
no azimuth cull of its own; its horizontal extent is set purely by the
AI viewport's aspect ratio — see "Azimuthal extent" below.

## Azimuthal Extent (HFOV)

There is no configured forward-fan angle. The terrain drawn horizontally
spans whatever pixels-per-degree the GL camera is given, because the same
roll/pitch/yaw transform used for the pitch ladder and FPM projects
terrain too:

    HFOV_deg = viewport_width_px * TERRAIN_HFOV_PITCH_DEG / viewport_height_px

**AER-1973 (2026-09-23) decoupled this from `pitchDegreesShown`.**
`pitchDegreesShown` (`ai_widget.py`, 50 as of AER-1973, was 30) sets only
the pitch ladder's vertical gain now. The terrain's horizontal scale is
pinned separately at `_TERRAIN_HFOV_PITCH_DEG = 30.0`
(`svs_gl.py`) via `camera.view_projection`'s `pixels_per_deg_h` parameter
(the AER-1806 decouple hook, wired to `svs_gl.py:_update_camera` by
AER-1973) — so a `pitchDegreesShown` edit changes the vertical pitch
range shown without dragging the terrain HFOV along with it. `sy` (the
matrix's vertical scale) still follows the live `pitchDegreesShown` — the
terrain has to stay registered with the ladder's degree marks — so
raising `pitchDegreesShown` legitimately shows more sky/ground
*vertically*; it does not widen the picture *horizontally*.

So the half-fan a given panel actually draws is
`(viewport_width_px / 2) / (viewport_height_px / _TERRAIN_HFOV_PITCH_DEG)`,
and it changes with the widget's aspect ratio — e.g. ~50° total on an
800×480 panel, 51.2° on 1024×600, 40° for `tools/svs_capture.py`'s
800×600 capture default. Always compute this for the specific viewport in
question rather than assuming a fixed number (AER-1478); and compute it
from `_TERRAIN_HFOV_PITCH_DEG`, not the live `pitchDegreesShown`, now that
the two are independent (AER-1973).

## Cell Size and Visible Range

The grid covers `±range_nm` in both latitude and longitude around the aircraft.
Cell size on the ground is therefore:

    cell_nm = (2 × range_nm) / grid_n

Examples at typical SVS settings:

| Range  | Tier        | Cell size  |
|--------|-------------|------------|
| 30 NM  | cpu_sparse  | 1.25 NM    |
| 30 NM  | cpu_dense   | 0.47 NM    |
| 30 NM  | cpu_ultra   | 0.31 NM    |
| 50 NM  | cpu_sparse  | 2.08 NM    |
| 50 NM  | cpu_dense   | 0.78 NM    |
| 50 NM  | cpu_ultra   | 0.52 NM    |

Larger cells average terrain over a wider area, which flattens the slope-shading
output and reduces apparent depth. When increasing `range_nm`, step the renderer
up a tier to keep cell size from growing too far.

## Auto-Range

`auto_range: true` (default) reduces the rendered range based on aircraft
altitude and AGL — see [svs.py:236-251](../src/pyefis/instruments/ai/svs.py).
The rendered range is

    min(range_nm, max(min_range_nm, 0.1·√AGL_ft, 0.001·MSL_ft))

This keeps near-ground views useful but can clip distant peaks. Disable with
`auto_range: false` to render the full configured `range_nm`.

## Grid Lines Overlay (removed)

The mesh-wireframe overlay was deleted in P7 — it was a CPU-era
debugging aid, superseded by MSAA + distance haze. The `grid_lines`
config key is ignored.

## Native SRTM3 Resolution

Source data:

- 1°×1° HGT tile
- 1201 × 1201 samples per tile
- ≈ 3 arc-seconds ≈ 90 m / 295 ft per sample at the equator

A 30 NM range spans 60 NM ≈ 111 km on the ground. Rendering at native sample
density would require ≈ **1,235 cells per side**:

- ~1.5 M cells
- ~3 M triangles per frame

The pure-Python NumPy + QPainter path cannot sustain that at video rate. The
current `cpu_ultra` (192) is near the practical CPU ceiling.

## Polar Tier — Distance-Dependent LOD

The rectangular tiers sample on a uniform lat/lon grid. Two consequences
follow on a low-power CPU renderer:

1. **About half of the samples are behind the aircraft** and get masked out
   by the `visible = (x_fwd > 0) & ...` test. That's polygon budget paid
   for but never drawn.
2. **All cells have the same ground footprint**, so near-aircraft cells
   project to large screen areas (blocky near-field) while horizon cells
   project to <1 pixel (wasted detail in the far field).

The `polar` tier rebuilds the grid in forward-fan (range, azimuth)
coordinates centred on the aircraft. Two payoffs:

- **No wasted samples behind the aircraft** — ~2× effective resolution at
  the same total cell count.
- **Distance-dependent LOD for free** — the radial axis is sampled with a
  warp `r_i = r_min + (r_max - r_min) · (i / (n_range-1))**p` so cells get
  finer toward the aircraft.

### Polar config keys (screen YAML) — legacy, dead

This example describes the deleted `renderer: polar` CPU tier (see
"GL-required" above). The keys are still accepted for config
compatibility but nothing reads them, including `fov_deg` — the GL
fan's azimuthal extent is not configurable; it follows the viewport
aspect ratio (see "Azimuthal Extent (HFOV)" above).

```yaml
svs:
    enabled: true
    renderer: polar
    tile_path: /media/terrain/srtm3
    range_nm: 30
    n_range:     80    # radial samples — dead, unread
    n_az:        120   # azimuthal samples — dead, unread
    fov_deg:     140   # forward field-of-view — dead, unread
    radial_warp: 1.5   # outer cell ~10× inner cell — dead, unread
    r_min_nm:    0.05  # epsilon at r=0 to avoid the singularity — dead, unread
```

### Cell sizes at the polar default (n_range=80, warp=1.5, range_nm=30)

| Distance from a/c | Cell size (radial) | Notes                              |
|-------------------|--------------------|------------------------------------|
| 0 NM (inner ring) | ~ 0.05 NM ≈ 90 m   | matches SRTM3 native sample size   |
| 5 NM              | ~ 0.31 NM ≈ 575 m  | finer than `cpu_dense` here        |
| 15 NM (mid)       | ~ 0.70 NM ≈ 1.30 km| similar to `cpu_sparse`            |
| 30 NM (horizon)   | ~ 1.10 NM ≈ 2.04 km| coarser than `cpu_dense`, but each cell <1 pixel anyway |

### Tuning advice

- `radial_warp` between **1.0 and 2.5**. 1.0 = uniform radial spacing;
  1.5 (default) gives a ~10× inner/outer cell ratio that keeps both the
  near-field and horizon usable. Values above 2.5 leave the far horizon
  too blocky for SVS purposes.
- `fov_deg` is dead (unread) on both the removed CPU polar tier and the
  GL renderer. There is no configurable FOV — the drawn azimuthal
  extent follows the viewport aspect ratio; see "Azimuthal Extent
  (HFOV)" above.
- For Raspberry Pi 4: try `n_range=64, n_az=96, radial_warp=2.0`
  (~6,000 quads) before reaching for `cpu_sparse`. For Pi 5 and x86,
  the defaults (n_range=80, n_az=120) come in ~25% faster than
  `cpu_dense` while improving near-field clarity. For x86 with room to
  spare, `n_range=96, n_az=144, radial_warp=1.5` (~13.6k quads) matches
  `cpu_dense` frame time with much better near-field.

### Slope shading on the polar grid

The polar path computes per-cell slopes in geographic (E, N) frame by
rotating the radial/tangential gradients via the per-column bearing
(`heading + az_j`). This keeps the same hill shaded the same way
regardless of viewing heading — see the polar branch at
[svs.py](../src/pyefis/instruments/ai/svs.py) inside the slope-shading block.

## OpenGL Tier — GPU Rasteriser

The `opengl` tier moves terrain rasterisation onto the Pi 5's V3D GPU
(or any desktop OpenGL stack). On Pi 5 it runs at ~196 FPS — 30× faster
than the polar CPU tier at the same pose, with p95 frame time within
0.2 ms of p50. Implementation lives in
[svs_gl.py](../src/pyefis/instruments/ai/svs_gl.py).

### Architecture

```
SVSGraphicsItem.paint(painter, opt, widget)
└── SVSRenderer.draw()
    └── (renderer == "opengl") SVSGLRenderer.draw():
        1. makeCurrent(offscreen QOpenGLContext + QOffscreenSurface)
        2. lazy-build FBO, polar mesh VBO/IBO, heightmap texture
        3. rebuild heightmap when aircraft crosses a half-integer
           degree boundary (kept >= 0.5 deg from every patch edge)
        4. glDrawElements over the 64×96 polar fan
           - vertex shader: polar (t, az) -> world -> screen, heightmap
             texture lookup, finite-difference normal
           - fragment shader: Lambertian shading + clearance buckets
             (SAFE / CAUTION / WARNING / CONFLICT / WATER) with the
             airport-proximity 2-colour collapse mirrored from the
             polar CPU tier
        5. fbo.toImage() -> QImage
    -> painter.drawImage(0, 0, image)
    -> existing CPU overlays (runways, obstacles, markings, flags)
       paint on top via the same QPainter
```

The FBO + blit architecture means the `SVSGraphicsItem` scene-graph
integration, the pitch-ladder z-order, and every CPU overlay path stay
exactly as they are. The GL context lives entirely inside
`SVSGLRenderer`; nothing else in pyEfis knows about it.

### Failure policy

Any exception during `SVSGLRenderer.__init__` or any `draw()` sets
`SVSRenderer.gl_failed`, permanently disabling the SVS for the
process; the AI widget annunciates SVS UNAVAIL. One-shot — GL is
never re-attempted.

### Heightmap texture

A 2x2-tile patch (2402×2402 R32F = ~22 MB) is uploaded once per
half-integer-degree of aircraft movement. The patch origin is
`floor(ac_lat - 0.5), floor(ac_lon - 0.5)`, which keeps the aircraft
at least 0.5° (~30 NM) from every patch edge — far enough that
`GL_CLAMP_TO_EDGE` never paints fake-flat terrain ahead of the nose,
even at the default 30 NM range. Rebuilds use the same `TileCache`
the CPU tiers use; once tiles are cached the upload itself is ~4 ms
of GPU VRAM transfer.

### Config

```yaml
svs:
    enabled: true
    renderer: opengl
    tile_path: /media/terrain/srtm3
    range_nm: 30
```

The GL tier reuses the same polar (range, azimuth) mesh topology as the
removed CPU tier, executed on the GPU, but none of the old tuning knobs
(`n_range`, `n_az`, `fov_deg`, `radial_warp`, `r_min_nm`) are read —
mesh resolution and azimuthal extent are not configurable; the latter
follows the viewport aspect ratio (see "Azimuthal Extent (HFOV)"
above). The keys are still accepted in YAML for config compatibility
and silently ignored (AER-1478).

### Pi 5 verdict

At 800×600 viewport, default polar grid, range_nm=30, auto_range=true:

- mean 5.1 ms/frame across KSBA offshore, KASE short final, KASE 10k MSL
- p95 within 0.2 ms of p50 (no jitter)
- ~196 FPS sustained — leaves enormous headroom for the CPU overlay code

Stage-1 target was 60 FPS. Actual is >3× that. The V3D was the unused
silicon in the system; freeing the A76 cores from rasterisation also
makes the CPU available for `_draw_runways`, `_draw_obstacles`, and
`_draw_runway_markings` to run at their natural cost without frame
budget pressure.

## Practical Guidance

- `range_nm: 50` + `auto_range: true` (defaults) render to the true
  horizon. Polar mesh defaults (n_range=80, n_az=120) are fine on
  Pi 5; n_range=64, n_az=96 trims GPU cost slightly if needed.

## Terrain data sources

Tile resolution is per-file: 1201x1201 (SRTM3, 3 arc-sec, 60N-56S) and
3601x3601 (1 arc-sec) HGT tiles coexist in one tile tree.

**Copernicus GLO-30** is the preferred source — true global coverage
(fixes the SRTM >60N hole over northern Canada) at 30 m:

    python tools/fetch_glo30.py  --dest <raw-dir>            # ~88 GB for NA
    python tools/convert_glo30.py --src <raw-dir> --dest <tile-root>

The GL heightmap patch decimates to fit `heightmap_max_px` (default
4096) and the driver texture limit — GLO patches render at ~60 m
effective; CPU elevation sampling always uses full native resolution.

## Related

- Spec: `docs/requirements.md` EFIS-SVS-001 through EFIS-SVS-015
- Issues: #19 (rendering tiers), #24 (vectorise sample_elevations)
- Visual harness: `tests/visual_svs_test.py` — env vars `SVS_RENDERER`,
  `SVS_RANGE`, `SVS_AUTO_RANGE`, `SVS_GRID_LINES`, `SVS_LAT`, `SVS_LON`,
  `SVS_ALT`, `SVS_HEAD`, `SVS_PITCH`, `SVS_ROLL`, `SVS_TILE_PATH`.
