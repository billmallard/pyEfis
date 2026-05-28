# SVS Rendering Tiers and Resolution

Notes on the SVS terrain renderer's grid resolution, why it matters, and the
path to native-resolution rendering.

## Tiers

Defined in `GRID_SIZES` / `POLAR_DEFAULTS` at [src/pyefis/instruments/ai/svs.py](../src/pyefis/instruments/ai/svs.py):

| Tier         | Grid                  | Total quads | x86 ms/frame† | Pi 5 ms/frame‡ | Notes                              |
|--------------|-----------------------|-------------|---------------|----------------|------------------------------------|
| `cpu_sparse` | 48 × 48 rect          | 2,209       | 23            | —              | ~15 Hz on Raspberry Pi 4           |
| `cpu_dense`  | 128 × 128 rect        | 16,129      | 108           | —              | ~20 Hz on x86                      |
| `cpu_ultra`  | 192 × 192 rect        | 36,481      | 220           | —              | ~2.3× more quads than dense        |
| `polar`      | 80 × 120 fan          | 9,401       | 106           | 153 (6.5 FPS)  | Distance-dependent LOD — see below |
| `opengl`     | 64 × 96 polar on V3D  | 6,049       | —             | **5.1 (196 FPS)** | GPU rasteriser — see below; recommended default on Pi 5 |

† Measured at 640×480, range_nm=30, grid_lines=true, Aspen pose (39.20°N
106.85°W 12,000 ft, head 150°). Frame times reflect the vectorised
fill/grid_lines path; the per-cell aggregates and shade-key calculation
run as whole-array NumPy ops, only the unavoidable Qt object construction
is done per cell.

‡ Measured on Raspberry Pi 5 (eglfs) at 800×600, range_nm=30,
auto_range=true, warmup-trimmed mean over 100 frames at three poses
(KSBA offshore, KASE short final, KASE 10k MSL). p95 is within 0.2 ms
of p50 across all GL samples — jitter is negligible. The `opengl` tier
is ~30× faster than `polar` on the same hardware because the polar
mesh is built once, uploaded as a VBO, and the per-vertex
projection/elevation/Lambertian work runs entirely in the V3D fragment
and vertex shaders; CPU is idle except for `glReadPixels` (~1 ms at
this viewport) and `QPainter.drawImage` of the FBO result.

Selected via screen YAML (`renderer: cpu_dense`) or via the
`SVSRenderer({"renderer": ...})` config dict.

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

## Grid Lines Overlay

Each quad edge is drawn as a 1-pixel `QLineF` on top of the filled terrain
(see [svs.py:409-439](../src/pyefis/instruments/ai/svs.py)). At long range
or with finer tiers, perspective foreshortening compresses distant rows so
the wireframe reads as a dense mesh near the horizon.

Disable with `grid_lines: false` for clean shaded fills only.

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

### Polar config keys (screen YAML)

```yaml
svs:
    enabled: true
    renderer: polar
    tile_path: /media/terrain/srtm3
    range_nm: 30
    n_range:     80    # radial samples
    n_az:        120   # azimuthal samples
    fov_deg:     140   # total forward field-of-view
    radial_warp: 1.5   # outer cell ~10× inner cell
    r_min_nm:    0.05  # epsilon at r=0 to avoid the singularity
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
- `fov_deg` 120-160. Wider FOV adds samples to corners that are nearly
  always off-screen; narrower can cause visible cropping during steep
  banks. 140° (default) covers `±70°` either side of the nose.
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

### Fallback

Any exception during `SVSGLRenderer.__init__` or its first `draw()`
permanently downgrades `self.renderer` to `polar` and logs a warning.
Missing GL driver, Qt build without OpenGL, shader compile failure,
context creation refused — all degrade silently to the CPU path. The
fallback is one-shot; we never re-attempt GL in the same process.

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
    # polar mesh dimensions still tunable via the polar config keys
    n_range:     64
    n_az:        96
    fov_deg:     140
    radial_warp: 2.0
```

The polar tuning knobs (`n_range`, `n_az`, `fov_deg`, `radial_warp`,
`r_min_nm`) apply identically — the GL tier reuses the same polar mesh
topology, just executes it on the GPU.

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

- **Default on Pi 5 or any GL-capable host**: `opengl`, `range_nm: 30`,
  `auto_range: true`. ~196 FPS measured; falls back to `polar` cleanly
  if a GL context can't be created.
- **CPU-only fallback default**: `polar` with the same range/auto-range
  settings. Best near-field clarity per CPU cycle.
- **Wide-area framing** (50 NM+, distant peaks): either tier with
  `auto_range: false` and `radial_warp: 1.5` to push more cells outward.
- **Legacy tiers** `cpu_sparse` / `cpu_dense` / `cpu_ultra` remain
  available for A/B comparison and as conservative fallbacks.
- **Beyond opengl**: vector overlays (runways/obstacles/markings) still
  run on CPU. Stage 2 of the GPU work moves those onto instanced quads
  with marking textures; not implemented today.

## Related

- Spec: `docs/requirements.md` EFIS-SVS-001 through EFIS-SVS-015
- Issues: #19 (rendering tiers), #24 (vectorise sample_elevations)
- Visual harness: `tests/visual_svs_test.py` — env vars `SVS_RENDERER`,
  `SVS_RANGE`, `SVS_AUTO_RANGE`, `SVS_GRID_LINES`, `SVS_LAT`, `SVS_LON`,
  `SVS_ALT`, `SVS_HEAD`, `SVS_PITCH`, `SVS_ROLL`, `SVS_TILE_PATH`.
