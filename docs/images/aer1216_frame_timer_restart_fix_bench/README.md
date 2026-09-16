# AER-1216: gesture frame-timer restart fix, staged bench render

This proves the corrected branch deploys cleanly and renders on the Beelink
bench -- it is NOT a proof of pinch feel. Whether the gesture itself feels
fluid on the touchscreen is Bill's on-glass call.

## Why this evidence exists

Bill, 2026-09-16 (still on `8c8c84d`, the totalScaleFactor fix): "It's still
nearly unusable. It does respond if I'm slow and careful with my movements.
I feel like the commands are there but the screen redraw is so slow the
visual feedback doesn't match what command it's receiving due to the delay."

That is a different defect from the scaleFactor/totalScaleFactor mixup:
`_gesture_phase()` calls `_set_gesture_active(True)` on every single
`GestureUpdated` event, not just the transition into a gesture, and
`_set_gesture_active` unconditionally called `QTimer.start()` -- which
resets an already-running timer's countdown to a full interval (Qt
semantics). A real pinch reports events faster than the ~33ms gesture-clock
tick, so the repaint timer was perpetually restarted before it could ever
fire: input (`range_nm`) was applied instantly but the screen only
repainted during a gap between touch events wider than one tick -- exactly
"commands are there but the screen redraw is so slow." Slow, careful
movement leaves gaps for the timer to sneak a tick in, which is why it
"does respond" when careful.

Fixed in `d0f502b` by guarding the timer restart on an actual
active/inactive transition; once running at the right rate it free-runs on
its own. Pinned by
`test_rapid_pinch_updates_do_not_starve_the_frame_clock` in
`tests/instruments/test_map_frame_clock.py`, which drives GestureUpdated
events through `event()` every 5ms (under the 33ms tick) for 200ms and
requires at least one paint mid-gesture -- confirmed red against
unmodified code (0 paints in the window), green after the fix.

## What was done

Bench: Beelink, `10.110.10.241` (`beelinkpyefis`). Staged
`aer-1216/pinch-continuous-zoom` @ `d0f502b` (up from `8c8c84d`, which had
been staged since the prior round) via
`bench-deploy.sh --ref aer-1216/pinch-continuous-zoom` per
`makerplane/processes/bench_deploy.md`. `fixgw.service` was left alone
(fix-gateway did not move); `pyefis.service` restarted and came back
`active` with no traceback in the journal. Captured via the script's
built-in SIGUSR1 screenshot (`~/bench-deploy-shot.png`, pulled with scp).

## What the capture shows

`bench_render.png` -- SIGUSR1 capture of `gui.mainWindow`: tapes, VSI, HSI
rose, and the moving map. The SVS/AI panel is blank top-left, as expected
for every such capture (a `QOpenGLWidget`; GL does not render into an
offscreen grab) -- not a fault.

This confirms the branch boots and paints without error on the bench. It
does not and cannot confirm the pinch feels fluid -- that requires touching
the glass, and the timer restart is a per-touch-event GUI-thread effect an
offscreen static screenshot cannot exercise. The regression test above is
the evidence for the mechanism; Bill's fingers are the evidence for the feel.

## Regenerate

```bash
ssh -i <BEELINK_SSH_KEY> pyefis@10.110.10.241 'sh -s' \
  < makerplane/processes/paperclip/scripts/bench-deploy.sh -- --ref aer-1216/pinch-continuous-zoom
scp -i <BEELINK_SSH_KEY> pyefis@10.110.10.241:~/bench-deploy-shot.png bench_render.png
```
