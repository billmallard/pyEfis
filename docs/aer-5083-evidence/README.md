# AER-5083 evidence: heading_display ink moves from grey to white (style contract S2)

`heading_display_before_after.png` is a 2x nearest-neighbour upscale. Left column:
`dev` at `fce470c1`. Right column: this branch. Rows: stock options on a black
panel, then `bg_opacity: 0` composited over a sky colour and a terrain colour.
The single-panel PNGs beside it are the 1:1 renders the montage was built from
(`base_*` = dev, `head_*` = this branch).

Measured on the 1:1 black-panel render: the text and frame pixels are
`(170,170,170)` before and `(255,255,255)` after. Same pixel count (2622) in both,
so only the colour changes; geometry is identical.

## Instruments affected

Only `heading_display`. Every other colour prop that S1 mapped to a token already
had a default equal to its token's value, so no other default moves. Shipped
screens: `includes/ahrs/virtual_vfr.yaml` places a `heading_display` without an
`fg_color`, so it changes from grey to white. `includes/ahrs/svs.yaml` already sets
`fg_color: "#FFFFFF"`, so it does not change.

## How to regenerate

From this checkout, with a `dev` worktree at `<base>`, under the sandbox's
offscreen Qt (see `docs/aer-4453-evidence/README.md` for the fontconfig setup):

    for T in <base> .; do (cd $T && PYTHONPATH=src QT_QPA_PLATFORM=offscreen \
      python3 tools/render_instrument.py heading_display --seed '{"HEAD":87}' \
        --width 200 --height 80 -o <out>/black.png && \
      python3 tools/render_instrument.py heading_display --seed '{"HEAD":87}' \
        --width 200 --height 80 --options '{"bg_opacity":0}' \
        --screen-color '(150,190,235)' -o <out>/sky.png && \
      python3 tools/render_instrument.py heading_display --seed '{"HEAD":87}' \
        --width 200 --height 80 --options '{"bg_opacity":0}' \
        --screen-color '(96,112,64)' -o <out>/terrain.png); done
