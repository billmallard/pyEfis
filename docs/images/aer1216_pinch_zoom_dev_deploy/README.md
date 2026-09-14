# AER-1216 -- bench deploy of `dev` after the pinch dead-band / range-ladder-snap fix landed (pyEfis #220, #221)

**Result: `dev` (bench-deployed, not a staged branch) is on the Beelink bench
and rendering cleanly.** This is the follow-up to the earlier staged-branch
capture (`docs/images/aer1216_pinch_zoom_bench/`, PR #221) -- that one showed
the feature branch alone; this one confirms the merged history, including
`#212` and the `#220`/`#221` merge commits, comes up clean as ordinary `dev`
currency with no staging step. It does not, and cannot, prove the pinch
gesture itself feels right on the touchscreen -- that is Bill's on-glass call,
not something a SIGUSR1 capture can stand in for.

Bench: Beelink, `10.110.10.241` (`beelinkpyefis`), plain `bench-deploy.sh`
run (no `--ref`) per `bench_deploy.md`. The checkout was already at `dev`
`1de6bf8` (`Merge pull request #221 from
billmallard/aer-1216/pinch-zoom-deadband-range-ladder`) -- `git pull --ff-only`
reported "Already up to date" for all three checkouts (pyEfis, fix-gateway,
makerplane-data). `fixgw.service` was left alone (fix-gateway did not move).
`pyefis.service` was restarted and came back `active` with no traceback or
missing-screen error in the last 90s of the journal.

## What the capture shows

`bench_render.png` -- SIGUSR1 capture of `gui.mainWindow` (HSI window). The
SVS/AI panel is blank in every such capture (a `QOpenGLWidget`; GL does not
render into an offscreen grab) -- expected, not a fault.

## What this does not show

This is a static grab, not an interaction trace. It cannot demonstrate:
- the pinch dead-band separating zoom/pan/rotate,
- the snap-to-ladder-rung behaviour on release,
- whether the fix *feels* better than before on real touch hardware.

Those are exactly the axes the PR's own test suite pins programmatically
(via `event()`, not by calling `zoom_by`/`rotate_by` directly). This image's
only job is to confirm `dev`, as merged, is the code on the glass for Bill's
feel judgement.
