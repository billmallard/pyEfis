# AER-389 / pyEfis#140 -- HSI nav-source tab renders

Before/after renders for the nav-source annunciation reformat (floating
top-left label -> coloured tab on the HDG | MAG | CRS panel's left edge),
produced offscreen with the real widget code at the real-PFD HSI size
(`virtual_vfr.yaml`'s 1920x1080 grid gives a 950x950 HSI square):

```bash
PYTHONPATH="C:/pylib;src" python tools/render_instrument.py \
    horizontal_situation_indicator \
    --options '{"font_percent":0.05,"cdi_enabled":true,"gsi_enabled":true}' \
    --seed '{"NAVSRC":2}' --width 950 --height 950 \
    --screen-color "(150,190,235)" -o gps_sky.png
```

`--seed '{"NAVSRC":2}'` selects GPS (magenta tab); `{"NAVSRC":0,"NAVTYPE":0}`
selects NAV1 with no VOR/LOC decode, i.e. the "VLOC1" fallback label -- the
widest of the source strings and the fit worst case. "before" is
`origin/dev` (plain floating label); "after" is this branch.

- `gps_tab_fp05.png`, `vloc1_tab_fp05.png` -- four panels each, left to
  right: before/ground, after/ground, before/sky, after/sky, at the shipped
  `virtual_vfr.yaml` ratio (`font_percent: 0.05`). Left corners rounded on
  `helpers.READOUT_RADIUS_RATIO`, right edge flush with the panel, no visible
  seam or doubled stroke, white text centred both axes, fill = active source
  colour, whole tab taller/shorter than the panel by twice the corner radius
  (reads as a tab, not a bolted-on box).
- `vloc1_tab_fp025_comfortable_fit.png` -- `font_percent: 0.025`, sky only.
  Comfortable margin; included as the other end of the shipped range.
- `corners_layout_unchanged.png` -- `readout_layout: corners`, before/after,
  sky. **Byte-identical** (`cmp` exit 0) -- this layout draws no HDG | MAG |
  CRS panel, so it keeps the plain top-left label untouched, exactly as
  pyEfis#140 acceptance #6 requires. `split`/`none` are the same code path
  and are not separately rendered here.
- `fp07_sixpack_overflow.png` -- **the escalation**, not a success case.
  `font_percent: 0.07` is what `sixpack.yaml` / `sixpack-portrait.yaml` /
  `sixpack-left-buttons.yaml` all ship (the only other font_percent used with
  `horizontal_situation_indicator` besides `virtual_vfr.yaml`'s 0.05). At
  that ratio `pw = fontSize * 12.5` already consumes ~87% of the widget's own
  width, leaving `px ~= 0.0625 * W` to the left of the panel -- less room
  than even the shortest label ("GPS") needs with no padding at all. The tab
  runs off the widget's left edge for every source string; this render shows
  only a sliver ("S", "1") surviving on-screen for GPS and VLOC1.

  Per pyEfis#140's hard boundary this is **not** silently fixed here (no
  panel resize/move, no shrink-to-fit, no silent text clipping) -- it is
  reported for Bill's call. See the pyEfis#140 comment thread / AER-389 for
  the writeup; docs/hsi_widget_spec.md sec 7.4 also carries the finding.
- `sixpack_screen_before_after.png` -- **the same finding, but in situ**: the
  actual `SIXPACK` preset screen (six gauges on a 200x110 grid, `move: {shrink:
  11, justify: [bottom]}` applied to the HSI cell), rendered whole and cropped
  to the HSI, at real screen resolution (1280x720; the render harness at
  `tests/screenshots/generate_screenshots.py::test_generate_preset_screen`).
  Produced with `GENERATE_SCREENSHOTS=1 python -m pytest
  tests/screenshots/generate_screenshots.py -k sixpack --no-cov -q` on
  `origin/dev` (before) and this branch (after).

  This shows something the isolated-widget render above doesn't: **the
  sixpack HSI is already too tight for the source label on `origin/dev`,
  before this PR touches anything.** "before" shows the old floating label
  ("VLOC1") with its last three characters hidden *underneath* the opaque
  HDG|MAG|CRS panel -- the label and panel already overlap today, just
  silently, because the label is painted first and the panel paints over it.
  "after" turns that same crowding into a visible clip at the widget's own
  left edge (only "1" of "VLOC1" survives) instead of a hidden one. Same root
  cause both times -- the sixpack HSI cell is only a few hundred px square at
  this grid span, and the panel alone (`pw = fontSize * 12.5`) is ~87-88% of
  that width regardless of the screen's absolute resolution (this ratio held
  at both 1920x1080 and 1280x720 test renders) -- there has never been enough
  room to the panel's left for the full label at `font_percent: 0.07`. This
  PR does not introduce the crowding; it changes which failure mode it takes.

## Contrast (pyEfis#140 acceptance #9)

Reusing the WCAG formula in `tests/instruments/test_readout_panel.py`
(`tests/instruments/hsi/test_hsi.py::test_hsi_source_tab_white_on_source_colour_contrast`
is the executable version of these numbers):

| pair | ratio | WCAG 4.5:1 floor |
|---|---|---|
| white text on `course_color` `#ff00ff` (GPS) | **3.14:1** | fail |
| white text on `vloc_color` `#00ff00` (VOR/LOC/VLOC) | **1.37:1** | fail |

Both fail badly, green far worse than magenta (pure `#00ff00` is close to
the eye's peak luminous sensitivity, which is exactly why it reads as
"bright" while still measuring low WCAG contrast against white). Per the
hard boundary: text stays white (Bill's direction stands); if this is fixed,
the fix is a **darker fill**, and that choice is Bill's, not something this
change decides.
