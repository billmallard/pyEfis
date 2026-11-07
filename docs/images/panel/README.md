# Panel pictures

For [The Panel at a Glance](../../wiki/The-Panel-at-a-Glance.md).

| File | Source frame | Crop box | Scale |
|---|---|---|---|
| `bench_panel_climb.png` | `052133_chg_FPLACTLEG_WPNAME_WINCH.png` | full frame | 1 |

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
