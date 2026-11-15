# AER-4453 evidence: colour tokens are pixel-neutral (style contract S1)

Offscreen renders of the real widgets through `tools/render_instrument.py`,
made from two trees: `dev` at `eed5e72` (before the tokens) and this branch.
Every comparison in `report.txt` is a byte-for-byte compare of the ARGB pixels.

**Result: 100 of 100 comparisons identical, 0 differ.**

`montage.png` shows one row per instrument that renders offscreen (variant 0,
sky screen, half scale):

| Column | What it is |
|---|---|
| base/stock | `dev`, no colour options: what ships today |
| head/stock | this branch, no colour options |
| head/token | this branch, every mapped colour option set to its token name (`fg_color: ink.primary`, ...) |
| head/theme | this branch, no colour options, plus a `styles: colors:` block at the built-in token values, so the theme fills every mutable mapped prop |
| control | this branch, one mapped prop set to `#ff0123`, to show the compare does see a change |

## What the pixels cover, and what they don't

`report.txt` also has a sensitivity pass. It renders each mapped prop alone at
a loud literal and records whether any pixel moved. An identity verdict only
covers props that were drawn. **20 of the 29 mapped props are drawn in at least
one render.** The other 9 are not:

- `button` `bg_color`/`fg_color` and `virtual_vfr` `symbol_color`/
  `horizon_heading_color`: the renderer draws a placeholder for config-driven
  and GL widgets.
- `moving_map` `road_color`/`river_color`: there is no road or water data in
  the offscreen render.
- `checklist` `done_color`/`current_color`: these need an acknowledged item and
  a focused cursor.
- `value_text` `value_color`: the widget picks its value colour up on the next
  value update, and an offscreen render never updates the value. This is the
  same on `dev`.

For those 9, the evidence is the unit tests in
`tests/screens/test_color_tokens.py`. Each token's built-in value equals the
registry default of every prop that reads it. Resolving every prop's token
yields exactly its default literal. A theme at the built-in values fills every
prop with exactly its default. So the widget receives the same option values
either way.

Text renders with DejaVu from matplotlib's font directory. This sandbox has no
system fontconfig, so the run supplies its own (below).

## How to regenerate

From this checkout, with a `dev` checkout before the tokens at `<base>`:

    cat > /tmp/fonts.conf <<EOF
    <?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd">
    <fontconfig><dir><path containing DejaVuSans.ttf></dir></fontconfig>
    EOF
    FONTCONFIG_FILE=/tmp/fonts.conf QT_QPA_PLATFORM=offscreen PYTHONPATH=src \
        python3 tools/color_token_identity.py --base <base> --out <out_dir>

It writes every render, `report.txt` and `montage.png` to `<out_dir>`, and
exits 1 if any comparison differs. A full run takes about 6 minutes.
