# Panel pictures

For [The Panel at a Glance](../../wiki/The-Panel-at-a-Glance.md).

| File | Source frame | Crop box | Scale |
|---|---|---|---|
| `bench_panel_climb.png` | `105321_chg_FPLACTLEG_WPNAME_WINCH.png` | full frame | 1 |

## Where they came from

Every picture is cropped from a full-screen grab of the simulator bench (the
Beelink, X11, 1920 x 1080) during sim-bench session `a9055711e732` on
2026-11-07, 10:44-11:05 UTC. The bench was flying the KSMX RNAV (GPS) RWY 30
with its missed approach and the WINCH hold, on pyEFIS `dev` at `4c4f4dc` (the same code as `980497e`) with
its configurator panel (`screens/managed.yaml`). The grabs were taken by
[`../hsi/bench_flight/docs_flight.py`](../hsi/bench_flight/docs_flight.py), run
with that session id and the sim-bench service URL. Its event log is
[`../hsi/bench_flight/flight2_events.log`](../hsi/bench_flight/flight2_events.log); the source frame names below are the
names it gave each grab.

The grabs used `ffmpeg -f x11grab`. Some of these grabs can show the
previous grab's state, so every caption is read from the picture's own
readouts, never from the logged keys.

## Regenerate

```python
from PIL import Image
im = Image.open(SOURCE_FRAME).convert("RGB").crop(BOX)
im = im.resize((im.width * SCALE, im.height * SCALE), Image.NEAREST)  # SCALE 1 = no resize
im.save(OUT, optimize=True)
```
