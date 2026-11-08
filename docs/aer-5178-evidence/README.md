# AER-5178 (CERT1a): a failed tape carries a red X and no scale

pyEfis #411's "fixgw stopped 6 s" frame showed the attitude indicator grey under
a large red XXX, but the airspeed, altitude and VSI tapes showed their failure
only as a small red XXX in the readout box, and kept drawing scale numbers,
coloured bands and trend vectors that can still be read as live.

## The two looks (offscreen widget renders, Beelink fonts)

`variants_sheet.png`, left to right: the tapes live, the tapes failed on `dev`
today, look A (red X over the scale), look B (scale blanked + red X; the
branch default). Each panel is airspeed, altitude, VSI trend tape at their
Beelink PFD sizes (120x590, 115x590, 65x400). The single strips are
`live.png`, `dev_failed.png`, `x_over_scale.png` and `blanked.png`.

In both looks the readout boxes keep their red XXX, the VSI tape keeps its
"VSI / XXX" header, and the TAS and baro boxes keep drawing, because those are
their own data (TAS, BARO). Look B also drops the trend vectors, the altitude
bug and the VSI moving dot. `helpers.FAILED_TAPE_BLANK_SCALE` selects between
them.

Regenerate (from a pyEfis tree; a `dev` tree for `live` and `dev`, the branch
for the two looks):

```sh
export QT_QPA_PLATFORM=offscreen PYTHONPATH=src:.
python docs/aer-5178-evidence/render_tape_variants.py strip live live.png
python docs/aer-5178-evidence/render_tape_variants.py strip dev dev_failed.png
python docs/aer-5178-evidence/render_tape_variants.py strip x_over_scale x_over_scale.png
python docs/aer-5178-evidence/render_tape_variants.py strip blanked blanked.png
python docs/aer-5178-evidence/render_tape_variants.py sheet variants_sheet.png \
  live.png "Live (reference)" dev_failed.png "Failed today (dev)" \
  x_over_scale.png "A: red X over scale" blanked.png "B: scale blanked + red X"
```

The Beelink has no DejaVu Sans Condensed, so text falls back to DejaVu Sans, as
it does on the glass.
