# HSI touch-select HDG / CRS (pyEfis #309, AER-3913)

Rendered **on the Pi 5 test unit** (`wpballard@10.110.10.199`, the Pi's own
DejaVu fonts and PyQt6 from `~/pyEfis/.venv`) from a throwaway clone of
branch `aer-3913/tk2-hsi-touch-hdg-crs` at `6e6e084`, with
`QT_QPA_PLATFORM=offscreen`. The HSI is QPainter-drawn, so an offscreen render
gives the panel's own pixels. The Pi's live display was not touched.

Size: 432 x 425 px, the HSI's 45 x 39 cells on the Pi's 1920x1200, 200 x 110
grid, with the live Pi HSI options plus `touch_edit: true`. The at-rest icon
is on (the default).

Each focused state is reached through the widget's own handling: a synthetic
tap on the readout through `EncoderController`, then real `changed` /
`outer_changed` / `button_changed` calls. The script asserts the FIX values
(HEADBUG 132, NAV1CRS 77, COURSE untouched at 45) before it saves.

| File | What it shows |
|---|---|
| `sheet_1x.png` | **Actual size.** Rows: `top_panel`, `corners`, `split`. Columns: at rest on VLOC1 (dim icon on HDG and CRS), HDG focused after two inner clicks and one outer click (120 -> 132), CRS focused after a push that centres the CDI (NAV1CRS 45 -> VOR1BRG 77), at rest on GPS (no icon on CRS). Far right: the `corners` source label before this change (drawn under the HDG box) and after (below it). |
| `focus_zoom3x.png` | Every HDG and CRS readout from the sheet, nearest-neighbour **3x**. |

In the CRS-focused frames the readout shows 077 while the course pointer stays
at 045. That is expected without fix-gateway: the readout shows the key being
edited (NAV1CRS), and the pointer follows `COURSE`, which only moves once
fix-gateway's NAVSRC select copies NAV1CRS into it.

Regenerate:

```sh
QT_QPA_PLATFORM=offscreen PYTHONPATH=src python3 tools/render_hsi_touch_edit_evidence.py OUTDIR
```
