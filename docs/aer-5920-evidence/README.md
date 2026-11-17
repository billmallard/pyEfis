# HSIARC1 (AER-5920) evidence: arc HSI compass marks off 5-degree headings

`arc_before_after.png`: the arc HSI at headings 120, 123 and 127.5, offscreen,
340x405 (the HSI box on the Beelink PFD), 1:1. Top row is `dev`, bottom row is
this branch. On `dev` the numerals and cardinals show only at 120; at 123 and
127.5 the band has no labels and its ticks sit off the compass marks. After
the fix all three headings carry their numerals and ticks on true 5-degree marks.

Regenerate from a checkout of this branch:

```bash
export QT_QPA_PLATFORM=offscreen PYTHONPATH=src:.
D=docs/aer-5920-evidence
git stash -- src                                   # dev's _paint_arc
python3 $D/render_arc.py row /tmp/before_row.png
git stash pop
python3 $D/render_arc.py row /tmp/after_row.png
python3 $D/render_arc.py sheet /tmp/before_row.png /tmp/after_row.png $D/arc_before_after.png
```

The only `src` change on this branch is `_paint_arc`, so stashing `src`
reverts to `dev`'s paint path for the before row.
