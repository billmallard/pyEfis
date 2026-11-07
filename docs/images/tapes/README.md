# Airspeed, altitude and VSI pictures

For [Airspeed, Altitude and Vertical Speed](../../wiki/Airspeed-Altitude-and-Vertical-Speed.md).

| File | Source frame | Crop box | Scale |
|---|---|---|---|
| `bench_airspeed_tape.png` | `105321_chg_FPLACTLEG_WPNAME_WINCH.png` | (130, 50, 270, 660) | 2, nearest-neighbour |
| `bench_altitude_climb.png` | `105321_chg_FPLACTLEG_WPNAME_WINCH.png` | (1000, 50, 1200, 660) | 2, nearest-neighbour |
| `bench_altitude_altsel_departed.png` | `110201_tick.png` | (1000, 50, 1200, 660) | 2, nearest-neighbour |

The page also uses two existing rendered sets, with their own READMEs: [`../aer3915_altsel/`](../aer3915_altsel/) and [`../aer3914_baro_box/`](../aer3914_baro_box/).

## Where they came from

Every picture is cropped from a full-screen grab of the simulator bench (the
Beelink, X11, 1920 x 1080) during sim-bench session `a9055711e732` on
2026-11-07, 10:44-11:05 UTC. The bench was flying the KSMX RNAV (GPS) RWY 30
with its missed approach and the WINCH hold, on pyEFIS `dev` (the bench checkout read `5abf28d`; `src/` is identical from `980497e` to `c8d7ede`) with
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
