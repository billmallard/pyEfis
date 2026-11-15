# AER-4350: the picker's software-notice screen

`notice_800x480.png`, `notice_1024x600.png` -- the Data Status picker after
`pyefis-data update --progress` refused with `notice_required` (exit 3): the
updater's notice in full, Decline / Accept. Rendered offscreen through the real
`DataStatus` flow (picker -> Install -> refusal), with the updater stubbed at
`DataStatus._run`.

Regenerate:

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src python docs/images/aer-4350/render.py
```

These were rendered in a sandbox with no system fonts, so they pass matplotlib's
bundled DejaVu directory as `FONT_DIR`. That has DejaVu Sans but not the
instrument default DejaVu Sans Condensed, so the text here is a little wider
than on the panel (wraps earlier, never later).
