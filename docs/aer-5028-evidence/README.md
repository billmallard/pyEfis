# AER-5028 -- HSI under a fail-only CDI flag and a failed COURSE (G66, billmallard/pyEfis#392)

The real `HSI` widget at 360 x 400, GPS source (magenta), heading 000, CDI at
its failed value of 0, `CDIV` = 1 (receiving). Course is 045 while valid and
000 (the failed value) while failed. These are offscreen grabs of the HSI's
viewport, its paint surface, from the in-memory mock FIX database.

| Image | What it shows |
|---|---|
| `strip_heading_up.png` | rose. Top row `dev` (8017016a), bottom row the fix. Left to right: all valid / CDI fail-only (bad false, fail true) / COURSE failed |
| `strip_arc.png` | the same three scenes in the arc layout |
| `before/*.png`, `after/*.png` | the single frames the strips are made of |

What changes:

- **CDI fail-only.** `dev` raises the NAV flag and still draws the deviation
  bar, centred on the pointer: "on course" under the flag. The fix draws no
  bar while NAV shows. The course pointer stays, because COURSE is valid.
- **COURSE failed.** `dev` draws the pointer and the deviation scale at the
  failed value (000) and the CRS readout reads `000°`. The fix draws neither
  and the readout reads `---°`.

The rose numerals vanish in the CDI fail-only frames on both sides. That is
the existing `changeFail()` label blanking on any CDI fail, not this change.

Fonts: the sandbox that drew these has no system fonts, so DejaVu Sans was
registered and substituted for the widget's families. Glyph shapes differ
from the panel; the geometry does not.

## Regenerate

From the repo root, once on the fix and once on a `dev` checkout with this
script copied in:

```bash
QT_QPA_PLATFORM=offscreen python docs/aer-5028-evidence/render_g66.py OUTDIR
```

`render_instrument._load_fonts()` registers DejaVu from the usual system paths.
The strips are the six frames of each side laid out 3 x 2 with a 4 px gutter.
