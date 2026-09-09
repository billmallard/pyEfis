# SVS water bench captures — AER-893 (KEYW #43 + Outer Banks #77)

Real renders from the Beelink bench (`10.110.10.241`), captured against the
**live installed** `water-na` pack. Bench was confirmed on cycle **2026q2r6**
via `bench-deploy.sh --check` immediately before capture (also cross-checked
against `/home/pyefis/makerplane-data/manifest.json`: the installed
`water/current/water.sqlite` byte count matches the `2026q2r6` manifest entry
exactly, not the older `2026q2r5`).

The bench's pyEfis checkout was staged on `aer-805/flightplan-fpl-entry-keypad`
for an unrelated review at capture time. These captures do not touch that
checkout, the running `pyefis.service`, or the X session's visible window —
`tools/svs_capture.py` runs in a second on-screen Qt window against the mock
FIX db (same tool the golden-image tests use), reads the live data packs
directly, and exits. Nothing on the glass changed.

## Commands (run on the bench, `~/src/pyEfis`, `pyefis-venv`)

KEYW / Lower Keys (test case #43):

```bash
DISPLAY=:0 QT_QPA_PLATFORM=xcb /home/pyefis/pyefis-venv/bin/python tools/svs_capture.py \
  --lat 24.5561 --lon -81.6500 --alt 2000 --heading 270 --range 20 \
  --width 1920 --height 1080 \
  --tiles /data/makerplane-data/terrain/tiles \
  --water /data/makerplane-data/water/current/water.sqlite \
  --nasr /data/makerplane-data/navdata/current/airports.sqlite \
  --dof /data/makerplane-data/obstacles/current/obstacles.sqlite \
  --highways /data/makerplane-data/highways/current/highways.sqlite \
  --water-max-vertices 1024 \
  --out keyw_43.png
```

Pose: 6 NM east of KEYW, heading 270 (dead ahead, 0 deg off the nose) —
well inside the ±70 deg forward fan. 2,000 ft, 20 NM range so the whole
island and its shoreline are in frame.

Outer Banks / Topsail-Onslow barrier strip (test case #77) — pose is the
**exact minimal repro Auspex posted on the issue** (2026-07-19 comment):

```bash
DISPLAY=:0 QT_QPA_PLATFORM=xcb /home/pyefis/pyefis-venv/bin/python tools/svs_capture.py \
  --lat 34.8844 --lon -77.4747 --alt 10600 --heading 180 --range 30 \
  --width 1920 --height 1080 \
  --tiles /data/makerplane-data/terrain/tiles \
  --water /data/makerplane-data/water/current/water.sqlite \
  --nasr /data/makerplane-data/navdata/current/airports.sqlite \
  --dof /data/makerplane-data/obstacles/current/obstacles.sqlite \
  --highways /data/makerplane-data/highways/current/highways.sqlite \
  --water-max-vertices 1024 \
  --out outerbanks_77.png
# and the diagnostic mirror of the original repro (flat colours, terrain only,
# no symbology overlaying the water/land boundary):
DISPLAY=:0 QT_QPA_PLATFORM=xcb /home/pyefis/pyefis-venv/bin/python tools/svs_capture.py \
  --lat 34.8844 --lon -77.4747 --alt 10600 --heading 180 --range 30 \
  --flat --terrain-only --width 1920 --height 1080 \
  --tiles /data/makerplane-data/terrain/tiles \
  --water /data/makerplane-data/water/current/water.sqlite \
  --water-max-vertices 1024 \
  --out outerbanks_77_flat_terrain_only.png
```

Pose: heading 180 (due south), 0 deg off the nose to the target geography —
inside the ±70 deg fan, and it's the same pose the original defect was
verified against, so a same-pose comparison is apples to apples.

`outerbanks_77_horizon_zoom8x.png` is an 8x nearest-neighbour vertical
upscale of rows 595-631 of the flat/terrain-only frame (the far-horizon
strip, ~36 px tall in the 1080 px original) — the shoreline detail this
issue turns on is only a few pixels tall at 30 NM, so the raw frame
under-argues it.

## What I see (not a certification — Bill's call on the touchscreen)

**KEYW (#43):** the island (and its neighbors down the Lower Keys chain)
render as green land with the EYW field flag on it, ocean blue around and
past it. I don't see the island swallowed by ocean fill.

**Outer Banks (#77):** in the flat/terrain-only frame, reading near-to-far
(bottom to top): mainland (green, with inland ponds) -> a wide water band
(the sound) -> a thin but *unbroken* green strip the full width of the frame
at the very horizon, then sky. That thin strip is the barrier-island
geography the original repro found painted as water
(`RGB(20, 80, 150)`, ring 74226 inside outer ring 74188). In this capture,
against the current `2026q2r6` pack, that strip reads as continuous land,
not water, across the full frame width -- I did not find a gap where the
old defect's water color breaks through.

That reads to me like the barrier islands are *not* currently vanishing
under the ocean fill at this pose. It does not rule out the defect at a
different position, range, or a different set of rings along the coast --
this is one pose, not a sweep -- and it is not a substitute for looking at
it on the glass.
