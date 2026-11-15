# ALTSEL deviation alert on the altimeter tape (EFIS-ALTSEL-006, AER-4436)

The tape at the Pi panel's live size (115 x 655 px), over the PFD sky colour.
ALTSEL is 4500 in every frame. The `ALTSEL` annunciate flag is set by hand
here, as fix-gateway's annunciate plugin sets it on the bus (fix-gateway #90).

| File | What it shows |
|---|---|
| `sheet_1x.png` | **Actual size**, left to right: level at 4500 (flag clear, cyan), ALT 4780 with the flag set and the default amber box and bug, the same with the bug amber and the box left cyan, the same in red, back to ALT 4560 with the flag cleared (cyan). |
| `alert_zoom2x.png` | The first four frames, top 560 px, **2x nearest-neighbour**. |
| `<state>_1x.png` | Each frame on its own. |

Only `amber` (box and bug) is what the code ships. `bugonly` and `red` are the
alternatives for the call on the glass; the tool produces them by overriding
the box's alert colour, not through a config option.

Produced on the Beelink for its real fonts (it has no B612; the glass falls
back to DejaVu Sans as these do). The bench venv has no Pillow, so the sheet
and zoom were composed afterwards:

    # on the bench, from a scratch copy of src tools tests/mock_db tests/__init__.py
    QT_QPA_PLATFORM=offscreen PYTHONPATH=src ~/pyefis-venv/bin/python tools/render_altsel_alert_evidence.py out
    # back here, with the frames copied into this directory
    python3 tools/render_altsel_alert_evidence.py --compose docs/images/aer4436_altsel_alert

## On the Pi 5, against the live gateway

`live_sheet_1x.png`, **actual size**, left to right: climbing through 4100,
captured at 4500, deviated to 4750, returned to 4560. ALTSEL is 4500 in every
frame. `live_<stop>_1x.png` are the frames on their own. They were rendered
offscreen on the Pi by a tape connected to its fix-gateway (`dev@2b18a9e`,
which includes #90). The tape is QPainter-drawn, not GL, so the pixels are the
ones the panel draws. The script flew ALT over netfix at 5 Hz. The gateway's
annunciate plugin alone set and cleared the flag.

    # on the Pi, from ~/bench-scratch/aer-4436 (a copy of src tools tests/mock_db tests/__init__.py)
    flock -w 900 /tmp/pyefis-bench.lock sh -c "QT_QPA_PLATFORM=offscreen PYTHONPATH=src \
        ~/pyEfis/.venv/bin/python -u tools/render_altsel_alert_evidence.py --live 127.0.0.1:3490 live"

Output, 2026-10-31T21:41Z, pyEfis staged at `3939d22` (the tool's final
`fix.stop()` removal was copied in by hand for this run):

    gateway before: ALTSEL=3000  ALT=('4560.0', '01000')
    climbing  ALT= 4100.0  gateway ALTSEL flags=00000  tape flag=0  bug=#00ffff  box=#00ffff  want #00ffff  ok
    captured  ALT= 4500.0  gateway ALTSEL flags=00000  tape flag=0  bug=#00ffff  box=#00ffff  want #00ffff  ok
    deviated  ALT= 4750.0  gateway ALTSEL flags=10000  tape flag=1  bug=#ffb000  box=#ffb000  want #ffb000  ok
    returned  ALT= 4560.0  gateway ALTSEL flags=00000  tape flag=0  bug=#00ffff  box=#00ffff  want #00ffff  ok
    restored ALTSEL: 3000
    LIVE CHECK PASS

`climbing` is 400 ft off the target with no alert. That is the gateway's arm-on-capture,
not anything in pyEfis. The flag's first character is annunciate.
