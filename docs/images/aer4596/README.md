# AER-4596 moving-map water raster: before / after

Each PNG is one `TerrainLayer._render` window (1024 x 1024, north up),
left = before (every ring of every polygon in one shared even-odd
accumulator), right = after (`raster.fill_union`: even-odd within a
polygon, union across polygons). Water pack: `water-na.sqlite`, cycle
2026q2r6.

| File | Scene | Range | Terrain |
|------|-------|-------|---------|
| `gsl_flat.png` | Great Salt Lake, 41.1 N 112.5 W | 10 NM | flat 500 m |
| `mille_lacs_flat.png` | Mille Lacs, 46.25 N 93.65 W | 10 NM | flat 500 m |
| `gulf_seam_n26_flat.png` | Gulf of Mexico on the 26 N seam, 82.45 W | 5 NM | flat 500 m |
| `gulf_seam_n26_flat_zoom8x.png` | 64 x 32 px crop of the above at the seam, 8x nearest-neighbour | 5 NM | flat 500 m |
| `gulf_seam_n26_terrain.png` | same seam, real GLO-30 tiles | 5 NM | real |

"Flat 500 m" isolates the polygon raster: no terrain tile is water, so
every blue pixel is the polygon fill. The GSL, Mille Lacs and Texas-seam
tiles were not available where these were rendered. The real-terrain seam
is byte-identical before and after (0 px differ): open sea sits at
elevation 0, which `_sample` already marks as water underneath the
polygons.

Regenerate:

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src python3 \
    docs/images/aer4596/capture.py \
    /path/to/water-na.sqlite docs/images/aer4596 /path/to/terrain/tiles
```

The 8x crop is cut from `gulf_seam_n26_flat.png` around the changed
rows (510-512), columns 480-543, with PIL `Image.NEAREST`.
