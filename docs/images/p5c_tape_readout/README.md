# P5c tape readout renders (pyEfis #122)

Before/after strips for the airspeed and altimeter tape readout boxes, produced
offscreen with the real widget code:

```bash
PYTHONPATH="C:/pylib;src" python tools/render_instrument.py airspeed_tape \
    --width 160 --height 480 -o airspeed.png
PYTHONPATH="C:/pylib;src" python tools/render_instrument.py airspeed_tape \
    --width 160 --height 480 --screen-color "(150,190,235)" -o airspeed_sky.png
```

Each strip is four panels, left to right: **before / ground**, **after /
ground**, **before / sky**, **after / sky**. The sky pair is the one that
matters for the change -- the readout fill is translucent, so it only reveals
what it costs over a lit background, which is where these boxes actually live
on a PFD.

- `airspeed_tape.png` -- IAS readout box + TAS box
- `altimeter_tape.png` -- altitude readout box
