# AER-4604 NE lake dedup: before / after

Each PNG is one `TerrainLayer._render` window (600 x 600, north up) on
flat 500 m land, so every blue pixel is polygon fill. Left = before (the
water-na pack as published, cycle 2026q2r6, drawn as the AER-4596 union).
Right = after (the same rows with `build_water_db.drop_covered_ne_lakes`
applied, which drops each Natural Earth lake that OSM water already draws).

| File | Scene | Range | NE lakes dropped (cover / bbox IoU) |
|------|-------|-------|------|
| `mille_lacs_flat.png` | Mille Lacs, 46.25 N 93.65 W | 10 NM | 0.96 / 0.85 |
| `gsl_flat.png` | Great Salt Lake, 41.1 N 112.5 W | 10 NM | 0.62 / 0.82, 0.75 / 0.63 |
| `gsl_wide_flat.png` | Great Salt Lake, 41.15 N 112.45 W | 30 NM | same |

The pass runs on a cut of the pack: every row whose bbox meets the scene
window, widened to the full bbox of any NE lake in it. A lake's cover
depends only on rows that meet its bbox, so the decision matches a whole-pack
run.

Regenerate:

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src python3 \
    docs/images/aer4604/capture.py /path/to/water-na.sqlite docs/images/aer4604
```
