# AER-439: rose-disc shadow fill-through fix

Follow-up to AER-415's rose-disc finding (`docs/images/aer415_hsi_shadow_punchout/README.md`):
`QGraphicsDropShadowEffect` attached directly to the compass-disc background
item has the identical fill-through defect AER-415 fixed in
`helpers.bake_blurred_silhouette` -- Qt's effect draws the item's own
(possibly translucent) source back on top of an *unpunched* blurred halo at
zero offset, so a translucent disc reads that halo straight through and
tints its own interior. It never showed on the PFD's real config
(`bg_opacity: 0`, no background item at all) or at `bg_opacity: 100` (the
opaque fill fully occludes the halo) -- only a partial opacity exercises it.

## The fix

`src/pyefis/instruments/hsi/__init__.py`'s `resizeEvent`: the rose disc no
longer attaches a `QGraphicsDropShadowEffect` to its own background item.
Instead it bakes the halo with the already-fixed, already-punched
`helpers.bake_blurred_silhouette` primitive and adds it as its own
`QGraphicsPixmapItem`, `z=-2`, strictly *behind* the disc's fill item
(`z=-1`) -- the disc's own translucent fill is drawn undisturbed on top,
the same "fix lives in the shared primitive" precedent AER-415 set for the
readout panel. The now-orphaned `helpers.drop_shadow_effect()` Qt-effect
wrapper (and its two dedicated unit tests) were deleted -- nothing calls it
anymore, and it structurally cannot punch out its own shape.

Regression test: `tests/instruments/hsi/test_hsi.py::
test_shadow_rose_disc_translucent_fill_unchanged_by_shadow` -- same standard
as AER-415's `test_shadow_baked_silhouette_leaves_shape_interior_unchanged`.
Confirmed failing against the pre-fix code (interior `(169,169,169)` ->
`(131,131,131)`, a ~22% darkening at `font_percent 0.1` / no `bg_color`)
and passing after.

## `rose_disc_shadow_fix_comparison.png`

```bash
PYTHONPATH=src python tools/render_instrument.py \
    horizontal_situation_indicator \
    --options '{"font_percent":0.08,"bg_color":"#aaaaaa","bg_opacity":50,"shadow_enabled":<true|false>}' \
    --seed '{"HEAD":30}' \
    --width 500 --height 500 --screen-color "(150,190,235)" -o <out>.png
# "shadow on, BEFORE fix" rendered against dev @ 7220477 (pre-AER-439 HEAD)
```

Same clean disc quadrant as the AER-415 probe (crop `(330,200,470,300)`,
3x nearest-neighbour), three rows:

1. **green tag -- no shadow (baseline).** Interior samples `(160, 180, 202)`.
2. **red tag -- shadow on, BEFORE this fix.** Same sample point reads
   `(137, 151, 167)` -- the ~14% darkening AER-415 already measured on this
   exact probe.
3. **green tag -- shadow on, AFTER this fix.** Same sample point reads
   `(160, 180, 202)` -- byte-for-byte identical to the no-shadow baseline.
   The shadow itself (the soft halo past the disc's rim, visible in all
   three frames as the darker sky band) is unchanged; only the interior
   fill-through is gone.

Font glyphs render as `.notdef` boxes in this sandbox (no fontconfig
config file present) -- geometry, colour and the shadow itself are
unaffected, same caveat as the AER-415 renders.
