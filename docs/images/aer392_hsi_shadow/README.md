# AER-392 HSI static-element drop shadow renders

Produced offscreen with the real widget code (`tools/render_instrument.py`),
at the size the HSI occupies on a real PFD (`virtual_vfr.yaml`'s grid,
1920x1080: `horizontal_situation_indicator` 950x950 square):

```bash
PYTHONPATH="C:/pylib;src" python tools/render_instrument.py \
    horizontal_situation_indicator \
    --options '{"font_percent":0.05,"cdi_enabled":true,"gsi_enabled":true,"bg_color":"#aaaaaa","shadow_enabled":true}' \
    --seed '{"HEAD":30}' \
    --width 950 --height 950 --screen-color "(150,190,235)" -o hsi_full_hdg030.png
# same options, --seed '{"HEAD":210}' -o hsi_full_hdg210.png
# same options with "shadow_enabled":false for the no-shadow twins
```

## Rose shadow (Option 2: QGraphicsDropShadowEffect on the disc scene item)

- `rose_rim_shadow_hdg030.png` / `rose_rim_no_shadow_hdg030.png` -- a crop of
  the rose's right rim at HEAD=30, with and without `shadow_enabled`. The
  shadow version shows a soft dark halo hugging the rim and fading into the
  sky; the plain version cuts straight from the white ring to sky.
- `rose_rim_shadow_hdg210.png` -- the SAME screen-space crop at HEAD=210 (180
  deg apart, well past the 45 deg acceptance bar). The tick marks have moved
  (proof the card actually rotated); the halo has not -- same shape, same
  softness, same position relative to the rim. This is the AER-392 gotcha #1
  check: the shadow is baked with zero offset specifically so a light source
  does not appear to swing with heading once the bake is rotated per frame.

## Readout-panel shadow (Option 4: baked blurred silhouette)

- `panel_shadow.png` / `panel_no_shadow.png` -- the top_panel HDG|MAG|CRS
  readout, with and without `shadow_enabled`. The shadow version shows a
  soft shadow under the panel against the sky; both the panel and the
  underlying bake are static screen-fixed geometry, so this costs one blit
  per frame like the panel itself, not a per-frame blur.

## Full frames

- `hsi_full_hdg030.png`, `hsi_full_hdg210.png` -- the full 950x950 renders
  the crops above were taken from, `shadow_enabled: true` throughout.

Font glyphs render as boxes in these renders -- this sandbox has no
fontconfig config file, so DejaVu Sans Condensed falls back to .notdef boxes.
Geometry, colour and the shadow itself are unaffected.
