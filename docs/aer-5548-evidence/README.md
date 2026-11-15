# AER-5548 evidence: cyan, opt-in bearing pointers and the BRG tab

`sheet_1x.png`: the HSI at the Pi 5 panel size (432 x 425), CDI on GPS (top row)
and VLOC1 (bottom row). Columns: Off by default, one tap on the BRG tab, two taps,
both pointers on, and the `corners` layout with no tab.
`tab_zoom3x.png`: the BRG tab in each `top_panel` state, nearest-neighbour 3x.

Every state is reached by synthetic taps through the widget's own mouse
handling, and the script asserts what each tap wrote. The NAV flag shows
because the CDI key carries no live signal in this render.

Regenerate (fonts must resolve; DejaVu Sans as on the bench):

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python3 tools/render_hsi_bearing_evidence.py docs/aer-5548-evidence

## Beelink glass (1920x1080, X11)

`beelink_hsi_sheet.png`: the HSI region of nine live x11grab frames from the
Beelink PFD, branch `aer-5548/hsibrg1-cyan-bearing` at 28e7bd58, pyEfis freshly
restarted so both pointers start Off. `beelink_tab_zoom3x.png`: the BRG tab in
the same nine frames, nearest-neighbour 3x. Full frames are in `beelink/`.

`beelink/run.sh` drives it: real X pointer clicks (`xdotool`) on the tab rows,
NAVSRC written with `fixgwc`, and NAVSRC / BRG1SRC / BRG2SRC / COURSE / HEAD
read back from fix-gateway after each frame. `beelink/feed.py` holds a steady
heading, courses, deviations and VOR/GPS bearings over netfix on the select
INPUTS (feeding COURSE directly is overwritten by the gateway's select with
`0.0 Fail`). With no GPS position on the simulator bench, GPS bearing is
invalid, so a GPS pointer shows as `2 GPS X` with no needle.

    # on the Beelink, from ~/bench-scratch/AER-5548 with both files copied there
    systemctl --user restart pyefis.service; sleep 45
    flock -w 900 /tmp/pyefis-bench.lock sh run.sh
