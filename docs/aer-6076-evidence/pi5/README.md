# AER-6076: turn-rate trend rendered on the Pi 5

The three pictures from `tools/render_hsi_turn_trend_evidence.py`, rendered on the
Pi 5 bench (10.110.10.199) on 2026-11-21 at 20:32 UTC. They used the Pi's own Qt
(`~/pyEfis/.venv`), its fonts, and the live panel's HSI font, B612. The source was
a fresh clone of `dev` at `d9f7066`, in `~/bench-scratch/aer6076`, under the
bench lock. pyEfis kept running throughout (`NRestarts=0`).

- `turn_rate_trend.png`: standard rate left on the rose, right on the rose
  (`corners`), right in the arc view. 1:1.
- `top_zoom3x.png`: the band above the rose at standard rate each way, per
  presentation, nearest-neighbour 3x.
- `sheet_1x.png`: `ROT` -3, -1.5, 0, +3, +5 deg/s and failed, per presentation.

These are raster renders through Qt's offscreen platform, not a scanout of the
panel. The HSI is a raster widget (not GL), so this is the paint path the panel
uses. The Pi has no screenshot path under eglfs (AER-2002) and no `sudo` for a
DRM scanout grab. On the live bus at capture time, `ROT` was 0.0 and flagged
old, because nothing on the hardware bench publishes it. So the live HSI was
correctly drawing no arc.

The only change from the committed tool was the font, made in the scratch copy:

```sh
sed -i 's/font_family="DejaVu Sans Condensed")/font_family="B612")/' tools/render_hsi_turn_trend_evidence.py
QT_QPA_PLATFORM=offscreen PYTHONPATH=src ~/pyEfis/.venv/bin/python tools/render_hsi_turn_trend_evidence.py OUT
```
