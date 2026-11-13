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
