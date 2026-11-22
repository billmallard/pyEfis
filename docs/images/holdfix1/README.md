# HOLDFIX1 evidence (AER-6210)

Hold... on any fix, at the Beelink's Flight Plan pane size (649 x 993),
rendered offscreen from the real widget by
`tests/instruments/flight_plan/render_holdfix1_evidence.py`:

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python -m pytest \
        tests/instruments/flight_plan/render_holdfix1_evidence.py --no-cov -q

Route AAA -> BBB (VOR, 50 nm east) -> CCC, MAGVAR 12, ALT 6000.

| File | What it shows |
|---|---|
| `1_row_menu.png` | BBB's row menu with Hold... |
| `2_editor_default.png` | The editor as opened: hold as you arrive (inbound 102, west side), right turns, 1.0 min |
| `3_radial_keypad.png` | Typing the 130 radial |
| `4_editor_clearance.png` | "Hold southeast of BBB on the 130 radial, left turns, 10-mile legs" |
| `5_plan_with_hold.png` | The plan after Insert: a BBB HOLD row after BBB |
| `6_menu_exit_hold.png` | MENU while the engine reports FPLPHASE HOLD on that slot: Exit hold |

## On the Beelink (2026-11-21, after #534 merged)

Full 1920 x 1080 X11 frames (`ffmpeg -f x11grab`) of the live kiosk. pyEfis is at
`d9f7066d` and fix-gateway at `16282cd`, the plan is KSBA-KSMO, and input is xdotool
taps under the bench lock. There was no position source, so the glass reads NO POS.
I removed the hold at the end, and the plan went back to 24 slots.

| File | What it shows |
|---|---|
| `bench_1_row_menu.png` | VTU's row menu with Hold... |
| `bench_2_editor_default_junction.png` | The editor opened at N / 360. **Defect, fixed in this PR:** VTU follows FLOUT5, which also ends at VTU, so the default saw no leg into the fix |
| `bench_3_clearance.png` | SE, the 130 radial, LEFT, 10 NM: `INBOUND 310°  L TURNS  10 NM` |
| `bench_4_inserted.png` | After Insert, with the "HOLD AT VTU" toast. On the bus, slot 6 is `VTU HM 310.0 10.0 L`, SGI 3 (V485), FLAGS 0, and FPLLDSEQ = FPLSEQ = 69 with no FPLMSG |
| `bench_5_show_fixes.png` | V485's Show Fixes. **Defect, fixed in this PR:** the hold reads as a second plain "VTU" |
| `bench_6_remove_hold.png` | The hold's one-fix menu with Remove Hold |
| `bench_7_removed.png` | After Remove Hold: 24 slots, FPLSEQ = FPLLDSEQ = 70 |
