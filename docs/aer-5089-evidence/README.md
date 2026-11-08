# AER-5089 -- the FPL page after a refused route commit (G61, billmallard/pyEfis#380)

The FPL page at 650 x 1000, about the Flight Plan tab's pane on the Beelink's
PFD screen. These are offscreen QPainter renders of the `flight_plan` widget
(a plain QWidget, so these are the pixels the panel draws), with the bus played
by hand through the test suite's in-memory FIX client. The flight plan
KSBA GVO REYES KSMX is loaded (`FPLLDSEQ` = `FPLSEQ` = 1) and flown on the
GVO leg. A second display then commits the same route with an RF leg RFFIX
that has no turn direction (`FPLSEQ` 2). The engine answers `BADTURN 4` on
`FPLMSG` and leaves `FPLLDSEQ` at 1. Fonts: DejaVu Sans (the sandbox has no
DejaVu Sans Condensed, and neither does the bench).

| Image | What it shows |
|---|---|
| `before_refused.png` | `dev` before the fix (fce470c1): the refused route, RFFIX included, listed as the flight plan, with no sign it was refused |
| `after_refused.png` | the fix: the flown plan (no RFFIX), and the red strip `EDIT REFUSED: BADTURN 4` with **Edit draft** |
| `after_draft.png` | after **Edit draft**: the refused route as a draft (`DRAFT - NOT LOADED`, no active-leg colour), with **Flown plan** to go back |
| `after_*_strip_x2.png` | the strip region (y 840-940) of each, 2x nearest-neighbour |

Each image has a `.json` sidecar (docs/evidence.md) naming the commit that drew it.

## Regenerate

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. \
    python3 docs/aer-5089-evidence/render_refused_commit.py docs/aer-5089-evidence after_
# before: the same with src/pyefis/instruments/flight_plan/__init__.py from fce470c1
python3 -c "
from PyQt6.QtGui import QImage
for n in ('after_refused', 'after_draft'):
    QImage('docs/aer-5089-evidence/%s.png' % n).copy(0, 840, 650, 100).scaled(1300, 200) \
        .save('docs/aer-5089-evidence/%s_strip_x2.png' % n)"
```
