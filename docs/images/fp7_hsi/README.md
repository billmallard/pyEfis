# FP7 HSI chain evidence (billmallard/pyEfis#189)

The real pyEfis `HSI` and `nav_status` widgets, rendered offscreen while
connected to a **real fix-gateway** (`dev` @ `aebde02`) running the
`flightplan` engine, the `compute` selects (`GPSSRC`, `NAVSRC`) and `netfix`.
The aircraft position is synthetic: written over netfix at known cross-track
offsets from the active leg of KSBA > GVO > RZS > KSMX. Nothing in the chain
between the route block and the HSI's `COURSE`/`CDI`/`TOFROM` is mocked.

`hsi_contact_sheet.png`, left to right, top to bottom: on track, 0.5 nm right
and 0.5 nm left of KSBA-GVO; 1 nm before KSMX, 1 nm past KSMX, and 1 nm past
KSMX 0.5 nm right of the extended RZS-KSMX track.
`hsi_chain_gpssrc0_table.md` is the full key dump the same driver produced.

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

# 2. The key dump (publishes the route, MAGVAR 0, GS 120, GPSSRC 0, NAVSRC 2)
cd docs/images/fp7_hsi
python3 hsi_chain.py . > hsi_chain_gpssrc0_table.md

# 3. The renders (RENDER_FONT_DIR only needed on a host without system fonts)
QT_QPA_PLATFORM=offscreen PYTHONPATH=../../../src python3 render_live.py .
```

`MAGVAR` is 0 so `COURSE` is the true desired track; the engine adds `MAGVAR`
exactly as `TRACK -> TRACKM` does. Waypoint coordinates are in
`hsi_chain_points.py` (GVO/RZS approximate, adequate for a geometric check).
