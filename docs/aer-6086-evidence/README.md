# OBS3 bench strips (AER-6086): the TONIE example on the Beelink

The OBS1 brief's example (`makerplane/briefs/gps_obs_mode.md`): "Cleared to
TONIE, intercept the 270 course inbound." The plan is FLOUT, TONIE, OSH, with
TONIE active on the 310 course from FLOUT. The geometry is the synthetic one
from fix-gateway `tests/sim/test_obs_tonie.py`: TONIE at 34.70 N, 120.20 W,
MAGVAR -12, FLOUT 40 NM back on the 310 course, OSH 25 NM on 040 true.

Run on the Beelink (10.110.10.241), 2026-11-20 15:55-15:59 UTC:

- fix-gateway `dev` at `e2f7bf2`, the OBS2 merge (fix-gateway#213).
- pyEfis `aer-6086/obs3-gps-obs` at `981a567`.
- A **private** gateway on netfix port 3492 and pyEfis on Xvfb `:7`
  (1920x1080). Both used copies of the bench's live configs, run from
  `~/bench-scratch/aer6086`. The live `pyefis`/`fixgw` units and the show-unit
  soak were not touched, and all of them were still `active` afterwards.
- The copies differ from the live configs in only these ways:
  - netfix port 3492, and pyEfis `FixPort` 3492.
  - XPLANE and KNOBSTER off.
  - SVS off, to save CPU on Xvfb.
  - `database/flightplan.yaml` replaced by the merged repo's copy (see the
    note below).
- Pilot inputs went through the real pyEfis paths:
  - FPL page MENU -> OBS / OBS Off, by mouse clicks (`xdotool`).
  - A touch on the CRS readout.
  - The knob, as `ENC3` writes on the bus, which is what the Knobster plugin
    writes.
- The aircraft is `fixgw.sim.aircraft`, steering on the engine's FPLCRS and
  FPLXTK like a coupled GPSS. It flies at 8x time, writing LAT/LONG/TRACK/GS
  through netfix (`bench/feeder.py`).

| Frame | What it shows |
|---|---|
| `01_leg_310_read_only.png` | LEG to TONIE on 310. CRS 310 has no edit mark: it is read-only on GPS outside OBS. |
| `02_obs_entered_seeded_310.png` | MENU -> OBS sent `OBS 310`, seeded from FPLCRS. The badge reads OBS, the needle has not moved, and CRS now carries the edit mark. |
| `03_crs_turned_to_270.png` | CRS touched, then 40 knob detents left at 50 detents/s. The readout reads 270. The engine took 4 commands (seq 1003-1006), the last one `OBS 270`. The needle is pegged right, with the aircraft 19 NM south of the 270 line. |
| `04_map_obs_line_50nm.png` | Map at 50 NM: the magenta 270 line through TONIE (ringed). The plan's legs, FLOUT-TONIE and TONIE-OSH, are white. |
| `05_on_the_270_course.png` | Intercepted: XTK 0.2 NM, TO, 3.9 NM before TONIE. |
| `06_from_past_tonie.png` | 1.8 NM past TONIE: the HSI flag reads FROM, the needle is centred on 270, and TONIE is still the active waypoint. The map line runs through it. |
| `07_menu_obs_off.png` | The menu item now reads "OBS Off". |
| `08_obs_off_sequenced_osh.png` | OBS Off past the fix: the engine sequenced (`SEQ TONIE -> OSH`). The OBS line is gone, the leg to OSH is magenta, and CRS reads 028. |
| `09_map_obs_line_2000nm.png` | The same line at the 2000 NM range. The line is 1.5 map ranges each side of TONIE, so here it is a continent-wide great circle. This is a look question for Bill. |

`bench/frames.log` holds each frame's time and the bus state sampled with it.
`bench/feed.csv` is the full 5 Hz bus log of the run.

## Deploy note found on the way: an old database clamps OBS to SUSP

The first attempt used the bench's database copy unchanged. Its
`database/flightplan.yaml` predates OBS2, and declares `FPLSTATE` with
`max: 3`. The engine published 4, the database clamped it silently to 3, and
the glass read **SUSP** while the engine was in OBS. The live bench config,
the show unit's config and the `.dist` all still carry `max: 3`. Any
installation upgraded to OBS2 needs the new `flightplan.yaml`, or the display
will report SUSP for OBS. The display is right to read FPLSTATE alone; the
value on the bus is wrong.

## Regenerate

On the Beelink, from this folder's `bench/` scripts:

```bash
bash setup.sh                 # clones at the two SHAs, copies the live configs
bash cfg.sh                   # port 3492, X-Plane/Knobster off, SVS off, the TONIE route state
cp fgw/src/fixgw/config/database/flightplan.yaml fgwcfg/database/flightplan.yaml
mkdir -p run && touch run/hold && ./start.sh
setsid -f ~/pyefis-venv/bin/python feeder.py 8 > run/feeder.log 2>&1
~/pyefis-venv/bin/python rw.py GPSSRC=0 NAVSRC=2 HEADBUG=310   # a fresh gateway has no persisted selector
./g.sh s1 mousemove 1327 10 click 1      # Flight Plan tab
./g.sh s2 mousemove 1843 1008 click 1    # MENU
./g.sh s3 mousemove 1584 390 click 1     # OBS
./g.sh s4 mousemove 691 678 click 1      # touch CRS
echo -40 > run/enc                       # 40 detents left
rm run/hold; bash waitgrab.sh            # fly; grabs on course and FROM past TONIE
./stop.sh
```
