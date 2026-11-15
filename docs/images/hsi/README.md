# HSI pictures for the wiki's HSI page

Made 2026-11-07 for [The HSI](../../wiki/The-HSI.md). Two kinds: `bench_*` are
captures from the Beelink bench, the rest are offscreen renders.

## Bench flight captures

`bench_panel_approach.png` and the other `bench_*` pictures except
`bench_no_data.png` come from sim-bench session `20cc77924924`
(`processes/sim_bench.md` in maos-workspace), flown 2026-11-15 06:29-06:51 UTC.
X-Plane flew fix-gateway's `fp8-ksmx-rnav30-missed` profile: the KSMX RNAV (GPS)
RWY 30 via GVO from 2 nm before PAMJI, the missed approach, the 1 nm offsets on
HANNU-WINCH and the WINCH hold. The bench checkout read pyEFIS `dev` 5d77ad82
and fix-gateway `dev` 3d1d168 for the whole flight, with X-Plane position from
the bench's standing RREF block. Both bearing pointers were off, their default,
so the course pointer is the only needle in every picture.

`bench_flight/docs_flight.py` ran on the bench, detached. It changed no config
and restarted nothing. Once the session was flying it saved the route block it
found, published the approach to the flight-plan engine (the FP8 sessions'
`fp8_proc_route.py`, in `../fp8_bench/bench_scripts/`), sent `ACT` at PAMJI,
and sent `RESUME` 5 s after the engine's auto-SUSP at the MAP. It grabbed the
1920 x 1080 screen with `ffmpeg -f x11grab` under the bench lock every 30 s and
3 s after each change of leg, phase, state, TO/FROM or nav source. At the end
it put the saved route block, its active leg, `NAVSRC` and `GPSSRC` back.
`bench_flight/flight3_events.log` is its log, and
`bench_flight/flight3_keys.jsonl` holds the FIX keys it read just after each
grab. Its first four grabs, before CIMSO, timed out waiting for the bench lock,
so there is no frame from before the final approach fix.

**A grab can show the previous grab's state.** Some x11grab frames show the
screen as it was at the previous grab, 5 to 30 s earlier. Each caption on the
page is therefore taken from the readouts in the picture itself, and the frame
it was cut from is listed here:

| Picture | Frame | What it shows (readouts) |
|---|---|---|
| `bench_panel_approach.png` | `063305` | The whole panel, 1.0 nm before ANIBY (inside the FAF), 2,130 ft, scaled to 1280 x 720 |
| `bench_gps_leg_off_course.png` | `064003` | HANNU-WINCH on the 1 nm offset right of course: CRS 296, MAG 316, bar well left |
| `bench_susp_at_map.png` | `063557` | Past RW30 (the MAP), auto-SUSP: FROM, CRS 319 |
| `bench_resume_missed.png` | `063608` | After RESUME: the missed approach, TO, CRS 319 |
| `bench_hold_1_crossing.png` | `064706` | Past WINCH, still on 300: CRS 122, the outbound course |
| `bench_hold_2_entry_turn.png` | `064807` | In the entry turn: MAG 069, CRS 122 |
| `bench_hold_3_outbound.png` | `064838` | Outbound: MAG 147, CRS 122 |
| `bench_hold_4_turn_inbound.png` | `065009` | Turning back inbound: MAG 086, CRS 077 |

The HSI crops are 420 x 410 px at (420, 640) of the panel.

To capture again: queue the profile (`POST /sessions` with
`{"profile": "fp8-ksmx-rnav30-missed"}`), copy `bench_flight/docs_flight.py`,
`fp8_proc_route.py` and `nfx.py` into one directory on the bench, and start it
with the session id, the sim-bench service URL, the end of that night's flying
window in UTC, and the tab the bench is on:

```bash
setsid nohup ~/pyefis-venv/bin/python docs_flight.py <session-id> http://<bench-host>:<port> \
    "2026-11-15 12:00" fpl > follow.out 2>&1 < /dev/null &
```

## Renders

The other pictures are the real pyEFIS `HSI` widget
(pyEFIS `dev` a2d53d75), rendered offscreen at 420 x 420 px on 2026-11-14. It
is connected over netfix to a real fix-gateway (`dev` b96875f) running only
netfix, compute and flightplan. The options are the Beelink bench panel's
(`screens/managed.yaml`), applied through the screen builder's own
`apply_options`. The face is drawn over a dark green fill standing in for the
synthetic vision, because the bench panel sets `bg_opacity: 30`.

- **GPS scenes** (`gps_*`): `hsi_docs.py` publishes KSBA, DEANO, HENER, VTU
  (FAA CIFP coordinates) and flies a kinematic aircraft along the engine's own
  guidance: desired track plus a cross-track correction, 120 kt, turns of up
  to 3 deg/s, `MAGVAR` -11.449. Heading equals track, so there is no wind.
  The fly-by is the 61 degree turn at HENER. The hold scene adds an `HM` hold
  at HENER: right turns, inbound 073, 4 nm legs. The page shows the bench
  flight's leg and hold instead, so `gps_leg_right_of_course.png` and the three
  `gps_hold_*.png` are kept only as the script's output.
- **Bearing pointers.** The setup is one a real panel would fly: one CDI on
  its `NAVSRC`, and at most one bearing pointer, on another source. In the GPS
  scenes pointer 1 is stepped on once (`make_hsi(brg1=True)`, what one tap on
  its BRG tab row does), which puts it on VOR1, with NAV1 tuned to GVO (FAA
  CIFP coordinates), off the route so its needle stays clear of the course
  pointer. In the NAV radio scenes both pointers are off, their default.
- **NAV radio scenes** (`vor1_*`, `loc1_*`): the script writes the radio keys
  an X-Plane or CAN-FIX source would publish (`NAV1CRS`, `NAV1CDI`, `NAV1TF`,
  `NAV1DH`, `NAV1GSI`, `NAV1GSF`, `VOR1BRG`).
- `vor1_crs_selected.png` selects CRS for the knob, as a touch on it does.
- `evidence_guidance_failed.png` is not on a page. It is the evidence for the
  defect where the HSI keeps drawing the bar and course while guidance has
  failed: position stopped, so the engine flags its guidance `fail`.

The fonts are DejaVu Sans; the bench panel asks for B612. The `font_family`
falls back the same way wherever B612 is not installed.

## Regenerate

```bash
# 1. A fix-gateway with only netfix + compute + flightplan enabled
cp -r <fix-gateway>/src/fixgw/config gwcfg
cat > gwcfg/preferences.yaml.custom <<'YAML'
includes:
  QUORUM_CONFIG: connections/quorum.yaml
enabled:
  QUORUM: false
  XPLANE: false
  DEMO: false
  ANNUNCIATE: false
  SYSTEM: false
  NETFIX: true
  COMPUTE: true
  FLIGHTPLAN: true
  STATE_PERSIST: false
YAML
(cd <fix-gateway> && PYTHONPATH=src python3 fixGw.py --config-file "$PWD/../gwcfg/default.yaml") &

# 2. The renders (scenes: gps, hold, vor, edit; default all)
cd docs/images/hsi
RENDER_FONT_DIR=/usr/share/fonts/truetype/dejavu QT_QPA_PLATFORM=offscreen \
  PYTHONPATH=../../../src python3 -u hsi_docs.py . gps hold vor edit
```

The script prints the FIX keys behind every picture as it saves it.

## Bench, no data

`bench_no_data.png` is the Beelink bench (pyEFIS `dev` c445c000), grabbed with
`kill -USR1` under the bench lock on 2026-11-14 at 15:49 UTC, with no
simulator running. It is cropped to the HSI from the 1920 x 1080 panel, box
(420, 640, 840, 1060).
