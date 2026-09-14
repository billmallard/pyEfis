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
run (no `--ref`) per `bench_deploy.md`, pulling `dev` to `1dea402` (the merge
of this PR's own predecessor commit, `979dc9c`). `fixgw.service` was left
alone (fix-gateway did not move). `pyefis.service` was restarted and came back
`active` with no traceback or missing-screen error in the last 90s of the
journal.

**Correction (AER-1247):** the render this README originally shipped with
(`979dc9c`) was taken 6s after restart, per `bench-deploy.sh`'s normal
capture timing -- too soon. Since `1a01fc9` (well before #221), pyEfis always
boots to the nav-data-currency screen first (`_ensure_data_status_boot` in
`gui.py`, forced regardless of `main.defaultScreen`), and only proceeds to the
configured default screen once its `Continue` button is pressed. The original
capture landed on that gate, not on `gui.mainWindow` -- a full-screen
NAVIGATION DATA list, no HSI, no tapes, no map. The predecessor capture
(`docs/images/aer1216_pinch_zoom_bench/`, PR #221) apparently had `Continue`
already pressed by the time it was taken; this deploy's automated
post-restart screenshot cannot assume that. The image below replaces it: taken
after synthesizing a click on `Continue` (`xdotool` at the button's on-screen
coordinates) and re-capturing via the same SIGUSR1 path.

## What the capture shows

`bench_render.png` -- SIGUSR1 capture of `gui.mainWindow` (HSI window), taken
after dismissing the mandatory nav-data-currency gate described above. The
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
