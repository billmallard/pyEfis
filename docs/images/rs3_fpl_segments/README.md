# RS3 FPL page mock: route segments (pyEfis #306, AER-3792)

These are renders of the real `flight_plan` widget's own paint path (not a
drawing of it), at the Beelink Flight Plan tab size (649 x 993 px, 21.5 in
1920 x 1080 panel, `font_percent: 0.8` as served by the bench's managed.yaml).
They were produced on the Beelink itself, so they use the bench's fonts. The
golden route "KSBA GVO V27 AVOLS KSMX" is expanded from the bench's procedures
pack (AIRAC 2610) and published through the real FIX bridge into the mock FIX
db. MAGVAR is -11.6 (11.6 E), so DTK is magnetic.

| File | State |
|---|---|
| `1_summary.png` | active leg KSBA -> GVO; V27 is one segment row |
| `2_in_airway.png` | active leg KWANG -> DEANO; V27 opens into nested working rows, the rest folded |
| `3_segment_menu.png` | tap on the V27 row |
| `4_show_fixes.png` | Show Fixes from that menu |
| `sheet.png` | all four, 1:1, side by side |

Regenerate (on the bench, in a scratch copy of the tree; it does not touch the
live display):

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python3 tools/render_fpl_segments.py OUTDIR \
        --procedures /data/makerplane-data/procedures/current/procedures.sqlite

## Live bench screenshots (Beelink, after Bill accepted the mock)

`bench_*.png` are pyEfis's own SIGUSR1 screenshots of the live Beelink panel
running branch `aer-3792/rs3-fpl-segments` (staged with `bench-deploy.sh
--ref`), cropped to the Flight Plan tab at 1:1. `*_fullscreen.png` are the
uncropped 1920x1080 frames (the SVS panel is blank in a SIGUSR1 grab; that is
expected on the Beelink, a `QOpenGLWidget` does not render into it). The route
was entered on the glass with synthetic taps (`xdotool`): KSBA and GVO from the
entry page, Load Airway V27 exit AVOLS from GVO's row menu, KSMX appended.
Live MAGVAR on the bench was -14.0.

| File | How it was reached |
|---|---|
| `bench_1_summary.png` | GVO row menu > Activate Leg (`FPLACTLEG` 2) |
| `bench_2_in_airway.png` | V27 row > Show Fixes > DEANO > Activate Leg (`FPLACTLEG` 5) |
| `bench_3_segment_menu.png` | tap on the V27 row |
| `bench_4_show_fixes.png` | Show Fixes from that menu |
| `bench_sheet.png` | all four side by side |

On the bus after state 2: `FPLACTLEG 5`, `FPL5ID DEANO`, `FPL5CRS 70.6` (the
page shows 071°), segment 2 = `KIND 1, ID V27, ENT GVO, EXT AVOLS`. X-Plane was
not connected (position keys flagged old), so `FPLCRS` itself was not live.
