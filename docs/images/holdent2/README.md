# HOLDENT2 (AER-6016): the hold entry on the moving map

The `flight_plan` map layer alone, offscreen, on a plain dark background, 640x640 per
panel, north up, 6 NM range, 1:1 pixels, centred 1.5 NM northwest of WINCH. Left panel:
`origin/dev` before HOLDENT2 (4146d4ca). Right panel: this branch. These are layer
renders, not the composed bench screen. They were rendered on the Beelink bench
(offscreen, in a scratch directory) for its fonts.

The procedure is the KSMX RNAV (GPS) RWY 30 missed approach: CA, DF HANNU, TF WINCH,
HM WINCH (left turns, inbound 121.4 M, 4 NM). This is fix-gateway's encoder output from FAA
CIFP (`tests/flightplan/fixtures/fplroute_blocks.json`, profile
`fp8-ksmx-rnav30-missed`). The engine outputs on the bus come from fix-gateway's own
flight-plan engine (dev 82fb091, HOLDENT1). The engine is loaded with the same block and
flown to each pose, and what it publishes is written to the FIX keys the map reads.

| File | Pose | Engine publishes |
|---|---|---|
| `1_planned_parallel_predicted_before_after.png` | On the missed approach, HANNU to WINCH, 6 NM before WINCH | `FPLHOLDSLOT` 11, `FPLHOLDENT` PARALLEL, `FPLHOLDCOMMIT` false |
| `2_planned_parallel_committed_before_after.png` | The same flight, 0.05 NM past WINCH | 11, PARALLEL, true (active leg 11) |
| `3_dto_south_teardrop_predicted_before_after.png` | Direct-to WINCH from 10 NM south, 4 NM flown (arrival track 000 true) | 11, TEARDROP, false |
| `4_dto_west_direct_predicted_before_after.png` | Direct-to WINCH from 10 NM west, 4 NM flown (arrival track about 090 true) | 11, DIRECT, false |

The before panels draw the racetrack alone in every case. The after panels add
the entry path and its name above WINCH. The entry is dashed while it is a prediction
and solid once committed, and the DIRECT case draws the name only. The whole missed
approach segment is dashed (PA8), racetrack included. A predicted entry in a missed
approach is therefore dashed like the racetrack around it.

## Regenerate

From the repo root, with a fix-gateway checkout that has HOLDENT1 (only
`src/fixgw/geo.py` and `src/fixgw/plugins/flightplan/engine.py` are read):

```bash
D=docs/images/holdent2
export QT_QPA_PLATFORM=offscreen FIX_GATEWAY_SRC=/path/to/fix-gateway
python3 $D/render.py /tmp/holdent2/after
git worktree add --detach /tmp/holdent2-dev 4146d4ca
mkdir -p /tmp/holdent2-dev/$D && cp $D/render.py /tmp/holdent2-dev/$D/
(cd /tmp/holdent2-dev && python3 $D/render.py /tmp/holdent2/before)
git worktree remove --force /tmp/holdent2-dev
python3 - <<'PY'
from PyQt6.QtGui import QImage, QPainter, QColor
from PyQt6.QtWidgets import QApplication
app = QApplication([])
for n in ["1_planned_parallel_predicted", "2_planned_parallel_committed",
          "3_dto_south_teardrop_predicted", "4_dto_west_direct_predicted"]:
    b, a = QImage(f"/tmp/holdent2/before/{n}.png"), QImage(f"/tmp/holdent2/after/{n}.png")
    out = QImage(1290, 640, QImage.Format.Format_RGB32)
    out.fill(QColor("#000000"))
    p = QPainter(out)
    p.drawImage(0, 0, b)
    p.drawImage(650, 0, a)
    p.end()
    out.save(f"docs/images/holdent2/{n}_before_after.png")
PY
```
