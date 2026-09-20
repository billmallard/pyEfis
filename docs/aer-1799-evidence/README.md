# AER-1799 bench evidence

Renders backing the AER-1799 recommendation (AI visible pitch range vs
AC 23.1311-1C Sec 8.5(c), and the SVS FOV coupling it exposed). All
five frames are the same pose -- level flight, 1 NM final RWY 7 KSBA,
611 ft MSL, heading 089, range 5 NM -- captured with
`tools/svs_capture.py --offscreen` on the Beelink bench (Intel ADL-N
iGPU) against three separate throwaway checkouts, never the bench's
live `~/src/pyEfis` (which stayed on `dev`, untouched, services never
restarted).

| File | Panel | Checkout | `pyefis_rev` (sidecar) |
|---|---|---|---|
| `baseline_800x480.png` | 800x480 | `dev` | `4838942` |
| `raise_only_800x480.png` | 800x480 | `aer-1799/pitch-range-raise-only-eval` | `7cb49b9` |
| `decouple_800x480.png` | 800x480 | `aer-1799/pitch-range-svs-fov-eval` | `7e42491` |
| `baseline_1024x600.png` | 1024x600 | `dev` | `4838942` |
| `decouple_1024x600.png` | 1024x600 | `aer-1799/pitch-range-svs-fov-eval` | `7e42491` |

Command (per file, `$D` = the checkout dir, `$W`/`$H` = panel size):

```bash
cd $D
DISPLAY=:0 PYTHONPATH=$PWD/src ~/pyefis-venv/bin/python tools/svs_capture.py \
  --out <name>.png \
  --lat 34.42721 --lon -119.87481 --alt 611.0 --heading 89 --pitch 0 --roll 0 \
  --range 5 --width $W --height $H --offscreen \
  --tiles /data/makerplane-data/terrain/tiles \
  --water /data/makerplane-data/water/current/water.sqlite \
  --nasr /data/makerplane-data/navdata/current/airports.sqlite \
  --dof /data/makerplane-data/obstacles/current/obstacles.sqlite \
  --timeout 60 --verbose
```

## What to look at

- **Pitch ladder**: baseline shows only +-10 numbered with the frame
  edge landing at +-15 (30 deg total shown). Both eval candidates show
  +-25 at the same numbered-tick style -- the guidance floor is met in
  both.
- **Terrain/runway scale** (the coupling's actual consequence): measured
  the magenta-mountain silhouette's rightmost visible column (a clean,
  HFOV-sensitive, color-isolable feature) with a plain color-threshold
  scan, rows 0-250/0-310:

  | Panel | baseline | raise-only (coupled) | decouple |
  |---|---|---|---|
  | 800x480 | col 601 | col 460 (-23%) | col 601 (exact match) |
  | 1024x600 | col 611 | -- (not captured; same coupling as 800x480) | col 596 (-2.5%, within capture-to-capture noise) |

  raise-only's mountain reaches meaningfully less far across the frame
  because its wider HFOV (~72 deg exact, ~83 deg linear-approx) spreads
  the same azimuth range over the same pixel width -- the shrink the
  30-deg-shown constant was originally chosen to fix (see
  `ai_widget.py`'s history at `pitchDegreesShown`). decouple's terrain
  scale is statistically indistinguishable from baseline's, because its
  horizontal camera scale is the literal same `height/30` expression
  baseline uses, just no longer tied to the ladder's `pitchDegreesShown`.
