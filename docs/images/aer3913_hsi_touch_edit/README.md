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

## Bench (Beelink, X11, live pyEfis + fix-gateway)

`bench_beelink_1x.png` and `bench_beelink_panel_4x.png` are `x11grab` frames
of the live PFD on the Beelink bench (`10.110.10.241`, 1920x1080). The branch
was staged with `bench-deploy.sh --ref aer-3913/tk2-hsi-touch-hdg-crs` at
`24a9ad0`, and `touch_edit: true` was added to the live HSI in
`screens/managed.yaml` for the test, then reverted. Taps were real X pointer
clicks (`xdotool`) on the readouts. The knob was driven by writing the
Knobster's own FIX keys (`ENC3` inner, `ENC4` outer, `BTN3` push) with
`fixgwc`, the same keys the attached Knobster publishes. No X-Plane runs on this
bench, so `HEADBUG` / `NAV1CRS` have no sim writer. Every value below was
read back **from fix-gateway**, not from pyEfis:

| Step | fix-gateway after |
|---|---|
| touch HDG, inner +1, outer +1 | `HEADBUG` 0 -> 11 |
| push | `HEADBUG` 20 (= `HEAD` 20) |
| touch CRS on VLOC1, inner +1, outer +1 | `NAV1CRS` 11, `COURSE` 11 (via the compute select), `NAV2CRS` untouched |
| `VOR1BRG` 77, push | `NAV1CRS` 77, `COURSE` 77, still focused (next click: 78) |
| `NAVSRC` 2 (GPS), touch CRS, turn | nothing written (`NAV1CRS` 78, `NAV2CRS` 0) |
| touch HDG, turn, wait 12 s, turn again | 21, then still 21 (timeout released the knob) |
