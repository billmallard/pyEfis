# AER-415: panel-fill punch-out fix + rose-disc finding

Produced offscreen with the real widget code (`tools/render_instrument.py`),
at the size the HSI occupies on a real PFD (`virtual_vfr.yaml`'s grid,
1920x1080: `horizontal_situation_indicator` 950x950 square) for the panel,
and a 500x500 render for the rose-disc probe crops.

## `panel_punch_out_comparison.png` -- Phase 1 fix

```bash
PYTHONPATH="C:/pylib;src" python tools/render_instrument.py \
    horizontal_situation_indicator \
    --options '{"font_percent":0.05,"cdi_enabled":true,"gsi_enabled":true,"bg_color":"#aaaaaa","shadow_enabled":true}' \
    --seed '{"HEAD":30}' \
    --width 950 --height 950 --screen-color "(150,190,235)" -o hsi_full_after_fix.png
# same options with "shadow_enabled":false -> hsi_full_no_shadow.png
# same options against the pre-AER-415 helpers.bake_blurred_silhouette (no
# punch-out, HEAD checked out at ca1bc62) -> hsi_full_before_fix.png
```

Each frame is cropped to the HDG|MAG|CRS panel + its shadow margin and
upscaled 2x nearest-neighbour. Top to bottom, grey/red/green tag bar:

1. **grey -- `shadow_enabled: false`** (baseline). Panel interior samples
   `(57, 72, 89)` at every point checked.
2. **red -- `shadow_enabled: true`, BEFORE the punch-out fix.** Same sample
   points read `(23, 29, 36)` -- uniformly darker across the WHOLE interior,
   not just the edge. This is the exact regression from the parent card
   (AER-412): Bill's PR-render arithmetic back-solved this to a second black
   layer at alpha 0.597 ~= `SHADOW_ALPHA` (0.6) laid across the entire panel
   body, silently making the deliberately-0.62 fill nearly opaque.
3. **green -- `shadow_enabled: true`, AFTER the punch-out fix.** Same sample
   points read `(57, 72, 89)` -- identical to the no-shadow baseline. The
   soft halo below the panel (visible in both the red and green frames,
   between the panel and the tick arc) is unchanged by the fix -- only the
   interior fill-through is gone.

## `rose_disc_shadow_probe.png` -- rose-disc finding (investigate-and-report)

```bash
PYTHONPATH="C:/pylib;src" python tools/render_instrument.py \
    horizontal_situation_indicator \
    --options '{"font_percent":0.08,"bg_color":"#aaaaaa","bg_opacity":<0|50>,"shadow_enabled":<true|false>}' \
    --seed '{"HEAD":30}' \
    --width 500 --height 500 --screen-color "(150,190,235)" -o roseB_op<op>_shadow<bool>.png
```

Same crop position (a clean disc quadrant, away from needles/labels),
upscaled 3x nearest-neighbour. Two rows, each a shadow-off / shadow-on pair:

- **Row 1 -- `bg_opacity: 0`** (the PFD's actual configuration: the disc is
  fully transparent over the SVS). Both crops are pixel-IDENTICAL --
  `(150, 190, 235)` at every sample point in both. **Not because Option 2 is
  immune to fill-through -- because the shadow is never drawn at all.**
  `hsi/__init__.py` (`resizeEvent`, the `_op > 0.0` gate around the compass-
  disc background item) only creates `_bgitem` -- the scene item the
  `QGraphicsDropShadowEffect` is attached to -- when `bg_opacity > 0`. At
  `bg_opacity: 0` no ellipse item exists, so `setGraphicsEffect` never runs.
  `shadow_enabled: true` currently has ZERO visible effect on the rose disc
  on the PFD as configured today.
- **Row 2 -- `bg_opacity: 50`** (translucent, to actually exercise the
  effect Qt applies to a partially-transparent source item). Visibly
  darker/greyer with the shadow on. Sample points: shadow off
  `(160, 180, 202)`, shadow on `(137, 151, 167)` -- a uniform ~14% darkening
  across the WHOLE disc interior, not just the rim. This is the SAME defect
  class as the pre-fix `bake_blurred_silhouette`: `QGraphicsDropShadowEffect`
  does not punch the source item's own footprint out of the shadow layer it
  paints underneath, so on anything less than fully opaque the shadow bleeds
  through. At `bg_opacity: 100` the item's own full-opacity fill completely
  occludes that layer, which is why the two-heading acceptance renders in
  the original AER-392 PR (`bg_color: "#aaaaaa"`, no opacity override, i.e.
  100) never surfaced this.

**Bottom line:** the defect Bill traced through the readout panel is a
property of the shared primitive, not of any one call site, and Option 2
(`QGraphicsDropShadowEffect`) has the identical failure mode -- it simply
does not currently manifest on the PFD because `bg_opacity: 0` skips drawing
a shadow at all, rather than because Qt's compositor "owns" the problem
correctly. No code change to the rose disc is made in this PR (out of
AER-415's Phase 1 scope, which is the shared primitive + its test); this is
a reported finding, and worth a follow-up if the rose is ever run with a
partial `bg_opacity`.

Font glyphs render as boxes in these renders -- this sandbox has no
fontconfig config file, so DejaVu Sans Condensed falls back to .notdef
boxes. Geometry, colour and the shadow itself are unaffected.
