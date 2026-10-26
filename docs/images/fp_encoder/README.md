# flight_plan encoder focus ring (FP5c, AER-810, pyEfis#188)

Offscreen renders of the real widget at the Beelink Flight Plan tab size
(657x1003), driven ONLY through the `enc_*` protocol (`enc_highlight`,
`enc_select`, `enc_changed`, `enc_clicked`) -- no touch, no keyboard.
Rendered on the Beelink (`~/pyefis-venv`, offscreen, from a throwaway clone
of the branch; the live checkout and display were not touched). Not a bench
capture with the physical knob: that is the separate on-glass step.

`fp_encoder_4up.png`, left to right:

1. `1_fpl_row_focused.png` -- FPL page, two detents: the GVO row has the
   orange focus box.
2. `2_row_menu.png` -- push on that row, three detents: Activate Leg focused
   (the page behind is dimmed and is not in the ring).
3. `3_entry_editing.png` -- ADD WPT by knob, K and S dialled in: the cursor
   (orange underline) sits on the blank after S, FastFind predicts the cyan
   `BA`; a push now accepts KSBA.
4. `4_dto_shortcut.png` -- push with nothing focused on the FPL page (active
   leg 2): Direct To opens on the FPL tab with GVO pre-selected (cyan) and
   ACTIVATE focused, so a second push activates.

Caveats, so nobody reads them as findings of this change:
- The Beelink has no DejaVu Sans Condensed installed (`fc-list`), so text is
  in the regular-width fallback face.
- `0 NM 0:00` and `LOI` in the header: the mock FIX bus has no nav engine
  publishing remaining distance / integrity.
- The very large row text on the DTO FPL tab (panel 4) is that tab's existing
  sizing (`row_h = h / len(rows)`, font = row_h * 0.42), unchanged here.

Regenerate (from the root of a checkout of the branch):

```bash
QT_QPA_PLATFORM=offscreen python docs/images/fp_encoder/render_evidence.py <outdir> [657x1003]
```
