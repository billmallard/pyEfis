# AER-5028 -- HSI failure flags (G66, billmallard/pyEfis#392)

The real `HSI` widget at 360 x 400, GPS source (magenta), heading 000, CDI at
its failed value of 0, `CDIV` = 1 (receiving), a glideslope expected
(`GSV` = 1) with GSI at 0. Course is 045 while valid and 000 (the failed
value) while failed. These are offscreen grabs of the HSI's viewport, its
paint surface, from the in-memory mock FIX database.

| Image | What it shows |
|---|---|
| `strip_heading_up.png` | rose. Top row `dev` (8017016a), bottom row the fix (dde5caa7). Left to right: all valid / CDI fail-only (bad false, fail true) / COURSE failed / HEAD failed / GSI failed |
| `strip_arc.png` | the same five scenes in the arc layout |
| `before/*.png`, `after/*.png` | the single frames the strips are made of |

What changes (Bill, 2026-11-08: the HSI never signals a failure only by
taking a symbol away):

- **CDI fail-only.** `dev` raises NAV and still draws the deviation bar,
  centred on the pointer: "on course" under the flag. The fix draws no bar
  while NAV shows (G66).
- **COURSE failed.** `dev` draws the pointer at the failed 000 and reads
  `000°`. The fix removes the pointer and the scale rotated to it, reads
  `---°`, and raises NAV.
- **HEAD failed.** On the rose, `dev` draws the HDG flag at the top centre,
  where the readout panel covers it (the red edge behind MAG). The fix puts
  it inside the card, upper right. The arc's HDG flag was already visible
  and is unchanged.
- **GSI failed.** GS flag on both sides; unchanged. The fix adds the GS flag
  for a stale GSI and for a lost GSI with no `GSV` key, which these scenes do
  not show (unit tests cover them).

The rose numerals vanish on CDI and GSI failure on both sides. That is the
existing `changeFail()` label blanking, not this change.

Fonts: the sandbox that drew these has no system fonts, so DejaVu Sans was
registered and substituted for the widget's families. Glyph shapes differ
from the panel; the geometry does not.

## Regenerate

From the repo root, once on the fix and once on a `dev` checkout with this
script copied to the same path:

```bash
QT_QPA_PLATFORM=offscreen python docs/aer-5028-evidence/render_g66.py OUTDIR
```

The script puts its own checkout first on `sys.path`, so run the copy inside
the checkout being drawn. The strips are the five frames of each side laid
out 5 x 2 with a 4 px gutter.
