# AER-1216: pinch-zoom scaleFactor-compounding fix, staged bench render

This proves the branch deploys cleanly and renders on the Beelink bench --
it is NOT a proof of pinch feel. Whether the gesture itself feels fluid on
the touchscreen is Bill's on-glass call and cannot be stood in for by a
static capture. What this fix addresses is documented in the commit
message: `QPinchGesture.scaleFactor()` is cumulative since the gesture
started, and the old `event()` handler was compounding that cumulative
value onto the already-zoomed `range_nm` on every update instead of
re-deriving it from a fixed per-gesture baseline -- see
`test_finely_sampled_pinch_does_not_overshoot_from_scaleFactor_compounding`
in `tests/instruments/test_map_pinch_deadband.py` for the reproduction.

## What was done

Bench: Beelink, `10.110.10.241` (`beelinkpyefis`). Staged
`aer-1216/pinch-continuous-zoom` @ `37a6e99` (up from `df69c61`, already
staged from the previous round) via
`bench-deploy.sh --ref aer-1216/pinch-continuous-zoom` per
`makerplane/processes/bench_deploy.md`. `fixgw.service` was left alone
(fix-gateway did not move); `pyefis.service` restarted and came back
`active` with no traceback in the journal. Captured via the script's
built-in SIGUSR1 screenshot (`~/bench-deploy-shot.png`, pulled with scp).

## What the capture shows

`bench_render.png` -- SIGUSR1 capture of `gui.mainWindow`: tapes, VSI, HSI
rose, and the moving map showing KSBA and RZS 114.9 with the range chip
reading "10 NM  NORTH UP  NO POS". The SVS/AI panel is blank top-left, as
expected for every such capture (a `QOpenGLWidget`; GL does not render
into an offscreen grab) -- not a fault.

This confirms the branch boots and paints without error on the bench. It
does not and cannot confirm the pinch feels fluid -- that requires
touching the glass.

## Regenerate

```bash
ssh -i <BEELINK_SSH_KEY> pyefis@10.110.10.241 'sh -s' \
  < makerplane/processes/paperclip/scripts/bench-deploy.sh -- --ref aer-1216/pinch-continuous-zoom
scp -i <BEELINK_SSH_KEY> pyefis@10.110.10.241:~/bench-deploy-shot.png bench_render.png
```
