# flight_plan font sizing (fp-font-scale)

Bench report (Beelink, Flight Plan tab ~657x1003): the text is far too large
and the configurator's `font_percent` has no effect. Offscreen renders of the
real widget, not bench captures -- DejaVu Sans Condensed loaded explicitly
(the widget's font, same as the bench), plan published through the real
`FixBridge` with `FPLSTATE`=DIRECT, `FPLREMDIS`=55, `FPLREMETE`=0 so the
header matches the report.

- `compare_fpl_657x1003.png` (`fpl_657x1003_*.png`) -- the Beelink tab size.
  Before: "KSBA-KSMX" runs under "DIRECT", which runs under "55 NM 0:00";
  the idents collide with the DTK column; the footer labels run together.
  After: fonts shrink by width/height (0.655 here); nothing overlaps.
  `font_percent 0.8` scales that down a further 20%.
- `compare_fpl_1000x600.png` (`fpl_1000x600_*.png`) -- a landscape pane.
  Before and after are pixel-identical (fit = 1.0); only the `font_percent
  0.8` variant changes.
- `compare_fpl_960x1080_stock_screen.png` -- the stock `flightplan.yaml`
  layout (right half of 1920x1080). Slightly portrait, so its text shrinks to
  0.889x. Nothing overlapped there before; this is the only default-setting
  change on a shipped screen.
- `compare_entry_657x1003.png` -- the Entry page at the tab size: every font
  on every page takes the same scale (keypad glyphs included); key and tab
  rectangles, and all tap targets, do not move.

Before `font_percent 0.8` is not shown because it rendered pixel-identical
to before-default (the bug: the builder dropped the value and nothing read
it).

Regenerate (from each checkout's root; "before" from a pristine `origin/dev`
tree, "after" from this branch):

```bash
export QT_QPA_PLATFORM=offscreen PYTHONPATH="<pyavtools>:src:."
python docs/images/fp_font_scale/render_evidence.py render /tmp/fp before --sizes 657x1003,1000x600,960x1080
python docs/images/fp_font_scale/render_evidence.py render /tmp/fp after  --sizes 657x1003,1000x600,960x1080
python docs/images/fp_font_scale/render_evidence.py render /tmp/fp after_fp80 0.8
python docs/images/fp_font_scale/render_evidence.py compose out.png "before=/tmp/fp/before_657x1003.png" "after=/tmp/fp/after_657x1003.png"
```

(`render_evidence.py` is the exact script that produced these PNGs.)
