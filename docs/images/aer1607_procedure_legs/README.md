# PA8 (AER-1607): procedure legs on the moving map

The `flight_plan` map layer alone, offscreen, on a plain dark background, 640x640 per
panel, north up, 1:1 pixels. Left panel: `origin/dev` before PA8 (41cda11). Right panel:
this branch. These are layer renders, not the composed bench screen.

| File | View | What it shows |
|---|---|---|
| `kssf_rnav28_missed_before_after.png` | KSSF RNAV (GPS) 28 via XTEND with the missed approach, 10 NM, flying the final into RW28 | Before: straight lines between slot points, a fix symbol on the CA point, and a straight leg to GANLE that reads as a left turn. After: the CA climb-out, the coded right turn back to GANLE, the GANLE racetrack (right turns, inbound 336.9 M, 4 NM). The missed approach is dashed and altitude constraints are in chart notation |
| `kssf_rejected_before_after.png` | The same block, with the engine having rejected the commit (`FPLLDSEQ` 0, `FPLSEQ` 2), still flying its active leg | Before: the refused procedure is drawn in full. After: only the leg the engine is flying, from its own FROM/TO outputs |
| `kabq_rf_arcs_before_after.png` | KABQ RNAV (GPS) Y RWY 21, FOXRR transition, 3 NM | Before: chords. After: the two RF arcs about the centre fix CFDXH, in the coded direction (right) |

Data: the KSSF block is fix-gateway's encoder output from FAA CIFP cycle 2611
(`tests/flightplan/fixtures/fplroute_blocks.json`). The KABQ fixes are the constants
fix-gateway's `tests/plugins/flightplan/test_engine_golden_procedures.py` decodes from
its CIFP excerpt.

## Regenerate

From the repo root, with Qt able to run offscreen:

```bash
D=docs/images/aer1607_procedure_legs
QT_QPA_PLATFORM=offscreen python3 $D/render.py /tmp/pa8/after
git worktree add --detach /tmp/pa8-dev 41cda11
mkdir -p /tmp/pa8-dev/$D && cp $D/render.py /tmp/pa8-dev/$D/
(cd /tmp/pa8-dev && QT_QPA_PLATFORM=offscreen python3 $D/render.py /tmp/pa8/before)
git worktree remove --force /tmp/pa8-dev
QT_QPA_PLATFORM=offscreen python3 - <<'PY'
from PyQt6.QtGui import QImage, QPainter, QColor
from PyQt6.QtWidgets import QApplication
app = QApplication([])
for n in ("kssf_rnav28_missed", "kssf_rejected", "kabq_rf_arcs"):
    a, b = QImage(f"/tmp/pa8/before/{n}.png"), QImage(f"/tmp/pa8/after/{n}.png")
    out = QImage(a.width() * 2 + 8, a.height(), QImage.Format.Format_RGB32)
    out.fill(QColor("#000000"))
    p = QPainter(out); p.drawImage(0, 0, a); p.drawImage(a.width() + 8, 0, b); p.end()
    out.save(f"docs/images/aer1607_procedure_legs/{n}_before_after.png")
PY
```
