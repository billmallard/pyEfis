# AER-5264 -- the refusal strip in plain words (G61a)

The FPL page at 650 x 1000, about the Flight Plan tab's pane on the Beelink's
PFD screen, after the engine refuses a route commit. Same scene as
`docs/aer-5089-evidence`: KSBA GVO REYES KSMX is loaded and flown on the GVO
leg, and a second display commits the route with an RF leg at RFFIX. The engine
is played by hand through the test suite's in-memory FIX client, writing each
`FPLMSG` below in the exact shape fix-gateway's flightplan engine uses. Offscreen
QPainter renders of the `flight_plan` widget (a plain QWidget, so these are the
pixels the panel draws), drawn on the Beelink for its fonts (DejaVu Sans).

| Image | `FPLMSG` | Strip reads |
|---|---|---|
| `badturn.png` | `BADTURN RF RFFIX` | `EDIT REFUSED: ARC AT RFFIX: NO TURN DIRECTION` |
| `badturn_draft.png` | the same, after **Edit draft** | `DRAFT - NOT LOADED: ARC AT RFFIX: NO TURN DIRECTION` |
| `unsupp.png` | `UNSUPP FC RFFIX` | `EDIT REFUSED: CAN'T FLY FC LEG AT RFFIX` |
| `segent.png` | `SEGENT S4 RFFIX` | `EDIT REFUSED: ROUTE TABLE ERROR AT RFFIX (ENTRY FIX)` (segment 4 named from the refused plan) |
| `unknown.png` | `NEWCODE RF RFFIX` (a code the display has no words for) | `EDIT REFUSED: NEWCODE RF RFFIX`, as it came |
| `strips_x2.png` | all of the above | the strip region (y 840-940) of each, 2x nearest-neighbour, labelled |

Before this change the strip showed the code as it came, as `unknown.png` still
does (`docs/aer-5089-evidence/after_refused.png`). Each image has a `.json`
sidecar (docs/evidence.md) naming the commit that drew it.

## Regenerate

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:.:tools \
    python3 docs/aer-5264-evidence/render_refusal_reasons.py docs/aer-5264-evidence
```
