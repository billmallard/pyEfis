# AER-6245 (SDRVOR3): supplemental nav source mark on the HSI

Offscreen renders of the HSI at its served size and options: the Beelink bench's
`screens/managed.yaml` places it at 55 x 41 cells of a 200 x 110 grid on
1920 x 1080, so 528 x 403 px, with `readout_layout: top_panel`, `bg_opacity: 30`,
bearing pointers on, `heading_bug_enabled`, `track_indicator_enabled`. The HSI is
drawn over a flat terrain-colour fill standing in for the SVS behind it. The
sandbox has no B612, so the text is in a fallback face.

The state is what fix-gateway publishes with `sdr_vor` on NAV2 and NAV2 selected:
`NAVSRC` 1, `NAVTYPE` 1 (VOR) or 2 (LOC), `CDIV` 1 and a live `CDI` (valid) or
`CDIV` 0 and `CDI` failed (flagged), `GSV` 0, `GSI` old (`NAV2GSI` has no writer),
`NAVSUPP` 1.

- `sheet.png`: top row VOR, bottom row LOC. Left: `dev` (no mark). Middle: branch,
  valid. Right: branch, flagged.
- `inset_4x.png`: the source tab, `dev` left and branch right, 4x nearest-neighbour.
- `supp1_*.png`, `dev_*.png`: the single frames.

`dev` renders `NAVSUPP` = 1 the same as the branch renders it absent or 0: the
branch's absent and 0 frames are byte-identical to `dev`'s in all seven states the
script draws. With `NAVSUPP` = 1, every branch frame differs from `dev` only inside
the box (122, 60)-(160, 71), the mark.

Regenerate (from a pyEfis checkout; `dev` for the left column):

```
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=<Qt libs> FONTCONFIG_FILE=<fonts.conf> \
  python3 docs/images/aer-6245/render_navsupp.py src <out dir>
```
