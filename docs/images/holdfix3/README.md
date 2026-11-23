# HOLDFIX3 "as published" evidence (AER-6328)

The hold editor's PUBLISHED row, at the Beelink's Flight Plan pane size
(649 x 993), rendered offscreen from the real widget by
`tests/instruments/flight_plan/render_holdfix3_evidence.py`:

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python -m pytest \
        tests/instruments/flight_plan/render_holdfix3_evidence.py --no-cov -q

Route AAA -> BBB -> CCC, ALT 6000. The holds at BBB are the five that AIRAC
2611 publishes at BTG (Battle Ground VORTAC), moved onto BBB.

| File | What it shows |
|---|---|
| `1_editor_published_row.png` | The editor as opened: PUBLISHED (5) under the title, fields as before |
| `2_chooser.png` | The list, enroute and arrival holds first |
| `3_enroute_timed_std_time.png` | The ENR HIGH/ENR LOW hold picked: south, inbound 343, right turns, 1 min marked STD TIME in amber |
| `4_star_10nm.png` | The STAR hold picked: 10 NM legs, no STD TIME |
