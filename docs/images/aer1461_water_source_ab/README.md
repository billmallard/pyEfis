# AER-1461 — which layer draws the water past range_nm?

One bench measurement (Beelink, `dev`@`76468bf`), not a fix. Answers: does the
terrain-heightmap void classification in the GL shader (`svs_gl.py` `WATER_THR_M`)
draw open water independent of `range_nm`, as a code reading claimed?

**Answer: no.** The heightmap-void path draws *zero* water, at any distance,
on this deployment's actual data (GLO-30). All visible water in the full
render comes from the `water_db` overlay polygon pack. See the AER-1461 issue
thread / AER-1460 comment for the full writeup.

## Commands

All three frames use `tools/svs_capture.py` (renderer hardcoded to `opengl`)
via `xvfb-run` on the Beelink bench (`pyefis@10.110.10.241`), against the
deployed data:

```
TILES=/data/makerplane-data/terrain/tiles
WATER=/data/makerplane-data/water/current/water.sqlite
VP=/home/pyefis/pyefis-venv/bin/python
CAP=/home/pyefis/src/pyEfis/tools/svs_capture.py
```

**frameA_full.png** — full render, overlay pack loaded, coastal pose, range
pinned at 40 NM, heading chosen (220°, verified against raw GLO-30 tiles) to
clear the Santa Barbara Channel Islands so open ocean runs clean to 100+ NM:

```
xvfb-run -a -s "-screen 0 1280x720x24" "$VP" "$CAP" \
  --lat 34.4275 --lon -119.8546 --alt 6000 --heading 220 --pitch 0 --roll 0 \
  --range 40 --width 1280 --height 720 \
  --tiles "$TILES" --water "$WATER" --water-max-vertices 1000000 \
  --flat --timeout 45 --verbose \
  --out frameA_full.png
```

**frameB_terrainonly.png** — same pose, `--terrain-only` (hides symbology)
and `--water` *omitted* (no overlay pack loaded — `_default_water()` finds
nothing under `<repo>/water/`, so `water_db_path=""` and the water collector
never runs):

```
xvfb-run -a -s "-screen 0 1280x720x24" "$VP" "$CAP" \
  --lat 34.4275 --lon -119.8546 --alt 6000 --heading 220 --pitch 0 --roll 0 \
  --range 40 --width 1280 --height 720 \
  --tiles "$TILES" \
  --terrain-only --flat --timeout 45 --verbose \
  --out frameB_terrainonly.png
```

**frameC_control_terrainonly.png** — close-range control: aircraft placed
~10 NM further out along the same 220° ray (`34.29984, -119.98420`, confirmed
open water via raw tile sampling), 1500 ft, 10 NM range, terrain-only, no
overlay. Isolates whether the heightmap-void path works *at all*, independent
of any far-distance/clipmap-radius question:

```
xvfb-run -a -s "-screen 0 1280x720x24" "$VP" "$CAP" \
  --lat 34.29984 --lon -119.98420 --alt 1500 --heading 220 --pitch 0 --roll 0 \
  --range 10 --width 1280 --height 720 \
  --tiles "$TILES" \
  --terrain-only --flat --timeout 45 --verbose \
  --out frameC_control_terrainonly.png
```

`--flat` is used throughout (disables haze/texture/grid) so a frame can be
classified by exact pixel value (`COLOR_WATER = (20, 80, 150)`) instead of
eyeballed, per the tool's own docstring.

## Heading selection

Santa Barbara's Channel Islands (Santa Cruz, Santa Rosa, San Miguel, Anacapa)
sit 20-40 NM south/southwest of KSBA and would contaminate a naive due-south
or due-west ray. Headings were screened against the actual deployed GLO-30
tiles (`/data/makerplane-data/terrain/tiles`, raw `>i2`, ocean = exactly `0`
on this void-free format — confirmed by sampling known points) before picking
a pose; 220° and 240° both give a clean water ray to 100 NM. See the issue
thread for the probe script.
