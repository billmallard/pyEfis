# AER-5847 evidence: the one-button BRG tab (HSIBRG4)

`sheet_1x.png`: the HSI at the Pi 5 panel size (432 x 425), both bearing pointers
available. Rows: CDI on GPS, VLOC1, VLOC2. Columns: each state the BRG tab offers
for that source, reached by synthetic taps on the tab from NONE, then the `corners`
layout (no top panel, so the corner labels `1 OFF` / `2 OFF` carry the tap). The
CDI on VLOC1 offers only NONE and BRG 2, and on VLOC2 only NONE and BRG 1, so those
rows have two tab columns. In `corners`, a pointer that would repeat the CDI shows no
`OFF` label.

`tabs_zoom3x.png`: the source tab, the HDG | MAG | CRS panel and the BRG tab in one
crop for every tab state, nearest-neighbour 3x, so the matching size shows.

The script asserts every state it draws: the tab label, which pointers are on, that
each one's `BRGnSRC` is its own VOR (never GPS, never the CDI's source), and that the
BRG tab is the source tab mirrored about the panel's centre line. It printed, at the
432 x 425 size, for all eight tab states:

    source tab x=62.75 y=15.65 w=59.50 h=36.69 | BRG tab x=309.75 y=15.65 w=59.50 h=36.69
    insets from centre 153.25 / 153.25

The NAV flag shows because the CDI key carries no live signal in this render. Fonts:
DejaVu Sans (DejaVu Sans Condensed is not installed here or on the bench).

Regenerate:

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python3 tools/render_hsi_bearing_evidence.py docs/aer-5847-evidence
