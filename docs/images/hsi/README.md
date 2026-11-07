# HSI pictures for the wiki's HSI page

Made 2026-11-07 for [The HSI](../../wiki/The-HSI.md).

## Renders

Every picture except `bench_no_data.png` is the real pyEFIS `HSI` widget
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
  at HENER: right turns, inbound 073, 4 nm legs.
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

## Bench capture

`bench_no_data.png` is the Beelink bench (pyEFIS `dev` 980497e), grabbed with
`kill -USR1` under the bench lock on 2026-11-07 at 02:05 UTC, with no
simulator running. It is cropped to the HSI from the 1920 x 1080 panel.
