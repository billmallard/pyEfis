# flight_plan bench captures (AER-805)

Real X-session captures from the Beelink pyEfis bench (`bench_deploy.md --ref
aer-805/flightplan-fpl-entry-keypad`), not the offscreen headless harness.
`SIGUSR1`'s screenshot handler is known-broken on this box (grabs the wrong
window / never writes the file), so these were taken directly against the X
display instead:

```bash
# one-time on the bench (passwordless sudo already available):
sudo apt-get install -y xdotool

# per capture, against the live kiosk window (no window manager, single
# fullscreen 1920x1080 X window named "pyefis"):
DISPLAY=:0 xdotool mousemove <x> <y>
DISPLAY=:0 xdotool click 1
ffmpeg -y -f x11grab -video_size 1920x1080 -i :0 -frames:v 1 /tmp/shot.png
```

`flight_plan` occupies the right half of `config/screens/flightplan.yaml`
(screen x 960-1920); keypad/tab/footer tap-target centers were computed from
the widget's own `_paint_*` layout fractions (e.g. keypad row `y = 540 +
row_index*90 + 45`, key `x = 960 + (col_index+0.5)*(960/7)`).

- `fpl_page_empty.png` -- FPL page, no plan (`NO FLT PLAN`, `NO WAYPOINTS`).
- `entry_page_fastfind.png` -- Entry page mid-FastFind: typed `KSBA` against
  the real bench `airports.sqlite`/`navaids.sqlite` packs (`nasr_db_path`/
  `navaid_db_path` in the stock screen), Recent tab showing the prior commit.
- `fpl_page_two_waypoints.png` -- FPL page after committing KSBA and KSMX by
  keypad: real DTK/DIS/CUM (313°/42 nm to KSMX) from `flightplan.geo` against
  the actual airport coordinates.

Not captured: the HSI showing GPS course. The bench has no live position
(X-Plane wasn't feeding LAT/LONG -- the map shows `NO POS`), so there was no
GPS course for the FP2 engine to compute. See the PR body for what this
means for the DoD's HSI item.
