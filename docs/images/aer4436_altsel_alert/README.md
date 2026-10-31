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
