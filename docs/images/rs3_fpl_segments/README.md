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
