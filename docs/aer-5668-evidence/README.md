# MAPPAINT1 bench evidence (AER-5668)

Beelink bench, 2026-11-14, the live panel `managed.yaml`: SVS on the left,
the Map tab on the right (ND CTR, 10 NM, track-up; terrain relief, roads,
water, airports, navaids, fixes, airways, an 18-waypoint flight plan). This
is the view from pyEfis #480's investigation.

## Live A/B, `measure.sh`

X-Plane was not running, so `feed.py` writes the 14 keys the X-Plane plugin
writes at the rate the bench measured from X-Plane, 7.6 Hz. It flies a smooth,
hand-flown drift from the investigation's last position: east Tennessee,
track 307, 136 kt, with gentle pitch and roll so the SVS has a new frame to
draw on every tick. Every run uses the same start point and flight.

`run_measure.sh LABEL [X Y]` takes the bench lock, restarts pyEfis, starts
the feed at 20 s of uptime, and runs the investigation's `measure.sh`, which
waits for 75 s of uptime and then samples 15 s with py-spy at 250 Hz. The
investigation's copy writes to `~/perf/2026-11-14-svs-slow/`; this run used
a copy that writes to `~/bench-scratch/aer5668/perf/`. With `X Y` it clicks
there first: 1385,10 is the Engine tab, which hides the map. The branch was
staged with `bench-deploy.sh --ref aer-5668/mappaint1` and restored with
`--restore`. Order: dev, branch, branch without the map, branch, dev.

| run | pyEfis | map paint, ms/s | map repaints/s | map paint ms, med / p90 / max | SVS paints/s | GUI stalls >= 50 ms, per s | GUI idle |
|---|---|---|---|---|---|---|---|
| dev_a | `dev` 5d77ad82 | 184 | 7.0 | 24 / 48 / 84 | 16.7 | 3.27 | 33.9% |
| br_a | c7d9dc3a | 119 | 5.3 | 20 / 48 / 72 | 17.3 | 1.93 | 41.2% |
| br_nomap | c7d9dc3a, Engine tab | 0 | 0 | none | 18.8 | 1.13 | 48.7% |
| br_b | c7d9dc3a | 99 | 4.9 | 16 / 40 / 100 | 17.9 | 1.73 | 40.1% |
| dev_b | `dev` 5d77ad82 | 205 | 6.9 | 28 / 52 / 92 | 15.3 | 3.00 | 35.3% |

With the map off the screen the SVS reaches 18.8 paints a second. Map work
alone cannot take it past that on this bench.

`frame_dev.png` and `frame_branch.png` are DRM scanout grabs (`kmsgrab`)
taken at the end of dev_b and br_b, at the same point in the feed. They show
the same view drawing the same layers. The ETA differs because it is computed
from the wall clock. The pixel-identity claims are made by
`tests/instruments/test_map_paint_cache.py`, not by these frames.

## Offscreen microbench, `mapbench.py`

The same map widget with the live layer set, at 650x1000, built from the
bench's real data and fonts and flown through the real frame clock. It runs
with `QT_QPA_PLATFORM=offscreen`, so it never touches the display.

```
cd <pyEfis tree>        # dev, or the branch
QT_QPA_PLATFORM=offscreen ~/pyefis-venv/bin/python ../mapbench.py --secs 30 --seed N
```

Runs alternated dev, branch, dev, branch on a quiet box (load 0.25):

| | GUI ms/s in map paint | paint ms, median / p90 | layer redraws / reuses in 30 s |
|---|---|---|---|
| dev, 3 runs | 236-238 | 24.2-24.7 / 24.8-25.4 | every paint |
| branch, 3 runs | 140-142 | 10.2-10.7 / 24.3-24.5 | 109-115 / 180-187 |

Cost of one layer redraw, by layer, from the dev runs: roads 6.3 ms, ND
overlay 4.6 ms, terrain 3.7 ms, range rings 2.7 ms, airways 2.1 ms, fixes
1.6 ms. The branch takes the rings to 0.95 ms. Airways and fixes stay
close to what they were, because their cost is Qt stroking the lines that
are on screen, not the Python loop. Roads and terrain are two rotated
full-panel image blits and are unchanged.
