# Airspeed, altitude and VSI pictures

For [Airspeed, Altitude and Vertical Speed](../../wiki/Airspeed-Altitude-and-Vertical-Speed.md).

| File | Source frame | Crop box | Scale |
|---|---|---|---|
| `bench_airspeed_tape.png` | `052133_chg_FPLACTLEG_WPNAME_WINCH.png` | (130, 50, 270, 660) | 2, nearest-neighbour |
| `bench_altitude_climb.png` | `052133_chg_FPLACTLEG_WPNAME_WINCH.png` | (1000, 50, 1200, 660) | 2, nearest-neighbour |
| `bench_altitude_altsel_departed.png` | `053037_tick.png` | (1000, 50, 1200, 660) | 2, nearest-neighbour |

The page also uses two existing rendered sets, with their own READMEs: [`../aer3915_altsel/`](../aer3915_altsel/) and [`../aer3914_baro_box/`](../aer3914_baro_box/).

## Where they came from

Every picture is cropped from a full-screen grab of the simulator bench (the
Beelink, X11, 1920 x 1080) during sim-bench session `8f9eb80b0daa` on
2026-11-07, 05:11-05:33 UTC. The bench was flying the KSMX RNAV (GPS) RWY 30
with its missed approach and the WINCH hold, on pyEFIS `dev` at `4c4f4dc` (the same code as `980497e`) with
its configurator panel (`screens/managed.yaml`). The follower that took the
grabs, its event log and the FIX keys logged at every grab are in
[`../hsi/bench_flight/`](../hsi/bench_flight/); the source frame names below are
the names in its `keys.jsonl`.

The grabs used `ffmpeg -f x11grab`. About half of that night's frames show the
previous grab's state, so every caption is read from the picture's own
readouts, never from the logged keys.

**Grey sky.** In every frame the sky is grey, not blue. The bench's X-Plane
connection does not send `ALAT`, so that attitude input stays flagged old, and
pyEFIS greys the sky while any attitude input is old or bad
(`src/pyefis/instruments/ai/ai_widget.py:586-590`).

## Regenerate

```python
from PIL import Image
im = Image.open(SOURCE_FRAME).convert("RGB").crop(BOX)
im = im.resize((im.width * SCALE, im.height * SCALE), Image.NEAREST)  # SCALE 1 = no resize
im.save(OUT, optimize=True)
```
