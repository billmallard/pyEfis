# AER-1216: totalScaleFactor() correction, staged bench render

This proves the corrected branch deploys cleanly and renders on the Beelink
bench -- it is NOT a proof of pinch feel. Whether the gesture itself feels
fluid on the touchscreen is Bill's on-glass call. What this fix addresses is
documented in the commit message (`8c8c84d`): the prior commit (`37a6e99`)
fed `g.scaleFactor()` into a formula that requires the cumulative
since-gesture-start value, which is actually `g.totalScaleFactor()` --
`scaleFactor()` is the delta since the *last* event. Feeding the per-event
delta into that formula left `range_nm` nearly frozen (a synthesized 2x
zoom-out moved it from 10.0 to 9.99, not 5.0), which reads on the glass as
"no improvement" -- see
`test_pinch_zoom_uses_totalScaleFactor_not_per_event_scaleFactor` in
`tests/instruments/test_map_pinch_deadband.py` for the reproduction.

## Why this evidence exists

Before this fix, the bench (`10.110.10.241`) was staged at `37a6e99` --
the broken commit -- when Bill reported "no improvement." He was right:
that commit did nothing observable to the actual gesture, and the bench
had not yet been moved off it. This capture confirms the bench is now on
the corrected commit and still boots and paints without error.

## What was done

Bench: Beelink, `10.110.10.241` (`beelinkpyefis`). Staged
`aer-1216/pinch-continuous-zoom` @ `8c8c84d` (up from `37a6e99`, which had
been staged since the prior round) via
`bench-deploy.sh --ref aer-1216/pinch-continuous-zoom` per
`makerplane/processes/bench_deploy.md`. `fixgw.service` was left alone
(fix-gateway did not move); `pyefis.service` restarted and came back
`active` with no traceback in the journal. Captured via the script's
built-in SIGUSR1 screenshot (`~/bench-deploy-shot.png`, pulled with scp).

## What the capture shows

`bench_render.png` -- SIGUSR1 capture of `gui.mainWindow`: tapes, VSI, HSI
rose, and the moving map at 2.1 NM showing coastline and water. The SVS/AI
panel is blank top-left, as expected for every such capture (a
`QOpenGLWidget`; GL does not render into an offscreen grab) -- not a fault.

This confirms the branch boots and paints without error on the bench. It
does not and cannot confirm the pinch feels fluid -- that requires
touching the glass.

## Regenerate

```bash
ssh -i <BEELINK_SSH_KEY> pyefis@10.110.10.241 'sh -s' \
  < makerplane/processes/paperclip/scripts/bench-deploy.sh -- --ref aer-1216/pinch-continuous-zoom
scp -i <BEELINK_SSH_KEY> pyefis@10.110.10.241:~/bench-deploy-shot.png bench_render.png
```
