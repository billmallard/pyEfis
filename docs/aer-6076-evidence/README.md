# AER-6076 (ATT1b): turn-rate trend arc on the HSI

A magenta arc from the lubber line to the heading the aircraft will reach in
6 s at the present rate of turn (`ROT`), with white marks at half (9 deg) and
standard (18 deg) rate each side, after the Garmin G1000/G3X turn rate
indicator. Above 4 deg/s it stops at 24 deg with an arrowhead. Arc and marks
hide when `ROT` is old, bad or failed.

- `sheet_1x.png`: rows `top_panel`, `corners`, `arc`; columns `ROT` -3, -1.5,
  0, +3, +5 deg/s and `ROT` failed. 1:1.
- `top_zoom3x.png`: the band above the rose at standard rate each way, per
  presentation, nearest-neighbour 3x.

Both are sandbox renders (Qt offscreen platform, DejaVu Sans in place of
DejaVu Sans Condensed) at the Pi 5 panel's HSI size, 432 x 425, with the bench
panel's HSI options. The script asserts, per cell, that the trend is shown or
hidden and how long it is, so a render that does not show the behaviour fails
instead of saving.

```sh
QT_QPA_PLATFORM=offscreen PYTHONPATH=src python3 tools/render_hsi_turn_trend_evidence.py OUTDIR
```
