# G97 bench evidence (AER-6536, pyEfis #582)

The FPL page on the Beelink bench (X11, 1920x1080), with pyEfis on branch
`aer-6536/g97-activate-refusal-reasons` @ `08a46a50` and fix-gateway `dev` @
`7951638`. The bench was staged with `bench-deploy.sh --ref` and restored to
`dev` afterwards. Each image is the right-hand pane, x 1250-1920 of the full
frame, at 1:1.

- `beelink_activate_leg_refused.png` shows a **real engine refusal**. The
  bench's `LAT`/`LONG` were flagged old, so there was no usable position. On
  the Flight Plan tab, a tap on the KSBA row and then **Activate Leg** sent
  `1 ACT 1`. The engine answered `FPLCMDACK=-1` with `FPLMSG=NO POSITION`
  (read back over netfix), and the strip reads `NO GPS POSITION`. Grabbed
  0.8 s after the tap.
- `beelink_active_leg_notice_injected.png` shows an **injected** notice,
  used to show the wording. With `FPLSEQ == FPLLDSEQ == 70`, netfix wrote
  `@wFPLMSG;ACTIVE LEG REMOVED`. FPLMSG was then restored to its previous
  value (`NO POSITION`). The strip reads
  `ACTIVE WAYPOINT REMOVED: NO LEG ACTIVE`.

Taps were driven by `xdotool` on `:0` under `flock /tmp/pyefis-bench.lock`,
and frames were taken with `ffmpeg -f x11grab -video_size 1920x1080 -i :0
-frames:v 1`:

    xdotool mousemove 1326 10 click 1     # Flight Plan tab
    xdotool mousemove 1400 199 click 1    # KSBA row -> menu
    xdotool mousemove 1584 349 click 1    # Activate Leg

The far-fix Yes and the coded-turn `ACT N/A ...` refusals need a live
position and a coded DF leg. The bench had neither, so those paths are
covered by `tests/instruments/flight_plan/test_activate_refusal.py` only.
They use the same strip and the same handler.
