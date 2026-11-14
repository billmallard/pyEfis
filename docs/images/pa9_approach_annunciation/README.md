# PA9 approach type, cycle and expired annunciation (AER-1608)

Rendered on the Beelink bench (real fonts, the installed procedures pack,
AIRAC 2611) from commit `e88b845255e5568f586ee7b25eb05f0a12e3c3c2`, in a scratch copy, so the live display was not touched:

    QT_QPA_PLATFORM=offscreen ~/pyefis-venv/bin/python tools/render_pa9_annunciation.py out \
        --procedures /data/makerplane-data/procedures/current/procedures.sqlite \
        --approach I07 --transition GOLET

The only change between "current" and "expired" is the UTC date handed to the AIRAC
check: 2026-10-30 (the day after 2611 took effect) and 2026-11-26 (the day it expires).
The expired approach is loaded by the same PROC page calls as the current one.

- `1_fpl_current.png`: FPL page after Load, the header reads `ILS  AIRAC 2611` in grey.
- `2_fpl_expired.png`: the same plan on 2026-11-26, `ILS  AIRAC 2611 EXPIRED` in amber.
- `3_preview_expired.png`: the PROC page before Load on 2026-11-26, cycle in amber, LOAD available.
- `4_chip.png`: nav_status at 960 x 64, top to bottom: current, expired, expired with FPLTURN = R.
- `sheet.png`: all of the above.
