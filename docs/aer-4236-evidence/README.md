# AER-4236 evidence: the HSI at CDIV = 0 (fix-gateway#20)

Offscreen renders of the real HSI widget, made on the Beelink bench
(2026-10-30) for its fonts. They were rendered in a scratch directory, so the
live display and the bench checkout were not touched. The flight state is #20's
bench case: ILS 1 tuned on a 090 course, heading 060, localizer not received.
X-Plane then reports a centred deflection (`CDI = 0.0`) and no glideslope
(`GSV = 0`).

| File | Left to right (360 px panels, 1:1) |
|---|---|
| `hsi-rose-before-after.png` | `dev` (before) / this branch at `CDIV = 0` / this branch with no `CDIV` key / this branch at `CDIV = 1` |
| `hsi-arc-before-after.png` | the same four scenes, `orientation: arc` |

What the panels show:
- **Before:** the centred bar looks like on-course guidance.
- **`CDIV = 0`:** the bar is gone and the red NAV flag shows; the course pointer stays.
- **No `CDIV` key** (an older fix-gateway) and **`CDIV = 1`:** these are byte-identical to `dev`, in both layouts. That is checked with `PIL.ImageChops.difference(...).getbbox() is None`, not by eye.

## How to regenerate

From a pyEfis checkout, once per scene:

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python \
        docs/aer-4236-evidence/render_cdiv.py <absent|0|1> <heading_up|arc> out.png

`render_cdiv.py` seeds the flight state above through `tools/render_instrument.py`.
For the "absent" scene it makes `CDIV` lookups raise, because the render tool
would otherwise auto-define the key at 0. For the "before" panel, run the same
script with `0` from a `dev` checkout, which ignores `CDIV`. Each strip is the
four PNGs pasted side by side with 8 px grey gaps.
