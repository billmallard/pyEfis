# Touch-select + knob-edit visual language (pyEfis #308, AER-3912)

Rendered **on the Pi 5 test unit** (`wpballard@10.110.10.199`, Raspberry Pi OS,
the Pi's own DejaVu fonts and PyQt6 from `~/pyEfis/.venv`) from a throwaway
clone of branch `aer-3912/tk1-touch-knob-focus` at `37ad4cd`, with
`QT_QPA_PLATFORM=offscreen`. These widgets are QPainter-drawn, not GL, so an
offscreen render is the same pixels the panel draws. The Pi's live display
was not touched. There is no SIGUSR1 screenshot on the Pi (AER-2002).

Sizes are the Pi panel's native pixels: 1920x1200 on the live 200 x 110 grid.

| File | What it shows |
|---|---|
| `sheet_1x.png` | **Actual size.** Top: the baro `numeric_display` (12 x 4 cells = 115 x 44 px) at rest with no hint, at rest with the dim hint (`editIconAtRest: true`), and focused by a real synthetic touch through `EncoderController`. Each is shown over black and over a sky colour. Bottom: the HSI (432 x 425 px, the live Pi options) with the marks on its HDG readout, in the live `top_panel` layout and in the `corners` layout, where the HDG box border is itself cyan (the colour-clash check). |
| `baro_zoom4x.png` | The three baro states, nearest-neighbour **4x**, so the 10 px icon's shape is visible. |
| `baro_{rest,hint,focused}_1x.png` | The individual baro frames over black. |

The HSI is not wired to touch here; that is TK2 (#309). Its marks are drawn by
a subclass, through the same `edit_focus.draw_edit_marks` that TK2 will call.

Regenerate:

```sh
QT_QPA_PLATFORM=offscreen PYTHONPATH=src python3 tools/render_edit_focus_evidence.py OUTDIR
```
