# RD2 evidence: moving-map roads at true scale, with casing (pyEfis #162)

`ab_crop4x_dfw_1nm.png`: left, `dev` before RD2; right, this branch. DFW
(I-35E / I-635, 32.92 N 96.93 W), 1 NM range, the bench map window
(650x1040, ownship 520 px below the top edge). A 160x160 crop of the
window image around the ownship, upscaled 4x nearest-neighbour, over a
flat dark green. This is the worker's window image. The widget blits it at
about 1/1.5 scale on that window, so a 1 px casing is about 0.7 screen px.

At 2 NM and wider the two images are byte-identical on this window, so
there is nothing to show; see the table below.

## Measured on the Beelink (real `highways-conus` pack, best of 3)

| scene | range | pre ms | RD2 ms | road px | changed px |
|---|---:|---:|---:|---:|---:|
| dfw | 1 NM | 15.5 | 27.3 | 57622 | 90741 |
| dfw | 2 NM | 25.9 | 26.1 | 80978 | 0 |
| dfw | 5 NM | 99.0 | 99.4 | 128458 | 0 |
| dfw | 20 NM | 223.6 | 222.8 | 80016 | 0 |
| dfw | 40 NM | 133.4 | 134.2 | 47305 | 0 |
| dfw | 80 NM | 143.4 | 143.1 | 23615 | 0 |
| ksba | 1 NM | 3.1 | 7.8 | 12069 | 19556 |
| ksba | 2 NM | 4.5 | 4.6 | 15055 | 0 |
| ksba | 5 NM | 6.7 | 6.6 | 11536 | 0 |
| ksba | 20 NM | 13.1 | 13.3 | 12187 | 0 |
| ksba | 40 NM | 22.1 | 22.1 | 14478 | 0 |
| ksba | 80 NM | 160.0 | 160.6 | 18893 | 0 |

"road px" is the pre-RD2 image's non-transparent count. "changed px" is
pixels that differ in any channel. Times are the worker `_render` (off the
paint path).

## Regenerate

On a box with the pack and pyEfis' venv (no display needed, does not touch
the live checkout):

```bash
git show e2d89d7:src/pyefis/instruments/map/layers/roads.py > roads_dev.py
QT_QPA_PLATFORM=offscreen PYTHONPATH=src python \
  docs/images/rd2_roads/bench_scripts/rd2_ab.py roads_dev.py \
  /data/makerplane-data/highways/current/highways.sqlite out
```
