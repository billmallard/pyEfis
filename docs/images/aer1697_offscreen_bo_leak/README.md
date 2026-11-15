# AER-1697 -- offscreen `svs_capture.py`'s per-tick GPU BO leak, Pi 5 bench evidence

No image in this directory: the repro pose never actually reached the readback
step (see "A second, separate finding" below), so there is no captured frame
to show. The evidence here is the V3D driver's own buffer-object accounting,
not a picture.

## Repro pose

The AER-1789-bisected pose (its own live-display test, comment 2026-09-20):
range 20, 8000 ft, high Colorado relief -- the one entry in that issue's
four-probe bisection table that segfaulted, at 33 s.

```
--lat 39.20 --lon -106.85 --alt 8000 --heading 150 --range 20 --width 800 --height 600
```

## Instrument: V3D's own BO accounting, not inference

The Pi 5's V3D driver exposes live buffer-object counts with no root needed:

```
cat /sys/kernel/debug/dri/1002000000.v3d/bo_stats
allocated bos:          64
allocated bo size (kb): 149712
```

That is the whole measurement method used below: sample this file every
0.5 s while `svs_capture.py --offscreen` runs, concurrently with
`pyefis.service` holding the display. `pyefis.service`'s own steady-state
baseline (64 BOs, ~146 MB) is what "allocated bos" reads with nothing else
running.

## Before the fix: unbounded, ~120 new BOs every tick

```
t_s   bo_count  bo_size_kb  rss_kb   (capture process still running throughout)
0.5   83        155296      143888
1.0   513       216496      433072
1.6   4388      278496      440608
2.1   8167      338960      440672
2.6   12020     400608      440720
3.1   15818     461216      440736
3.6   19598     522720      440752
4.1   23426     583408      440752
```

Between t=1.0s and t=4.1s (194 ticks at 16ms): `bo_count` grew 513 -> 23426
(+22913, **118 BOs/tick**), `bo_size_kb` grew 216496 -> 583408
(+366912 kb, **1.85 MB/tick**). This run was deliberately killed at the 4.1s
sample by a safety monitor (400 MB growth cutoff -- see "Bench hygiene")
before it could repeat the board reboot AER-1692 already hit once; the trend
through that point is already unambiguous.

**Note the RSS column plateaus at ~440 MB by t=1.0s while `bo_count`/
`bo_size_kb` keep climbing for the rest of the run.** These BOs are
kernel/driver-tracked GPU memory, not memory mapped into the capture
process's own address space -- which is exactly why `free -h` / a process
RSS check would never have caught this: the growth is invisible to every
signal except the driver's own debugfs counters.

Extrapolating 1.85 MB/tick from a ~150-215 MB working set to the point a
finite pool exhausts lands in the same ballpark as AER-1789's independently
observed **33 s to crash** on this exact pose -- consistent with one
mechanism, not two.

## Root cause

`render_offscreen_frame()` paints into a `QOpenGLFramebufferObject` that is
never presented through `eglSwapBuffers` -- there is no window, and
`QOffscreenSurface` has no swap chain. A live, windowed `QOpenGLWidget` (the
path `pyefis.service` itself uses) gets a frame boundary for free from Qt's
own swap-on-repaint; this path never asks for one. Without it, the V3D kernel
driver has no signal to reclaim the per-submission scratch/binning BOs each
draw call allocates, so `pump()`'s 16ms tick loop -- which calls
`render_offscreen_frame()` on every tick while waiting for `settled()` --
leaks a small, unbounded amount of GPU memory every single tick, regardless
of how long the scene takes to settle.

## Fix and after-fix numbers: flat, not bounded

One line: `gl.glFinish()` after `painter.end()`, so every offscreen frame
gets an explicit completion/reclaim point in place of the swap boundary this
path doesn't have.

```
t_s    bo_count  bo_size_kb  rss_kb
0.5    83        155296      147520
1.0    213       211696      438208
1.5    216       211744      440368
2.0    216       211744      440384
...    (flat)    (flat)      (flat)
17.5   214       211552      440592
18.1   214       211552      440576
```

`bo_count`/`bo_size_kb` settle to a steady state (~215 BOs, ~212 MB -- a
one-time cost for this pose's heightmap/atlas/vertex-buffer set, all
guarded/cached elsewhere in `svs_gl.py`) within the first ~60 ticks and stay
exactly flat for the rest of an 18 s (1125-tick) run. A second run with the
monitor's cap raised to 45 s (see "A second, separate finding") stayed flat
through 1290+ ticks. Removing the `gl.glFinish()` call and re-running
reproduces the original unbounded-growth trend exactly (see the regression
test below) -- confirms the fix, not just correlation with a quiet run.

`pyefis.service`'s `MainPID`/`NRestarts` were unchanged across every run in
this session (before-fix, after-fix, and the regression-test check) --
`pyefis.service` never touches the second GL context at all, and was never
implicated by AER-1789's own live-display test either.

## Leak, not threshold

Both parts of the issue's ask are answered directly by the two tables above:
growth is **linear in tick count** (not a step at some fixed tick), and it is
**unbounded** absent the flush (not capped by any cache or pool the code
already has) -- a leak, not a one-time cost that happens to be expensive.

## Regression test

`tests/tools/test_svs_capture.py::test_render_offscreen_frame_flushes_gl_every_call`
mocks the GL context/FBO (no real GPU in the sandbox this suite normally
runs in -- see the module's existing docstring) and asserts `glFinish()` is
called once per `render_offscreen_frame()` call. Verified both ways on this
bench, in the venv actually used for the fix (not a separate/parallel
environment): passes with the fix in place, and fails
(`AssertionError: assert 0 == 3`) with `gl.glFinish()` deleted -- confirming
it actually pins the invariant rather than passing vacuously.

## A second, separate finding: this pose does not settle at all within 60 s

Independent of the leak, this exact pose's `settled()` check never resolves
-- a 60 s run (with the leak fixed, so this is not GPU exhaustion) exited
`EXIT_NOT_SETTLED`. `--verbose` reports `layers: ['airports', 'obstacles']`
for this pose (water is configured but not in `expect_layers`, so it isn't
the cause). AER-1789's "33 s to crash" was time-to-crash under the leak, not
time-to-settle -- the scene may never have been on track to settle at all,
independent of the GPU issue this row was opened for. Not chased further
here: this row's own scope is the GPU allocation, and conflating a second,
different collector-level defect into this fix would muddy which change
caused which observed effect. Filed as its own follow-up.

## Bench hygiene

- All commands ran against a **separate scratch checkout**
  (`~/bench-scratch/aer1697-repro`), never `~/pyEfis` -- `pyefis.service`'s
  own checkout and its running process were never touched, restarted, or
  stopped at any point in this session.
- Every capture-driving command ran under
  `flock -w 900 /tmp/pyefis-bench.lock`, per the bench-deploy contract.
- `pytest`/`pytest-qt`/`pytest-cov` were installed into `~/pyEfis/.venv`
  (the only Python on this box with a working PyQt6 + eglfs GL stack) to run
  the regression test on real hardware; all three (plus their pulled-in
  deps: `iniconfig`, `pluggy`, `coverage`) were uninstalled again
  immediately after, confirmed via `pip list` against the pre-session
  baseline (`numpy`, `PyQt5`/`PyQt6`, `types-pytest-lazy-fixture` only).
- Every run that drove the leaking (before-fix) code path was wrapped in a
  monitor that kills the capture process on >400 MB BO growth over baseline
  or any `Failed to allocate device memory for BO` line in `dmesg`, well
  under the historical crash point -- this session did not reproduce the
  board reboot, by design.
- `/tmp/aer1697_repro.png` (never produced -- see "second finding" above)
  and all scratch output under `~/bench-scratch/aer1697_repro_out/` were
  removed; the scratch checkout (`~/bench-scratch/aer1697-repro`) itself was
  left in place (a plain `git clone`, cheap to keep or delete, on the fix
  branch with a clean tree) rather than deleted, matching how the AER-1631
  session's own scratch state was handled.
- `pyefis.service` confirmed `active`, `NRestarts=0`, unchanged `MainPID`
  throughout the entire session, checked before and after every run.
