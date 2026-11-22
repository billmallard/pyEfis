# AFC5 evidence: flight director command bars (AER-6052)

Offscreen renders of the real `AI` widget (QPainter on a QImage, `widget.grab()`),
driven from the in-memory FIX database (`tests/mock_db`). No SVS terrain: these are
not GL captures and not the live glass. The Pi 5 GL capture sheet is a separate
step, in the combined review with AFC4.

- `styles.png`: one row per style and aircraft symbol (single_cue and
  cross_pointer, on the classic and the garmin symbol), one column per command:
  satisfied, a climb command, a right-bank command, and a combined command. The
  cue shows command minus attitude: flying the command puts the symbol in it.
- `replay.png`: a real X-Plane flight replayed into the widget. Top row
  single_cue, bottom row cross_pointer. The bus is
  `tests/instruments/ai/data/afc2_bf3a33402db4_fd_bus.csv.gz`, a slice of the
  fix-gateway bus log of sim-bench session bf3a33402db4 (X-Plane 12.4.3, Laminar
  C172 G1000, 2026-11-18, the AFC2 run, AER-5806). Each caption gives the session
  time, the active modes and the FD and attitude values. The autopilot was flying,
  so the aircraft holds the command and the bars sit close to the symbol; the
  climb command at VS engage (t=44 s) shows them lead it. The last frame is 0.3 s
  after the FD keys went old (X-Plane paused after the disconnect): the bars are
  gone and the attitude greys.

The same flight is the test `test_real_flight_bars_follow_the_command_and_go_when_stale`:
every 0.25 s it checks the bars are drawn exactly when FDENG is on and every input
is fresh (679 frames drawn, 35 with the FD off, 4 after the keys went stale), at
command minus attitude.

Regenerate from the repo root (fonts: DejaVu Sans):

```sh
QT_QPA_PLATFORM=offscreen python3 docs/aer-6052-evidence/render.py
```
