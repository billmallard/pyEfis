# AER-4457 / MP13 (pyEfis #203): no dark border during a pinch-out

Each image is a contact sheet of four frames grabbed **mid-gesture** while
pinching out from 10 NM to 40 NM, after the 40 NM range had rendered once.
Columns left to right: 15, 25, 35 and 40 NM. **Top row: `dev` @ eed5e72.
Bottom row: this branch @ ac219b9.** Frames are scaled to 0.5x.

- `pinch_out_trk0.png`: track 0 (north up on screen).
- `pinch_out_trk37.png`: track 37, track-up, so the window image is rotated.

On `dev` the stale 10 NM image shrinks toward the centre and the rest is
the dark fill. On the branch, the 40 NM image fills the border behind it.
The thicker roads at the edges are the 40 NM roads image scaled up. That
is what any stale image looks like mid-gesture, and the settle render
replaces it.

Dark-fill fraction of each frame (pixels exactly `(16, 24, 32)`, the
widget's background), from `result_*.json`:

| frame | dev trk 0 | branch trk 0 | dev trk 37 | branch trk 37 |
|---|---|---|---|---|
| 15 NM | 0.025 | 0.000 | 0.045 | 0.000 |
| 25 NM | 0.443 | 0.000 | 0.475 | 0.000 |
| 35 NM | 0.710 | 0.000 | 0.709 | 0.000 |
| 40 NM | 0.769 | 0.000 | 0.769 | 0.000 |

## Reproduce

On a box with the makerplane-data packs (the Beelink), from the root of
the pyEfis checkout under test:

```sh
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:tools python3 \
    docs/aer-4457-evidence/pinch_out_frames.py --out OUT --track 37 \
    --tile-path /data/makerplane-data/terrain/tiles \
    --water-db /data/makerplane-data/water/current/water.sqlite \
    --highway-db /data/makerplane-data/highways/current/highways.sqlite \
    > OUT/result.json
```

The script reuses `tools/bench_map_gestures.py` for the mock FIX bus, the
widget, event pacing (90 `zoom_by` events at 60 Hz) and the MP1 gesture
bracket, at that tool's default scene (650x1040, 35.8N 78.8W). To run it
against `dev`, copy it into a `dev` checkout first, since `dev` does not
have it. The contact sheets were assembled from the four
`frame_<NN>nm.png` grabs per run with PIL (paste at 0.5x, 8 px gutters).
