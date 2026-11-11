# AER-5390: an unbound fuel bar

`bound_unbound_failed.png`, left to right, 2x nearest-neighbour:

- **L MAIN**: bound to a live `FUELQ1`, 18.0 gal.
- **L TIP**: `unbound: true` (its tank was removed from the aircraft profile).
- **R MAIN**: bound to `FUELQ2` with its sensor failed.

The unbound bar is the failed-sensor look with its last label. It has no
limit bands and no units, because it has no key to read them from. The light
grey surround is the offscreen platform's default widget background; the
gauges do not paint one. Fonts are DejaVu Sans from the sandbox fontconfig.

Regenerate from the repo root:

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python3 docs/images/aer-5390/render.py
```
