# SVS Rendering Tiers and Resolution

Notes on the SVS terrain renderer's grid resolution, why it matters, and the
path to native-resolution rendering.

## Tiers

Defined in `GRID_SIZES` at [src/pyefis/instruments/ai/svs.py](../src/pyefis/instruments/ai/svs.py):

| Tier         | Grid (cells/side) | Total quads | Notes                                  |
|--------------|-------------------|-------------|----------------------------------------|
| `cpu_sparse` | 48                | 2,209       | ~15 Hz on Raspberry Pi 4               |
| `cpu_dense`  | 128               | 16,129      | ~20 Hz on Raspberry Pi 5 / x86         |
| `cpu_ultra`  | 192               | 36,481      | ~2.3× more quads than dense            |
| `opengl`     | (stub)            | —           | Not implemented; falls back to sparse  |

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

- **Default**: `cpu_dense`, `range_nm: 30`, `auto_range: true`,
  `grid_lines: false`. Good for most en-route screenshots.
- **Wide-area framing** (50 NM+, distant peaks): `cpu_ultra` with
  `auto_range: false` to lift the range cap.
- **Near-terrain detail**: `cpu_dense` is enough — auto-range will pull the
  rendered range in to ~5-15 NM, where 0.1-0.2 NM cells already look crisp.
- **Beyond ultra**: don't add more CPU tiers. Wait for the OpenGL tier or add
  `grid_n` as direct config to override `GRID_SIZES` for experiments.

## Related

- Spec: `docs/requirements.md` EFIS-SVS-001 through EFIS-SVS-015
- Issues: #19 (rendering tiers), #24 (vectorise sample_elevations)
- Visual harness: `tests/visual_svs_test.py` — env vars `SVS_RENDERER`,
  `SVS_RANGE`, `SVS_AUTO_RANGE`, `SVS_GRID_LINES`, `SVS_LAT`, `SVS_LON`,
  `SVS_ALT`, `SVS_HEAD`, `SVS_PITCH`, `SVS_ROLL`, `SVS_TILE_PATH`.
