# AER-1799 bench evidence

Renders backing the AER-1799 recommendation (AI visible pitch range vs
AC 23.1311-1C Sec 8.5(c), and the SVS FOV coupling it exposed). All
frames are the same pose -- level flight, 1 NM final RWY 7 KSBA,
611 ft MSL, heading 089, range 5 NM -- captured with
`tools/svs_capture.py --offscreen` on the Beelink bench (Intel ADL-N
iGPU) against separate throwaway checkouts, never the bench's live
`~/src/pyEfis` (which stayed on `dev`, untouched, services never
restarted).

**Correction (v2, 2026-09-20):** the "both eval candidates show +-25"
claim below the v1 table was wrong -- QA measured the committed v1
`decouple_800x480.png` directly and found the ladder actually stopped
at +-14, not +-25 (`visiblePitchAngle`, a separate constant, was still
hard-coded to 15 and faded every mark past it regardless of
`pitchDegreesShown`). The v1 row is kept below for the coupling/HFOV
comparison, which QA verified independently and which still holds; do
not read the v1 pitch-ladder claim as true. The v2 rows are the fix.

| File | Panel | Checkout | `pyefis_rev` (sidecar) | horizon_position |
|---|---|---|---|---|
| `baseline_800x480.png` | 800x480 | `dev` | `4838942` | 50 (schema default) |
| `raise_only_800x480.png` | 800x480 | `aer-1799/pitch-range-raise-only-eval` | `7cb49b9` | 50 |
| `decouple_800x480.png` | 800x480 | `aer-1799/pitch-range-svs-fov-eval` (v1) | `7e42491` | 50 |
| `baseline_1024x600.png` | 1024x600 | `dev` | `4838942` | 50 |
| `decouple_1024x600.png` | 1024x600 | `aer-1799/pitch-range-svs-fov-eval` (v1) | `7e42491` | 50 |
| `decouple_v2_hp50_800x480.png` | 800x480 | `aer-1799/pitch-range-svs-fov-eval` (v2, fixed) | `b1628e5` | 50 |
| `decouple_v2_hp68_800x480.png` | 800x480 | `aer-1799/pitch-range-svs-fov-eval` (v2, fixed) | `b1628e5` | **68 (live value, both benches)** |
| `baseline_hp68_800x480.png` | 800x480 | `dev` | `4838942` | **68 (live value, both benches)** |

Command (per file, `$D` = the checkout dir, `$W`/`$H` = panel size). The
v2/hp68 frames additionally set `SVS_CAPTURE_HORIZON_POSITION=68` in the
environment against a local, uncommitted one-line patch to
`tools/svs_capture.py` (`widget.horizon_position = float(os.environ[...])`
right after widget construction) -- evidence-gathering only, never
pushed; the tool has no CLI flag for this and none is proposed here:

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

- **Terrain/runway scale** (the coupling's actual consequence, v1
  measurement -- unaffected by the v2 fix, still holds): measured the
  magenta-mountain silhouette's rightmost visible column (a clean,
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

- **Pitch ladder extent, v2 (the fix)**: `measure_ladder_extent.py`
  scans row-brightness variance in the ladder column band against a
  clean background band (same method QA used to catch v1's bug, just
  automated instead of eyeballed) and reports how many degrees above
  and below current pitch (0) still carry a mark:

  ```
  baseline pitchDegreesShown=30, hp=68          up= 9.0 deg  down=18.9 deg
  decouple-v2 pitchDegreesShown=50, hp=50       up=24.1 deg  down=24.0 deg   <- fix confirmed: was ~14/~14 in v1
  decouple-v2 pitchDegreesShown=50, hp=68       up=16.0 deg  down=24.0 deg   <- live horizon_position still short of +25 up
  ```

  Run: `PYTHONPATH=. python3 measure_ladder_extent.py` from this directory
  (needs `numpy` + `Pillow`).

  **v2 fix confirmed at the schema-default `horizon_position=50`**: the
  ladder now reaches ~24 deg both up and down (target +-25; the ~1 deg
  shortfall is the same edge-of-frame measurement effect QA's v1 method
  saw, not a residual bug -- `visiblePitchAngle` derives from
  `pitchDegreesShown / 2` exactly, so the marks are drawn to the
  specified angle, just partly clipped by anti-aliasing/label width at
  the very edge).

  **At the LIVE `horizon_position=68`** (read directly off both benches'
  active `managed*.yaml`, see the issue comment -- not the `70` this
  repo's `CLAUDE.md` records, which is stale), the fixed candidate only
  reaches **+16 deg up**, still 9 deg short of the AC 23.1311-1C floor.
  This is not a bug in the candidate: `up = (1 - horizon_position/100) *
  pitchDegreesShown`, and at `horizon_position=68` no value of
  `pitchDegreesShown` under the guidance's own 50-deg total ceiling can
  reach 25 (`up >= 25` forces `horizon_position <= 50`, independent of
  `pitchDegreesShown`) -- see the issue comment for the general result.
  The baseline (current shipped code) at the same live `horizon_position`
  does even worse (+9/-19).
