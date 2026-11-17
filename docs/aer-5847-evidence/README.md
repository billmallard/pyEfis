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

## Beelink glass (1920 x 1080, X11)

`beelink_hsi_sheet.png`: the HSI region of eleven live x11grab frames from the Beelink
PFD, branch `aer-5847/hsibrg4-brg-cycle` at a644c3e5 (`~/src/pyEfis`, stamped by the
run), staged with `bench-deploy.sh --ref` so pyEfis restarted with both pointers Off.
In order: the CDI on GPS stepped NONE, BRG 1, BRG 2, BOTH; NAVSRC to VLOC1, where BOTH
drops to BRG 2; taps NONE, BRG 2, NONE; BRG 2 on, then NAVSRC to VLOC2, where it drops
to NONE; taps BRG 1, NONE. `beelink_tabs_zoom3x.png`: both tabs and the panel from six
of those frames, nearest-neighbour 3x. Full frames are in `beelink/`. The pointer in the
first frame is left over from an earlier run's probe; every tap after it moves the
pointer away before the grab.

Measured on the glass (`beelink/make_sheets.py`, frame `gps_3_both`): the source tab's
fill spans x 475-534 (60 px), y 653-686; the BRG tab's fill spans x 724-783 (60 px), y
653-687. Each tab's outer edge is 154 px from the panel's centre line.

`beelink/run.sh` drives it: real X pointer clicks (`xdotool`) on the tab at (753, 669),
NAVSRC written with `fixgwc`, and NAVSRC / BRG1SRC / BRG2SRC / BRG1 / BRG2 / HEAD read
back from fix-gateway beside each frame (`beelink/run.log`). The readbacks show the taps
reached the gateway: BRG1SRC went from GPS (2.0) to VOR1 (0.0) on the first BRG 1, and
BRG2SRC from VOR1 (0.0) to VOR2 (1.0) on the first BRG 2. GPS was never written. The
script saved NAVSRC, BRG1SRC, BRG2SRC, GPSSRC, NAV1CRS and NAV2CRS first and put them
back after. `beelink/feed.py` (from AER-5548) holds the heading, courses, deviations and
VOR bearings steady over netfix on the select inputs. Three pairs of frames are
byte-identical, and each pair shows the same state reached twice (VLOC1 NONE, VLOC1
BRG 2, VLOC2 NONE).

    # on the Beelink, from ~/bench-scratch/AER-5847 with run.sh and feed.py copied there
    flock -w 900 /tmp/pyefis-bench.lock sh ./run.sh
    # then, in the repo root, with the frames copied into docs/aer-5847-evidence/beelink/
    QT_QPA_PLATFORM=offscreen python3 docs/aer-5847-evidence/beelink/make_sheets.py
