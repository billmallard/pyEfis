# AER-1216 -- bench stage of the pinch dead-band / range-ladder-snap fix (pyEfis #220)

**Result: the branch (`aer-1216/pinch-zoom-deadband-range-ladder` @ `59da31e`)
is staged on the Beelink bench and rendering cleanly.** This proves the code
runs on target hardware; it does not, and cannot, prove the pinch gesture
itself feels right -- that is a live touch interaction on the touchscreen,
and per the issue is Bill's on-glass call alone, not something a SIGUSR1
capture can stand in for.

Bench: Beelink, `10.110.10.241` (`beelinkpyefis`), pyEfis checkout staged via
`bench-deploy.sh --ref aer-1216/pinch-zoom-deadband-range-ladder`. The prior
occupant of the bench, `aer-1149/wide-water-cliff` (#212), had merged and was
gone upstream (exit code 6, "branch gone upstream"), so the checkout was
restored to `dev` @ `6787c3b` first and then re-staged onto this branch, per
`bench_deploy.md`'s exit-code table.

`pyefis.service` came back `active` with no traceback or missing-screen error
in the journal. `fixgw.service` was left alone (fix-gateway did not move).

## What the capture shows

`bench_render.png` -- SIGUSR1 capture of `gui.mainWindow` (HSI window),
showing the moving-map tab at 10 NM range with the range ring and label
rendering normally. The SVS/AI panel is blank in every such capture (a
`QOpenGLWidget`; GL does not render into an offscreen grab) -- expected, not
a fault.

## What this does not show

This is a static grab, not an interaction trace. It cannot demonstrate:
- the pinch dead-band separating zoom/pan/rotate,
- the snap-to-ladder-rung behaviour on release,
- whether the fix *feels* better than before on real touch hardware.

Those are exactly the axes the PR's own test suite pins programmatically
(via `event()`, not by calling `zoom_by`/`rotate_by` directly -- see the PR
body); this image's only job is to confirm the branch is the one on the
glass for Bill's feel judgement.
