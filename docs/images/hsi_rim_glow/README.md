# HSI rose rim glow: a gradient, at a strength that reads

Last of the rose-shadow chain: AER-392 (introduce) -> AER-415 (punch the shape
out of its own halo) -> AER-439 (bake it instead of using a Qt effect) ->
pyEfis#158 (stop deriving it from the label font, stop charging the rose 6.3%
of its area) -> here.

#158 fixed what the glow was proportional to. It did not make the glow
**visible**: on the bench display it was still reported as extremely subtle and
hard to observe, and the measurement agreed -- about 6% mean local contrast,
spread thin.

## Why the blur could not get there

The intended look is a symmetric, zero-offset black rim glow -- a shadow cast
from an infinitely distant light source. That is also the only shadow that can
be correct here: the item is captured by the rose bake and rotated per heading,
so an offset one would make the implied light orbit as the card turns (AER-392
gotcha #1). The offset was never the problem.

The problem was that a blurred silhouette cannot express a stated width or a
stated opacity:

- a Gaussian step edge lands at only **~50% of its fill alpha** at the shape's
  own edge, so `SHADOW_ALPHA = 0.6` delivered ~30% before antialiasing;
- its tail runs far past the nominal blur radius -- the visible band measured
  ~20 px for a 4.9 px blur.

Simultaneously too faint and too diffuse. Turning the alpha up would have made
a broad smudge, not a shadow.

## What it is now

A **radial-gradient annulus**, which states the profile outright:
`ROSE_SHADOW_ALPHA` at the disc edge, zero at `ROSE_GLOW_WIDTH_RATIO` out,
shaped by `helpers.RIM_GLOW_FALLOFF` (an eased 100/55/25/0 curve so the outer
limit fades instead of ending on an edge). Width is literal, so the clearance
reservation no longer estimates a Gaussian tail. Costs no blur pass.

Clipped to a ring, never the interior -- that keeps the AER-415 no-fill-through
guarantee **geometrically**: there is nothing inside `self.r` for a translucent
disc fill to read through, rather than nothing left after a punch-out.

Shipped values are Bill's, from the equivalent Fireworks treatment, chosen off
a rendered sweep (`rim_glow_opacity_sweep.png`) and then reviewed on the bench
display: **45% opacity**, **~10 px wide** (0.06 of rose radius).

## The trade the width exposes (`rim_glow_width_compare.png`)

At real panel geometry the rose sits only `ROSE_EDGE_MARGIN` (5 px) from the
widget edge vertically. A glow wider than that margin **cannot extend
outward** -- the clearance reservation takes the difference out of the rose
instead. So:

| | rose radius | glow occupies | outer edge |
|---|---|---|---|
| shadow off | 163.8 | -- | -- |
| 5 px glow | 163.8 (no cost) | 163.8 -> 168.8 | **168.8** |
| 10 px glow | 159.0 (-4.8, 5.8% of area) | 159.0 -> 168.8 | **168.8** |

Both end at the same outer edge. This is not "5 px vs 10 px of glow" -- it is a
bigger rose with a tight rim versus a smaller rose with a broad rim, inside a
fixed envelope. The 4.8 px is the same magnitude #158 removed, but it now buys
something visible, which makes it a trade rather than a defect. Accepted
deliberately (Bill, on-display review); the HSI can be given more grid cells in
the configurator if the rose size is wanted back.

Measurement note: a difference-against-unshadowed comparison is only valid
while the rose radius is unchanged. At 10 px it is not, so the difference image
measures rose-versus-background at the edge, not glow -- the geometry table
above is computed from the radius arithmetic instead, and that is the sound
comparison. The same trap produced the figures corrected in
`../pyefis158_hsi_rose_shadow_scale/README.md`.

## Reproducing

```bash
PYTHONPATH=src python tools/render_instrument.py \
    horizontal_situation_indicator \
    --options '{"font_family":"B612","bg_opacity":"30","heading_bug_enabled":true,"needle_width":"2","orientation":"heading_up","depth_rings":true,"shadow_enabled":<true|false>}' \
    --seed '{"HEAD":280,"COURSE":274}' \
    --width 528 --height 402 --screen-color "(150,190,235)" -o <out>.png
```

`--screen-color "(110,140,85)"` renders it over terrain instead of sky. A black
glow has roughly 40% less to work with over dark terrain, which is what drove
the opacity choice.
