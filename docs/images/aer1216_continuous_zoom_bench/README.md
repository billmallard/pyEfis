# AER-1216: continuous-zoom fix, staged bench render

This proves the branch deploys cleanly and renders on the Beelink bench --
it is NOT a proof of pinch feel. Whether the gesture itself feels
continuous on the touchscreen is Bill's on-glass call and cannot be stood
in for by a static capture.

## What was done

Bench: Beelink, `10.110.10.241` (`beelinkpyefis`). Staged
`aer-1216/pinch-continuous-zoom` @ `df69c61` via
`bench-deploy.sh --ref aer-1216/pinch-continuous-zoom` per
`makerplane/processes/bench_deploy.md`. `fixgw.service` was left alone
(fix-gateway did not move); `pyefis.service` restarted and came back
`active` with no traceback in the journal.

pyEfis always boots to the mandatory nav-data-currency gate first
(`_ensure_data_status_boot`) regardless of `main.defaultScreen`, and only
proceeds once its `Continue` button is pressed (see AER-1247, PR #224/#225
for the same lesson on the previous deploy of this issue). Dismissed it
with a synthesized click at the button's on-screen coordinates
(`xdotool mousemove 402 971 click 1`, found by masking the button's fill
colour in the raw capture), then re-captured via the normal SIGUSR1 path:

```bash
ssh -i <BEELINK_SSH_KEY> pyefis@10.110.10.241 \
  'DISPLAY=:0 xdotool mousemove 402 971 click 1; sleep 3; kill -USR1 <pid>'
scp -i <BEELINK_SSH_KEY> pyefis@10.110.10.241:/tmp/pyefis_screenshot.png bench_render.png
```

## What the capture shows

`bench_render.png` -- SIGUSR1 capture of `gui.mainWindow`: tapes, VSI, HSI
rose, and the moving map showing KSBA and RZS 114.9 with the range chip
reading "10 NM  NORTH UP  NO POS" (the display-rounding format introduced
in this PR; 10 is already whole so this capture does not exercise the
rounding of a fractional value, only that the new format string renders).
The SVS/AI panel is blank top-left, as expected for every such capture (a
`QOpenGLWidget`; GL does not render into an offscreen grab) -- not a fault.

This confirms the branch boots and paints without error on the bench. It
does not and cannot confirm the pinch feels continuous -- that requires
touching the glass.
