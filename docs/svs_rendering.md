# SVS Rendering Tiers and Resolution

Notes on the SVS terrain renderer's grid resolution, why it matters, and the
path to native-resolution rendering.

## Tiers

Defined in `GRID_SIZES` / `POLAR_DEFAULTS` at [src/pyefis/instruments/ai/svs.py](../src/pyefis/instruments/ai/svs.py):

| Tier         | Grid                  | Total quads | x86 ms/frame† | Notes                              |
|--------------|-----------------------|-------------|---------------|------------------------------------|
| `cpu_sparse` | 48 × 48 rect          | 2,209       | 23            | ~15 Hz on Raspberry Pi 4           |
| `cpu_dense`  | 128 × 128 rect        | 16,129      | 108           | ~20 Hz on Raspberry Pi 5 / x86     |
| `cpu_ultra`  | 192 × 192 rect        | 36,481      | 220           | ~2.3× more quads than dense        |
| `polar`      | 80 × 120 fan (default)| 9,401       | 106           | Distance-dependent LOD — see below |
| `opengl`     | (stub)                | —           | —             | Not implemented; falls back to sparse |

† Measured at 640×480, range_nm=30, grid_lines=true, Aspen pose (39.20°N
106.85°W 12,000 ft, head 150°). Frame times reflect the vectorised
fill/grid_lines path; the per-cell aggregates and shade-key calculation
run as whole-array NumPy ops, only the unavoidable Qt object construction
is done per cell.

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

## Path to Native: OpenGL Tier

The `opengl` tier is a stub today (`GRID_SIZES["opengl"] = 48` falls back to
sparse). The implementation path is:

1. Build a `QOpenGLWidget` mesh whose vertices are sampled directly from the
   tile cache.
2. Pass elevation as a heightmap texture or as a vertex attribute.
3. Move slope shading into a fragment shader (Lambertian on the geometric
   normal, identical math to the current CPU path).
4. Use the existing tile cache and visibility/clearance logic.

GPU rasterisation handles 1 M+ triangles trivially, so native resolution
becomes feasible. Tracked as part of issue #19 (rendering tiers).

## Practical Guidance

- **Default**: `polar`, `range_nm: 30`, `auto_range: true`,
  `grid_lines: false`. Best near-field clarity per CPU cycle.
- **Wide-area framing** (50 NM+, distant peaks): `polar` with
  `auto_range: false` and `radial_warp: 1.5` to push more cells outward.
- **Near-terrain detail**: `polar` already samples at SRTM3 native size
  near the aircraft. If you specifically want a uniform near/far grid for
  comparison, fall back to `cpu_dense`.
- **Legacy tiers** `cpu_sparse` / `cpu_dense` / `cpu_ultra` remain available
  for A/B comparison and as conservative fallbacks.
- **Beyond polar**: don't add more CPU tiers. Wait for the OpenGL tier.

## Related

- Spec: `docs/requirements.md` EFIS-SVS-001 through EFIS-SVS-015
- Issues: #19 (rendering tiers), #24 (vectorise sample_elevations)
- Visual harness: `tests/visual_svs_test.py` — env vars `SVS_RENDERER`,
  `SVS_RANGE`, `SVS_AUTO_RANGE`, `SVS_GRID_LINES`, `SVS_LAT`, `SVS_LON`,
  `SVS_ALT`, `SVS_HEAD`, `SVS_PITCH`, `SVS_ROLL`, `SVS_TILE_PATH`.
