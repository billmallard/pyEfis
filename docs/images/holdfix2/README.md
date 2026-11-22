# HOLDFIX2 evidence (AER-6322)

Hold at present position, at the Beelink's Flight Plan pane size (649 x 993),
rendered offscreen from the real widget by
`tests/instruments/flight_plan/render_holdfix2_evidence.py`:

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python -m pytest \
        tests/instruments/flight_plan/render_holdfix2_evidence.py --no-cov -q

Route AAA -> BBB (VOR, 50 nm east) -> CCC, MAGVAR 12, ALT 6000. The aircraft
is between AAA and BBB on the AAA -> BBB leg (FPLACTLEG 2), tracking 095
magnetic. The engine is played by hand: after Insert the page sends `ACT 3`,
and frame 3 shows the engine state that follows it (FPLACTLEG 3, FPLPHASE
HOLD). The real engine flying that pair is pinned in
`test_hold_ppos.py::test_the_inserted_pair_loads_on_the_engine_and_activates_into_the_hold`.

| File | What it shows |
|---|---|
| `1_menu.png` | MENU with Hold at PPOS |
| `2_editor_default.png` | The editor as opened: HOLD AT PPOS, inbound 095 (the present track), west side, right turns, 1 min |
| `3_plan_with_ppos_hold.png` | After Insert: AAA, PPOS, PPOS HOLD (active), BBB, CCC, with the "HOLD AT PPOS" toast |
| `4_no_gps_position.png` | Hold at PPOS with LAT old: the editor does not open, the toast says NO GPS POSITION |
