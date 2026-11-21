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
