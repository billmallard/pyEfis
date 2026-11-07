# Moving map pictures

For [Moving Map](../../wiki/Moving-Map.md).

| File | Source frame | Crop box |
|---|---|---|
| `bench_map_approach.png` | `104649_tick.png` | (1248, 0, 1920, 1080) |
| `bench_map_hold.png` | `110201_tick.png` | (1248, 0, 1920, 1080) |

Cropped from full-screen `ffmpeg -f x11grab` grabs of the simulator bench (the
Beelink, X11, 1920 x 1080) during sim-bench session `a9055711e732` on
2026-11-07, 10:44-11:05 UTC: the KSMX RNAV (GPS) RWY 30 via GVO, its missed
approach and the WINCH hold, on pyEFIS `dev` (the bench checkout read `5abf28d`; `src/` is identical from `980497e` to `c8d7ede`) with the bench's
configurator panel. The grabs were taken by
[`../hsi/bench_flight/docs_flight.py`](../hsi/bench_flight/docs_flight.py); its
log is [`../hsi/bench_flight/flight2_events.log`](../hsi/bench_flight/flight2_events.log).
Some x11grab frames show the previous grab's state, so captions are read from
each picture's own readouts.

The page also uses `../fp10_map_edit/01_tap_rzs_banner.png`, an earlier bench
capture with its own README.

```python
from PIL import Image
Image.open(SOURCE_FRAME).convert("RGB").crop(BOX).save(OUT, optimize=True)
```
