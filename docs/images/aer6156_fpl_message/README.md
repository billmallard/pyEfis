# AER-6156: the FPL page message moves off the header

Each `before_after_<W>x<H>.png` shows four renders of the real `flight_plan`
widget at 1:1, left to right:

1. `STORED` on `dev` `f7fc078e`
2. `STORED` on this branch
3. `OBS NOT AVAILABLE: NO ACTIVE WAYPOINT` (with LNAV and LOI up) on `dev`
4. the same on this branch

The plan is active (LEG, 48 NM 0:24). The panes:

- `649x993`: the Beelink's served Flight Plan tab (`managed.yaml`, `font_percent` 0.8)
- `800x480`: the size AER-6156 was filed from
- `649x400`: a short pane

All renders were made offscreen on the Beelink (`10.110.10.241`) with its
`~/pyefis-venv` and system fonts, from a scratch copy of each tree. The live
display was not touched. The bench has no DejaVu Sans Condensed, so the
widget falls back to DejaVu Sans there, as it does on the glass.

To regenerate, from a checkout of each tree:

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python3 \
        tools/render_fpl_message_overlap.py OUTDIR

The tool prints the number of header pixels each message changes. On `dev`
that is 0 at 649x993 (the message wedges under the top line), 137-312 at
800x480 and 98-238 at 649x400, all on the LEG/DIRECT badge. On this branch it
is 0 everywhere. The sheets were composed from `OUTDIR/<size>_0.png` and
`<size>_3.png` of the two runs, side by side with a 16 px grey gap (PIL).
