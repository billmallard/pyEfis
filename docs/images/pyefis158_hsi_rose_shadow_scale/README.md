# pyEfis#158: the rose shadow cost radius and returned nothing

Third and last of the rose-shadow findings, after
`docs/images/aer415_hsi_shadow_punchout/README.md` (punch the shape out of its
own halo) and `docs/images/aer439_hsi_rose_shadow_fix/README.md` (bake the halo
instead of attaching a Qt effect). Those two made the halo *correct*. This one
is about it being *absent* -- and about the rose paying for it anyway.

Ticking **Drop shadow** on the HSI visibly shrank the compass rose and produced
no perceptible halo, so from the configurator the option read as "my rose got
smaller for no reason." That is exactly what it did.

## Two mistakes, compounding

**The blur came from the label font.** `resizeEvent` used
`self.fontSize * helpers.SHADOW_BLUR_RATIO`. That ratio is calibrated for the
readout boxes, whose geometry really is font-derived; the rose is a
widget-sized disc. At real panel geometry it produced a **1.75 px** blur against
a **164 px** radius -- measured at `<=1.7/255` outside the disc. Not a tuning
problem: at `font_percent 0.08`, ~8x the default font, it was still `<=1.7/255`.

**The clearance came from the bake-canvas pad.** The rose reserved
`blur * SHADOW_CANVAS_PAD_RATIO`. That constant exists so
`bake_blurred_silhouette` can size its QImage with room for the Gaussian to
resolve before the canvas edge (AER-392 gotcha #2); it is not a claim about how
far the halo reaches *on screen*. Because the bake punches the disc's own
footprint back out (AER-415), only the outward falloff survives, and it is
spent within about one blur radius. Reserving 3x surrendered triple the room
the halo could use -- and ignored the 5 px the rose already held to the widget
edge.

## The fix

`ROSE_SHADOW_BLUR_RATIO` (a fraction of the rose's own radius) replaces the
font-derived blur, so the halo stays proportional to the shape casting it.
`helpers.SHADOW_VISIBLE_FALLOFF_RATIO` names what callers should actually
reserve on screen, and the rose reserves only the part `ROSE_EDGE_MARGIN` does
not already cover -- at ordinary panel sizes, zero.

Readout-box shadows are a separate call path and are unchanged; their
font-proportional geometry is what `SHADOW_BLUR_RATIO` was calibrated for.

Note for anyone scaling the halo up in a test: the knob moved. The two rose
property tests monkeypatched `helpers.SHADOW_BLUR_RATIO`, which the rose no
longer reads -- the patch had gone inert and left them sampling the steep edge
of a ~2 px halo. They now scale `hsi.ROSE_SHADOW_BLUR_RATIO`.

## Measured, at real panel geometry

528x402 px -- the HSI's real size on the bench panel (55x41 cells of the
200x110 grid on 1920x1080), with that panel's actual options.

| | rose disc radius | glow just outside the disc |
|---|---|---|
| shadow off | 163.9 px | -- |
| shadow on, before | 158.5 px (**-5.4**, 6.3% of area) | none measurable |
| shadow on, after | 163.8 px (-0.1, AA noise) | present, ~6% mean local contrast |

Method note, and a correction. An earlier revision of this file quoted
"19.2/255 just outside the disc, 0 by R+7px". Those figures were measured
against a reference circle derived from a brightness-threshold centroid, which
the rose's tick marks and labels skew -- the annuli were not where the caption
said they were, and the numbers are not reproducible. The sound comparison is a
DIFFERENCE against the unshadowed render, which is valid here precisely because
the fix leaves the rose radius alone, so the only thing that differs IS the
glow:

- pixels displaced by the rose moving: **11,090 -> 439** (i.e. the rose stops
  moving; 439 is antialiasing)
- zero difference anywhere inside r~155 px -- the AER-415 no-fill-through
  guarantee still holds
- the glow itself: peak 62/255, mean 4.8/255 across its band

That mean is ~6% of background luminance, which is measurable but reads as a
soft edge rather than as depth. **On the bench display it was reported as
extremely subtle and hard to observe** -- correctly. Fixing the scaling was
necessary but not sufficient; see
`docs/images/hsi_rim_glow/README.md` for what actually made it read.

## `rose_shadow_scale_comparison.png`

```bash
PYTHONPATH=src python tools/render_instrument.py \
    horizontal_situation_indicator \
    --options '{"font_family":"B612","bg_opacity":"30","heading_bug_enabled":true,"needle_width":"2","orientation":"heading_up","depth_rings":true,"shadow_enabled":<true|false>}' \
    --seed '{"HEAD":280,"COURSE":274}' \
    --width 528 --height 402 --screen-color "(150,190,235)" -o <out>.png
```
