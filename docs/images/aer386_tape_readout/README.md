# AER-386 tape readout renders (delete arrow + match HSI corner radius)

Before/after renders for the airspeed and altimeter tape readout boxes,
produced offscreen with the real widget code, at the sizes these instruments
occupy on a real PFD (`virtual_vfr.yaml`'s grid, 1920x1080: airspeed/altimeter
tapes 144px wide; HSI top_panel 950x950 square):

```bash
PYTHONPATH="C:/pylib;src" python tools/render_instrument.py airspeed_tape \
    --options '{"font_percent":0.25}' --width 144 --height 982 \
    --screen-color "(150,190,235)" -o airspeed_sky.png
PYTHONPATH="C:/pylib;src" python tools/render_instrument.py altimeter_tape \
    --options '{"font_percent":0.24,"majorDiv":100}' --width 144 --height 1080 \
    --screen-color "(150,190,235)" -o altimeter_sky.png
PYTHONPATH="C:/pylib;src" python tools/render_instrument.py \
    horizontal_situation_indicator \
    --options '{"font_percent":0.05,"cdi_enabled":true,"gsi_enabled":true,"bg_color":"#aaaaaa"}' \
    --width 950 --height 950 --screen-color "(150,190,235)" -o hsi_sky.png
```

"before" is `origin/dev` (arrow present, shared `READOUT_RADIUS_RATIO` on the
tape box); "after" is this branch (arrow deleted, tape box on the new
`TAPE_READOUT_RADIUS_RATIO`).

- `airspeed_tape.png`, `altimeter_tape.png` -- four panels each, left to
  right: before/ground, after/ground, before/sky, after/sky. Two changes are
  visible together: the arrow is gone, and the box corners are visibly
  flatter (matching the HSI's restrained rounding instead of the old
  near-pill look).
- `hsi_panel_unchanged.png` -- the HSI top_panel readout corner, ground and
  sky, on this branch. Included as the regression check: this render is
  byte-for-byte identical to the same render off `origin/dev` (verified with
  `PIL.ImageChops.difference(...).getbbox() is None`) -- `hsi/__init__.py`
  and `READOUT_RADIUS_RATIO` are untouched by this change.

## Measured radius (posted to AVIONICS-DATA for the configurator twin, AER-386)

At the real-PFD size above (1920x1080 layout, `virtual_vfr.yaml` grid):

- HSI top_panel panel: 950x950, `font_percent=0.05` -> `fontSize=48` ->
  radius = `48 * READOUT_RADIUS_RATIO(0.35)` = **16.8px**, on a panel height
  of `gutter(152) * 0.76` = 115.52px (**14.5%** of panel height).
- Reusing that 16.8px literally on the tape box (font_height 22.0, panel
  height `1.20 * 22.0` = 26.4px) exceeds half the panel height, so Qt clamps
  the rounded rect to a full stadium/pill -- rendered and confirmed
  indistinguishable from the too-round original, i.e. not a fix.
- Matching the HSI's *proportion* instead: target tape radius =
  `0.145 * 26.4` = 3.84px = `0.1745 * font_height`, rounded to
  **`TAPE_READOUT_RADIUS_RATIO = 0.17`** (3.74px at that font_height).

Base quantity: `font_height`, the fitted digit glyph height in
`NumericalDisplay` (`pyefis.instruments.NumericalDisplay`), NOT the same base
quantity as `READOUT_RADIUS_RATIO` (which is against the HSI's `fontSize`) --
see the token's docstring in `pyefis.instruments.helpers` for the full
derivation.
