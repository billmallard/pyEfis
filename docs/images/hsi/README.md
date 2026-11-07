# HSI pictures for the wiki's HSI page

Made 2026-11-07 for [The HSI](../../wiki/The-HSI.md). Two kinds: `bench_*` are
captures from the Beelink bench, the rest are offscreen renders.

## Bench flight captures

`bench_panel_approach.png` and the other `bench_*` pictures except
`bench_no_data.png` come from sim-bench session `8f9eb80b0daa`
(`processes/sim_bench.md` in maos-workspace), flown 2026-11-07 05:11-05:33 UTC.
X-Plane flew fix-gateway's `fp8-ksmx-rnav30-missed` profile: the KSMX RNAV (GPS)
RWY 30 via GVO from 2 nm before PAMJI, the missed approach, the 1 nm offsets on
HANNU-WINCH and the WINCH hold. The bench ran pyEFIS `dev` 4c4f4dc (the same
code as 980497e; the difference is wiki pages) and fix-gateway `dev` 5f1625c,
with X-Plane position from the bench's standing RREF block (AER-4970).

`bench_flight/docs_flight.py` ran on the bench, detached. It changed no config
and restarted nothing. Once the session was flying it published the approach
to the flight-plan engine (the FP8 sessions' `fp8_proc_route.py`, in
`../fp8_bench/bench_scripts/`), sent `ACT` at PAMJI, and sent `RESUME` 5 s
after the engine's auto-SUSP at the MAP. It grabbed the 1920 x 1080 screen
with `ffmpeg -f x11grab` under the bench lock every 30 s and 3 s after each
change of leg, phase, state, TO/FROM or nav source, then put the route block,
`NAVSRC` and `GPSSRC` back as it found them. `bench_flight/events.log` is its
log, and `bench_flight/keys.jsonl` holds the FIX keys it read just after each
grab.

**A grab can show the previous grab's state.** About half the x11grab frames
show the screen as it was at the previous grab, 5 to 30 s earlier, whatever
the interval; the altitude readout against `ALT` shows it. The staleness
tracks the grabs, not the clock, so it comes from the capture, not from the
display. Each caption on the page is therefore taken from the readouts in the
picture itself, and the frame it was cut from is listed here:

| Picture | Frame | What it shows (readouts) |
|---|---|---|
| `bench_panel_approach.png` | `051432` | The whole panel, 1.9 nm before CIMSO (the FAF), 2,210 ft, LNAV, scaled to 1280 x 720 |
| `bench_gps_leg_off_course.png` | `052235` | HANNU-WINCH, 0.86 nm right of course on the 1 nm offset: CRS 296, MAG 317 |
| `bench_susp_at_map.png` | `051829` | Past RW30 (the MAP), auto-SUSP: FROM, CRS 319 |
| `bench_resume_missed.png` | `051840` | After RESUME: the missed approach to HANNU, TO, CRS 319 |
| `bench_hold_1_crossing.png` | `053006` | 1.9 nm past WINCH, still on 300: CRS 122, the outbound course |
| `bench_hold_2_entry_turn.png` | `053107` | In the entry turn: MAG 069, CRS 122 |
| `bench_hold_3_outbound.png` | `053138` | Outbound: MAG 147, CRS 122 |
| `bench_hold_4_turn_inbound.png` | `053239` | Turning back inbound: MAG 087, CRS 080 |

The HSI crops are 420 x 410 px at (420, 640) of the panel.

**The diamond right of the rose** in these captures is the glidepath pointer.
On this bench `GSV` for GPS comes from X-Plane's own GPS glidepath flag
whatever `GPSSRC` is, so it shows beside the internal plan's lateral guidance.
That is a defect, not intended behaviour, and is filed on fix-gateway.

To capture again: queue the profile (`POST /sessions` with
`{"profile": "fp8-ksmx-rnav30-missed"}`), copy `bench_flight/docs_flight.py`,
`fp8_proc_route.py` and `nfx.py` into one directory on the bench, set its
`DEADLINE`, and start it with the session id:

```bash
setsid nohup ~/pyefis-venv/bin/python docs_flight.py <session-id> > follow.out 2>&1 < /dev/null &
```

## Renders

The other pictures are the real pyEFIS `HSI` widget
(pyEFIS `dev` 980497e), rendered offscreen at 420 x 420 px. It is connected
over netfix to a real fix-gateway (`dev` 5f1625c) running only netfix,
compute and flightplan. The options are the Beelink bench panel's
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

`bench_no_data.png` is the Beelink bench (pyEFIS `dev` 980497e), grabbed with
`kill -USR1` under the bench lock on 2026-11-07 at 02:05 UTC, with no
simulator running. It is cropped to the HSI from the 1920 x 1080 panel.
