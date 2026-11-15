# RS4 map: airway labels and active-segment emphasis (pyEfis #307, AER-3793)

pyEfis's own SIGUSR1 screenshots of the live Beelink panel running branch
`aer-3793/rs4-map-airway-labels` (staged with `bench-deploy.sh --ref`). The
moving-map tab is shown at 1:1 (670 x 1045 px of the 1920 x 1080 panel), at
48 NM, north up. `*_fullscreen.png` are the uncropped frames; the SVS panel
is blank in a SIGUSR1 grab, which is expected on the Beelink because a
`QOpenGLWidget` does not render into it. `*_zoom2x.png` are a 520 x 380
region around V27's first legs, scaled 2x nearest-neighbour so line widths
stay countable.

The golden route "KSBA GVO V27 AVOLS KSMX" was expanded from the bench's
procedures pack (AIRAC 2611) and published to the live fix-gateway through
the real FixBridge with `tools/bench_rs4_golden_route.py`. The gateway's
segment table and engine outputs are read back over a raw netfix socket:

    FPLS1: KIND=0 ID=   ENT=KSBA EXT=KSBA  FIRST=1  LAST=1
    FPLS2: KIND=1 ID=V27 ENT=GVO EXT=AVOLS FIRST=2  LAST=12
    FPLS3: KIND=0 ID=   ENT=KSMX EXT=KSMX  FIRST=13 LAST=13

| File | State on the bus | What to look at |
|---|---|---|
| `bench_1_v27_active.png` | `FPLACTLEG 2` (leg to GVO), `FPLACTSEG 2` (V27) | "V27" along GVO -> GOLET, white; V27's legs ahead (GOLET -> KWANG -> ...) drawn 3 px, AVOLS -> KSMX (segment 3) 2 px |
| `bench_2_v27_past.png` | `FPLACTLEG 13` (leg to KSMX), `FPLACTSEG 3` | V27 and its label grey with the rest of the past route; no emphasis on V27 |
| `bench_sheet_zoom2x.png` | both, 2x | side by side |

Measured on `bench_1_v27_active_fullscreen.png` (white coverage across the
line, corrected for the leg's angle): GOLET -> KWANG 3.0 to 3.3 px, AVOLS ->
KSMX 2.0 to 2.3 px.

X-Plane was not connected, so the position keys were stale ("NO POS") and
the engine published no FROM/TO point. That is why the active leg itself
(KSBA -> GVO, then AVOLS -> KSMX) is not drawn magenta in either frame. It
was the same before RS4; RS4 does not touch the active leg.

Regenerate (on the bench; the tool saves nothing about the active-leg or
direct-to state, so note the bus first):

    cd ~/src/pyEfis
    QT_QPA_PLATFORM=offscreen ~/pyefis-venv/bin/python -u tools/bench_rs4_golden_route.py \
        --procedures /data/makerplane-data/procedures/current/procedures.sqlite \
        --save OLD.json --act GVO        # then --act KSMX for state 2
    # map tab, 7 wheel-down notches over the map (10 NM -> 48 NM):
    DISPLAY=:0 xdotool mousemove 1580 600 click --repeat 7 --delay 200 5
    kill -USR1 <pyefis pid>              # -> /tmp/pyefis_screenshot.png
    QT_QPA_PLATFORM=offscreen ~/pyefis-venv/bin/python -u tools/bench_rs4_golden_route.py --restore OLD.json
