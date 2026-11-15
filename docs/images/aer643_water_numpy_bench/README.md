# AER-643 (MP5) on-glass evidence -- Beelink bench, `aer-643/water-numpy-scanline-fill`

Captured live on the Beelink (`10.110.10.241`), branch staged over
`bench-deploy.sh`'s normal `dev` flow (the script has no `--ref` support yet,
so this was done by hand: fetch + `git checkout -B` the PR branch in
`~/src/pyEfis`, restart `pyefis.service`, SIGUSR1 for the screenshot -- see
the PR body for the exact transcript). `water_raster` was left at its new
default (`numpy`) -- nothing in the live config sets it.

Both captures are a crop of the moving-map panel out of a full-screen
SIGUSR1 grab (`/tmp/pyefis_screenshot.png`, 1920x1080); the SVS/AI panel in
the original frame is blank per the standing note (`QOpenGLWidget`, GL does
not render into an offscreen grab) -- unrelated to this change, cropped out.

- `map_10nm_kcmh.png` -- 10 NM, north up, over KCMH (Columbus OH). Small
  lakes render correctly in blue against the numpy path (default).
- `map_160nm_lake_erie.png` -- 160 NM, same position, after 14 synthetic
  scroll-wheel notches (python-xlib `XTest.fake_input`, no `xdotool` on the
  box) to zoom out and let the worker settle. Lake Erie (top) and several
  rivers/reservoirs render with real multi-lobed shoreline geometry --
  the numpy `fill_even_odd` path on real `water-na 2026q2r6` data, not a
  synthetic fixture.

## Bench timing (`tools/bench_map_terrain.py`, real packs, Raleigh scene per the brief)

```bash
ssh -i $BEELINK_SSH_KEY pyefis@10.110.10.241
cd ~/src/pyEfis
~/pyefis-venv/bin/python3 tools/bench_map_terrain.py \
    --tiles /data/makerplane-data/terrain/tiles \
    --water /data/makerplane-data/water/current/water.sqlite \
    --water-raster numpy \
    --lat 35.8 --lon -78.8 --w 650 --h 1040 --ranges 160 300 --repeat 3
# repeat with --water-raster qt for the A/B
```

| range | water_raster | warm_s |
|---:|---|---:|
| 160 NM | numpy | 0.339 |
| 160 NM | qt (legacy, MP4 decimation still applied) | 0.347 |
| 300 NM | numpy | 0.775 |
| 300 NM | qt (legacy, MP4 decimation still applied) | 0.863 |

**The issue's `<= 0.6 s` bench target is met at 160 NM, not at 300 NM** (0.775 s
numpy vs 0.6 s target). This is a real, not-yet-closed gap -- reported instead
of claimed. Root cause, isolated with a same-process cold-cache comparison
(fresh `WaterDB` per path, no query-decode cache reuse across repeats -- see
the PR body for the script):

```
range=160.0  cold numpy=0.431s  cold qt=0.358s  speedup=0.83x
range=300.0  cold numpy=0.752s  cold qt=0.838s  speedup=1.11x
```

and a water-off baseline at the same sizes (numpy path, no DB configured):

```
range=160.0  warm_s=0.067   range=300.0  warm_s=0.077
```

So of the ~0.75-0.86 s water-path cost at 300 NM, only ~0.08 s is terrain
sampling/palette/gradient/QImage overhead -- the rest is water, and MP5's own
rasterization swap (QPointF/QPolygonF/drawPath -> `fill_even_odd`) is a small,
scene-dependent fraction of it (0.83x-1.11x either direction). The dominant
cost at wide range on this real, dense-coastline scene is the
`WaterDB.polygons_in_range` SQL/BLOB decode of millions of raw vertices
*before* MP4's per-pixel decimation runs (1279 polygons / 2.3M raw vertices
at 160 NM; 1469 / 3.7M at 300 NM) -- identical work in both `water_raster`
paths, and out of MP5's scope (rasterization only). That decode cost is
exactly what Track 2 (MP10, the water-mask pyramid) replaces with one gather
per render regardless of coastline density.
