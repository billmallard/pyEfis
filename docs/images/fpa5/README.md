# FPA5 duplicate chooser (AER-6544)

`flightplan direct to BR` on a navaids pack holding the three real cycle-2611
`BR` NDBs (NASR 2026-10-29: Larew MN, Depoo TX, Burns IA), at the Beelink's
Flight Plan pane size, 649 x 993.

- `1_chooser_pack_before_fpa5.png`: a pack built before the region columns. The
  rows carry no region, as every pack did before FPA5.
- `2_chooser_pack_with_region.png`: a pack built with them. Each row names its
  state.

Both are rendered by the FPA5 code: on `dev` the same action opens nothing at
all. Regenerate with:

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python -m pytest \
        tests/instruments/flight_plan/render_fpa5_evidence.py --no-cov -q
