# G43 bench evidence: the Direct To prompt clears once it is answered (#326)

Screens from the Beelink bench (pyEfis `e2ff017` on
`aer-4321/dto-message-clear`, fix-gateway `b15055e`, 2026-10-31), 1920x1080
kiosk, `x11grab`, scaled to 1280 wide and saved as JPEG.

- `after_1_select_a_waypoint.jpg`: Direct To page, Waypoint tab, ACTIVATE
  tapped with nothing selected. The SELECT A WAYPOINT prompt shows, as it
  should.
- `after_2_dto_rzs_active_fplpage.jpg`: then R, Z, ENT (FastFind RZS). The
  page returns to the FPL page with `DIRECT` in the header (`FPLSTATE` 2) and
  no prompt.
- `before_after_fpl_header_2x.png`: right-panel header, 2x nearest-neighbour.
  Left: FP8 `s1_dto_rzs_active_fplpage.jpg` (`dev` @ 1e11b62, before the fix),
  the prompt drawn over the FPL header after the direct-to went active. Right:
  the same moment on this branch. The FP8 frame had the KSBA-KSMX plan loaded;
  this run had no plan, which is why the header reads NO FLT PLAN.

The bus values at each grab are in `data/keys.log`.

## How it was run

X-Plane was idle, so `bench_scripts/dto_prompt.py` feeds a static position
near KSBA over netfix at 2 Hz while it drives the panel with `xdotool`. It
snapshots and restores the position keys.

```
scp bench_scripts/{nfx.py,dto_prompt.py} pyefis@<beelink>:bench-scratch/
ssh pyefis@<beelink> 'cd bench-scratch && \
  flock -w 900 /tmp/pyefis-bench.lock ~/pyefis-venv/bin/python dto_prompt.py aer4321/run1'
```

Notes:

- The panel repaints a few seconds behind the taps, so the grab taken right
  after ENT (`4_` in `keys.log`) still shows the Direct To page while the bus
  already reads `FPLSTATE` 2. The grab 3 s later (`5_`) is the one used here.
- The script's cleanup taps Remove on the Direct To page (DTOX). With no
  plan loaded the gateway rejects that (`FPLCMDACK` -3, `FPLMSG` NO PLAN), so
  the direct-to stayed active. `bench_scripts/reset_plan.py` republished the
  empty plan with `FPLSEQ`+1, which drops the activation (`FPLSTATE` 0). That
  rejection is a gateway behaviour, not part of this change.
