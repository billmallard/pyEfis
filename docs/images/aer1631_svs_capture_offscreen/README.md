# AER-1631 -- offscreen `svs_capture.py` repair, Pi 5 bench evidence

**Update (2026-09-20, AER-1785): `windowed_1920x1200.png` was not a control
-- it was never regenerated with the AER-1692 fix, and a live windowed-path
defect was hiding behind that gap.** `adbac1a6` (AER-1692) regenerated
`offscreen_1920x1200.png` and its siblings but left `windowed_1920x1200.png`
byte-identical to its pre-fix (`428ba48`) version -- the "Re-captured and
verified. All three frames..." claim two paragraphs below was true of the
code, not of what got committed. Two arms minted at different revisions
aren't a control pair: a pixel difference between them can't be attributed to
the capture path, which is the entire point of keeping this pair.

Recapturing `windowed_1920x1200.png` at #245's merged tip (`5fbd78d`, same
pose, same command) reproduced the exact same bytes as the stale file --
ruling out simple staleness. The windowed path has its own live defect,
independent of AER-1692's `centerOn()`/`viewport()` fix:
`AI.resizeEvent`'s `if self.bankAngleRadius is None:` guard
(`ai_widget.py`) computes the bank cluster's radius from `self.height()`
only on the FIRST resizeEvent a widget ever gets. A windowed top-level on
eglfs (no window manager) receives exactly two -- one at the requested
`--width`/`--height`, a second when the platform forces the window
fullscreen -- so the radius froze at the pre-fullscreen height (600, giving
radius 200) instead of the real one (1200, radius 400). The offscreen path
never showed this because `resize_for_offscreen_capture` delivers exactly
one manual resizeEvent, already at the final size.

Fixed by making `bankAngleRadius` a property: an explicit YAML/config
override (screenbuilder's plain `setattr`) marks the value explicit and is
never touched again; the auto-calculated default recomputes on every
resize instead of latching after the first. `windowed_1920x1200.png` below
is regenerated from that fix (`e89c9c1`, same pose, same bench, same
command) and is now **byte-identical** to `offscreen_1920x1200.png` --
confirming both paths agree exactly once the windowed-side defect is gone.
See the code + a regression test (`test_ai_bank_angle_radius_tracks_
latest_resize`, `tests/instruments/ai/test_ai.py`) on branch
`aer-1785/windowed-bank-radius-stale`.

```bash
systemctl --user stop pyefis.service
cd ~/pyEfis && git checkout aer-1785/windowed-bank-radius-stale
export QT_QPA_PLATFORM=eglfs
export QT_QPA_EGLFS_KMS_CONFIG=/home/wpballard/eglfs_hdmi.json
export PYTHONPATH=src:tests
.venv/bin/python tools/svs_capture.py \
  --lat 34.4275 --lon -119.8546 --alt 500 --heading 87 --range 8 \
  --width 800 --height 600 \
  --tiles /data/makerplane-data/terrain/tiles \
  --water /data/makerplane-data/water/current/water.sqlite \
  --nasr /data/makerplane-data/airports/airports-canada/2026.06/airports.sqlite \
  --dof /data/makerplane-data/obstacles/current/obstacles.sqlite \
  --out /tmp/aer1785_windowed_1920x1200.png --timeout 20 --verbose
# captured, exit 0, 1920x1200, pyefis_rev e89c9c1 (clean, no -dirty)
git checkout dev
systemctl --user reset-failed pyefis.service
systemctl --user restart pyefis.service
```

`pyefis.service` was `active`/`NRestarts=0` before and after (new `MainPID`
after the restart), same hygiene as every other capture in this file. The
bench was left back on `dev` @ `5fbd78d`, exactly where it started.

**Second update, same day: the committed frame could not name its own
revision, so it was re-run with the sidecar committed too.** The diff above
committed `windowed_1920x1200.png` and a README paragraph asserting
`pyefis_rev: e89c9c1`, but not the `<out>.json` sidecar AER-1675
(`859c6b9`, landed three commits before this branch's base) writes
alongside every successful capture -- so the artifact itself carried no
information distinguishing "recaptured on the bench" from "copied from the
offscreen sibling it now matches byte-for-byte." Re-ran the same command at
this branch's then-head (`5bb6e90`, the PR body/README commit -- no code
changed since `e89c9c1`, so this reproduces rather than retests the fix):

```bash
systemctl --user stop pyefis.service
cd ~/pyEfis && git pull --ff-only   # e89c9c1 -> 5bb6e90
export QT_QPA_PLATFORM=eglfs
export QT_QPA_EGLFS_KMS_CONFIG=/home/wpballard/eglfs_hdmi.json
export PYTHONPATH=src:tests
.venv/bin/python tools/svs_capture.py \
  --lat 34.4275 --lon -119.8546 --alt 500 --heading 87 --range 8 \
  --width 800 --height 600 \
  --tiles /data/makerplane-data/terrain/tiles \
  --water /data/makerplane-data/water/current/water.sqlite \
  --nasr /data/makerplane-data/airports/airports-canada/2026.06/airports.sqlite \
  --dof /data/makerplane-data/obstacles/current/obstacles.sqlite \
  --out /tmp/aer1785_windowed_1920x1200.png --timeout 20 --verbose
# captured, exit 0, 1920x1200, rev 5bb6e90 (clean, no -dirty)
systemctl --user reset-failed pyefis.service
systemctl --user restart pyefis.service
```

`sha256sum` of the fresh `/tmp/aer1785_windowed_1920x1200.png` matches the
already-committed `windowed_1920x1200.png` and `offscreen_1920x1200.png`
exactly (`ebc2afa2...fab926`, all three) -- **the second, independent
capture reproduces the first rather than averaging away a fluke.** Both the
PNG and its capture-written `.json` sidecar
(`windowed_1920x1200.png.json`, `{"pyefis_rev": "5bb6e90"}`) are committed
here from this run's own `/tmp` output, not hand-typed. `pyefis.service`
was `active`/`NRestarts=0` before and after; bench left on `dev` @ `5fbd78d`.

**On `sidebyside_full_1920x1200.png` and `horizon_align_crop_zoom3x.png`:
deleted, not regenerated.** Both were pixel-diff visualizations built
against the stale (pre-`e89c9c1`) windowed frame, back when offscreen and
windowed disagreed by 0.09% of pixels (anti-aliasing noise around the bank
arc). Now that the two paths are confirmed byte-identical -- twice, at
`e89c9c1` and again at `5bb6e90` -- a diff panel between them is a blank
image and a 3x crop is two copies of the same pixels stacked: neither has
a job left to do. Regenerating them would cost a bench session to produce
evidence of nothing. If a future defect reopens a visible offscreen/
windowed gap, a fresh comparison render at that point will actually show
something; these two are retired rather than carried forward as
permanently-blank placeholders.

**Update (2026-09-19, AER-1692): the frames above were geometrically wrong,
now fixed.** INTEGRATOR's review of #245 at head `428ba48` measured the
committed `offscreen_*.png` frames against `windowed_1920x1200.png` and found
the AI overlay (horizon line, pitch ladder, bank cluster) composited about a
fixed centre row of ~240px, regardless of the requested `--width`/`--height`
-- 360 rows above the true centre of a 1200-tall capture. The "How closely
they agree" section below, from the first AER-1631 session, attributed the
resulting disagreement to sky colour (an FBO/`QOpenGLWidget` surface-format
or sRGB difference); that hypothesis did not survive the actual measurements
-- a colour difference cannot displace a horizon line by 360 rows.

**Root cause.** `AI.redraw()`'s `centerOn()` call (`ai_widget.py`) positions
the scene using `self.viewport().width()/height()` -- not the outer `AI`
widget's own size, which `resizeEvent` already reads correctly via
`self.height()`. The `--offscreen` path resizes the outer widget with
`widget.resize(...)`, then delivers the resize by calling
`widget.resizeEvent(...)` directly as a plain Python method (AER-1631,
deliberately, since this widget is never shown). That direct call reaches
`AI`'s own resize logic but skips `QAbstractScrollArea`'s Resize-event
handling -- the code that keeps the internal `viewport()` child widget's size
in step with the view. Left untouched, that viewport stays at whatever size
it had when `set_svs_config()` installed it, so `centerOn()` centres every
capture on that fixed (wrong) point regardless of the requested capture size.

**The fix that didn't work, and why.** `set_svs_config()` installs a live
`QOpenGLWidget` as this view's viewport, for the windowed path's native-GL
terrain painting -- exactly the DRM/GPU resource `--offscreen` exists to
never touch (`render_offscreen_frame()` paints through its own, separate
`QOffscreenSurface`/FBO and never touches `viewport()` at all). The first fix
attempted here called `widget.viewport().resize(...)` directly on that live
GL widget to correct `centerOn()`'s input. On the Pi 5 bench, under `eglfs`
with `pyefis.service` already holding DRM master, that resize made Qt attempt
to realise the GL widget's native surface; repeated every `pump()` tick, it
spammed `MESA: error: Failed to allocate device memory for BO` and, once,
crashed the whole board hard enough to need a reboot -- not just the capture
process. **The shipped fix instead swaps `viewport()` for a plain, inert
`QWidget()` before resizing** -- `centerOn()`/`render()`'s viewport-size
dependency only needs the *size* to be right, never the paint capability,
since this path never shows or paints through it either way. A plain
`QWidget` resize touches no DRM/GPU resource.

**Re-captured and verified.** All three frames in this directory (`offscreen_
1920x1200.png`, `offscreen_concurrent_800x600.png`, `windowed_1920x1200.png`)
are re-captured with the fix, same pose as the original session. The
artificial horizon now lands on row 599 of 1200 (offscreen) and row 599 of
1200 (windowed) -- exact agreement -- and on row 299 of 600 in the 800x600
offscreen capture, confirming it now scales with the requested height rather
than sitting at a fixed absolute row. See the corrected "How closely they
agree" section below (in place of the superseded sky-colour hypothesis) and
`horizon_align_crop_zoom3x.png` (replacing the retired `sky_diff_crop_zoom3x.
png`, whose sky-colour framing no longer matches what the data shows).

**A stale path, not a bench defect.** The exact commands below use
`--dof .../obstacles/260611/obstacles.sqlite`, which no longer exists --
`makerplane-data`'s obstacle cycle has since rolled to `260806`, exposed via
a `current` symlink. Using the stale path (copied verbatim from this
document) made the DOF collector never key, so `settled()` waited forever,
`pump()` looped far longer than the ~1-2s a normal capture takes, and *that*
-- not the code fix -- is what reproduced the same `Failed to allocate device
memory for BO` crash signature independent of the viewport question above.
The lesson: point `--dof` (and, if `makerplane-data` follows the same
pattern, `--nasr`) at the `current` symlink rather than a dated snapshot
directory copied from an old command. With a live path, both offscreen
captures above settled and exited in under 2 seconds each.

### AER-1692 exact commands

Same pose and bench as the second session below, `--dof` corrected to the
`current` symlink. Concurrent offscreen, `pyefis.service` active throughout
(`MainPID`/`NRestarts` unchanged before and after both captures):

```bash
cd ~/pyEfis
export QT_QPA_PLATFORM=eglfs
export QT_QPA_EGLFS_KMS_CONFIG=/home/wpballard/eglfs_hdmi.json
export PYTHONPATH=src:tests
.venv/bin/python tools/svs_capture.py --offscreen \
  --lat 34.4275 --lon -119.8546 --alt 500 --heading 87 --range 8 \
  --width 800 --height 600 \
  --tiles /data/makerplane-data/terrain/tiles \
  --water /data/makerplane-data/water/current/water.sqlite \
  --nasr /data/makerplane-data/airports/airports-canada/2026.06/airports.sqlite \
  --dof /data/makerplane-data/obstacles/current/obstacles.sqlite \
  --out /tmp/aer1692_fixed_800x600.png --timeout 20 --verbose
# captured /tmp/aer1692_fixed_800x600.png, exit 0, real 0m1.323s

# same command, --width 1920 --height 1200, --out .../aer1692_fixed_1920x1200.png
# captured, exit 0, real 0m1.731s
```

Windowed comparison (`pyefis.service` stopped first, restarted immediately
after, same as the second session's convention):

```bash
systemctl --user stop pyefis.service
cd ~/pyEfis
export QT_QPA_PLATFORM=eglfs
export QT_QPA_EGLFS_KMS_CONFIG=/home/wpballard/eglfs_hdmi.json
export PYTHONPATH=src:tests
.venv/bin/python tools/svs_capture.py \
  --lat 34.4275 --lon -119.8546 --alt 500 --heading 87 --range 8 \
  --width 800 --height 600 \
  --tiles /data/makerplane-data/terrain/tiles \
  --water /data/makerplane-data/water/current/water.sqlite \
  --nasr /data/makerplane-data/airports/airports-canada/2026.06/airports.sqlite \
  --dof /data/makerplane-data/obstacles/current/obstacles.sqlite \
  --out /tmp/aer1692_windowed_1920x1200.png --timeout 20 --verbose
# captured /tmp/aer1692_windowed_1920x1200.png, exit 0, real 0m1.759s, 1920x1200
# despite --width 800 --height 600 (same eglfs fullscreen-forcing as before)
systemctl --user reset-failed pyefis.service
systemctl --user restart pyefis.service
```

**Update (2026-09-19, second Pi session): full DoD reached.** A physical
HDMI display is now connected to the Pi 5 (Bill connected one after
accepting the confirmation card raised in the first session below).
`--offscreen` now produces a real frame, **concurrently with `pyefis.service`
holding the display**, without disturbing it. This section supersedes the
"blocked" disposition further down, which is kept as-is for the record of
what was tried and learned in the first session.

## Result

1. **`--offscreen` renders.** Real 800x600 and 1920x1200 frames captured on
   the Pi 5's V3D 7.1.10.2 hardware. `offscreen_concurrent_800x600.png` is
   the primary artifact for DoD item 1.
2. **Concurrently with pyEfis holding the display.** `pyefis.service`'s
   `MainPID` and `NRestarts` were sampled immediately before and after each
   offscreen capture and were unchanged both times -- the offscreen render
   ran, and completed, without pyEfis losing or regaining the display.
3. **Frame committed** (this directory), exact commands below, embedded via
   SHA-pinned raw URLs in the PR body (confirmed 200 + `image/*` before
   posting).
4. **Compared against a windowed capture of the same pose** -- see "How
   closely they agree" below. They agree exactly on terrain and disagree
   systematically (not noisily) on sky color. Reported, not tuned to match,
   per this issue's own instruction.
5. **What this does and does not prove** -- see the final section.

## Bench state

Pi 5, `wpballard@10.110.10.199`. `~/pyEfis` was already clean on `dev` @
`aa7f16c` from the prior session. `/sys/class/drm/card1-HDMI-A-2/status` now
reads `connected` (was `disconnected` on both connectors in the first
session). `pyefis.service` (a **user** unit --
`systemctl --user is-active pyefis.service`) was `active`, `NRestarts=0`,
running against this display for the entire test.

The AER-1631 diff to `tools/svs_capture.py` (this branch vs. `dev` @
`aa7f16c`) was applied to the bench as a patch, exercised, then reverted --
same hygiene as the first session. Nothing was left dirty; see "Bench
hygiene" at the end.

## A required env var, not a code defect

The first session's `--offscreen` run (before a display was connected)
died with `drmModeGetResources failed (Operation not supported)` /
`no screens available`, then the same font-engine `QScreen::handle()`
null-deref segfault documented below, and that was attributed entirely to
"zero screens connected." **That was only half the story.** After
connecting a display, the *identical* command -- run either concurrently
with `pyefis.service` or with it stopped -- still failed exactly the same
way, until `QT_QPA_EGLFS_KMS_CONFIG` was set to the same
`/home/wpballard/eglfs_hdmi.json` (`{"device":
"/dev/dri/by-path/platform-axi:gpu-card"}`) that `pyefis.service`'s systemd
unit sets via `Environment=`. This Pi has two DRM nodes (`card0`, `card1`);
without that env var, Qt's eglfs KMS backend apparently probes/selects a
node with no usable output attached and still reports zero screens even
though one is physically connected and lit up for `pyefis.service`.

This is **not a `svs_capture.py` code defect** -- it's an environment
requirement `pyefis.service` satisfies for itself (via its own unit file)
that a standalone CLI invocation has to supply explicitly, same as
`QT_QPA_PLATFORM=eglfs` already does. Documented here rather than patched
around in code, consistent with this issue's scope (two named defects,
nothing more) -- a caller of `--offscreen` on a multi-DRM-node box needs
both `QT_QPA_PLATFORM=eglfs` and `QT_QPA_EGLFS_KMS_CONFIG` set to whatever
device file actually has the output.

## Exact commands

Concurrent offscreen capture (primary DoD 1+2 evidence, `pyefis.service`
`active`/`NRestarts=0` before and after, same PID throughout):

```bash
cd ~/pyEfis
export QT_QPA_PLATFORM=eglfs
export QT_QPA_EGLFS_KMS_CONFIG=/home/wpballard/eglfs_hdmi.json
export PYTHONPATH=src:tests
.venv/bin/python tools/svs_capture.py --offscreen \
  --lat 34.4275 --lon -119.8546 --alt 500 --heading 87 --range 8 \
  --width 800 --height 600 \
  --tiles /data/makerplane-data/terrain/tiles \
  --water /data/makerplane-data/water/current/water.sqlite \
  --nasr /data/makerplane-data/airports/airports-canada/2026.06/airports.sqlite \
  --dof /data/makerplane-data/obstacles/260611/obstacles.sqlite \
  --out /tmp/aer1631_offscreen_coastal.png --timeout 30 --verbose
```

Result: `captured /tmp/aer1631_offscreen_coastal.png`, exit 0.
`pyefis.service` `MainPID`/`NRestarts` sampled immediately before and after:
unchanged (`MainPID=102115`, `NRestarts=0` both times).

A second offscreen capture at `--width 1920 --height 1200` (same command,
different `--width`/`--height`/`--out`), run the same way, immediately after
-- also concurrent, also clean (`MainPID=102203` after an intervening
restart for the windowed comparison below, `NRestarts=0` both times around
this specific capture). This size matches what the windowed path actually
produces (next section), for a same-resolution pixel comparison.

Windowed comparison capture -- **`pyefis.service` was stopped first**
(only one process can hold DRM master; this is exactly the constraint
`--offscreen` exists to route around, so a windowed comparison capture
cannot run concurrently with pyEfis by construction) and restarted
immediately after:

```bash
systemctl --user stop pyefis.service
cd ~/pyEfis
export QT_QPA_PLATFORM=eglfs
export QT_QPA_EGLFS_KMS_CONFIG=/home/wpballard/eglfs_hdmi.json
export PYTHONPATH=src:tests
.venv/bin/python tools/svs_capture.py \
  --lat 34.4275 --lon -119.8546 --alt 500 --heading 87 --range 8 \
  --width 800 --height 600 \
  --tiles /data/makerplane-data/terrain/tiles \
  --water /data/makerplane-data/water/current/water.sqlite \
  --nasr /data/makerplane-data/airports/airports-canada/2026.06/airports.sqlite \
  --dof /data/makerplane-data/obstacles/260611/obstacles.sqlite \
  --out /tmp/aer1631_windowed_coastal.png --timeout 30 --verbose
systemctl --user reset-failed pyefis.service   # stop leaves it "failed", not "inactive" -- Restart=always/StartLimitIntervalSec=0 (AER-1674) means the unit needs an explicit reset before restart, not a defect introduced here
systemctl --user restart pyefis.service
```

Result: `captured /tmp/aer1631_windowed_coastal.png`, exit 0, **1920x1200**
despite `--width 800 --height 600` being passed -- eglfs has no window
manager, so a shown top-level window is forced fullscreen at the display's
native resolution regardless of the requested size. `pyefis.service` was
back to `active`, `NRestarts=0`, new `MainPID`, within 5s of the restart.

## How closely they agree

**Corrected 2026-09-19 (AER-1692).** The numbers below are re-measured
against the re-captured, geometry-fixed frames. The previous version of this
section (sky "disagrees smoothly and systematically", 46.4% of pixels
differ) was measuring the 360-row horizon displacement, not a colour or
surface-format difference -- see the AER-1692 update note at the top of this
document. That hypothesis is retracted.

Pixel diff between `offscreen_1920x1200.png` and `windowed_1920x1200.png`
(matching resolution, same pose, same command modulo `--offscreen`):

| region | agreement |
|---|---|
| terrain / ground (bottom ~50% of frame) | **byte-identical** -- mean abs diff 0.0/255 |
| sky (top ~40% of frame) | **near-identical** -- mean abs diff 0.267/255 (anti-aliasing-scale noise, not a systematic shift) |
| whole frame | 0.09% of pixels differ at all; 0.09% differ by >30/255 in some channel; mean abs diff 0.111/255 |

**Superseded 2026-09-20 (AER-1785): this table was measured against the
stale `windowed_1920x1200.png`.** That frame predated the `bankAngleRadius`
fix (`e89c9c1`) -- its bank cluster (arc + datum pointer) was drawn at half
radius (200px instead of 400px). The residual this table attributed to
"anti-aliasing-scale noise... confined to curved/rotated edges like the
bank arc" was measured against exactly the region a mis-sized bank arc
would occupy, so it was at minimum conflating that real defect with true
AA noise, not measuring AA noise alone as stated. Not re-litigated further
here -- as of `e89c9c1`/`5bb6e90` the two frames are byte-identical (0%
differ, no residual to attribute), see the update note at the top of this
document.

`sidebyside_full_1920x1200.png` and `horizon_align_crop_zoom3x.png`, which
used to be referenced here, were **deleted** (not regenerated) once that
byte-identity was confirmed -- a diff panel between two identical images is
blank and has no evidentiary job left. See the deletion note at the top of
this document.

The residual ~0.1% (anti-aliasing-scale, confined to curved/rotated edges
like the bank arc) is not chased further here -- it is two orders of
magnitude below the geometry defect this issue fixed, and is exactly the kind
of rounding difference expected between two independently-rasterized paths at
the same nominal size.

## What this does and does not prove

- **Proves:** both AER-1205 defects (`resizeEvent` never firing; the FBO's
  GL context never being reasserted current) are fixed -- `--offscreen`
  completes and writes a real frame.
- **Proves:** it does so **concurrently with `pyefis.service` holding the
  display**, without disturbing it (unchanged `MainPID`/`NRestarts` across
  two separate concurrent captures) -- the specific claim AER-763 was opened
  to demonstrate and that had never been shown before this session.
- **Proves:** terrain content (the data-driven part of the render -- SRTM
  elevation, water, airports, obstacles) is byte-identical between the
  offscreen and windowed paths at the same pose and resolution.
- **Proves (AER-1692):** with the geometry fix, the artificial horizon,
  pitch ladder and bank cluster land at the same pixel rows as the windowed
  capture, and scale with the requested `--height` rather than sitting at a
  fixed absolute row -- the two paths agree to within anti-aliasing noise
  (0.09% of pixels differ, mean abs diff 0.111/255) rather than the 46.4%/
  16.4-per-255 divergence the pre-fix frames showed. The sky-colour
  hypothesis in the original "How closely they agree" section is retracted.
- **Does not prove** this generalizes to poses/configs untested here
  (single coastal SBA pose, terrain_only=False, default MSAA/AA settings).
- **Does not prove** `QT_QPA_EGLFS_KMS_CONFIG` is unnecessary on a
  single-DRM-node box -- this Pi has two nodes; a box with one might not
  need it, untested.
- **Does not prove** `render_offscreen_frame()`'s per-tick GPU allocation is
  leak-free when `pump()` has to loop for many ticks (a scene that is slow to
  settle, not just one that never will) -- AER-1692's own testing hit
  repeated `MESA: error: Failed to allocate device memory for BO` and one
  full board reboot while diagnosing a *stale `--dof` path* that made the
  scene never settle at all (see the update note at the top). Once pointed
  at valid data every capture here settled in under 2 seconds, at which
  point this was never exercised. Whether a few seconds of genuinely slow
  settling (not "never") is also safe is untested and worth its own
  follow-up if `--offscreen` is going to run against real (not mock) data
  sources that can legitimately take longer to promote.

## Bench hygiene

- `~/pyEfis` stayed on `dev` @ `aa7f16c` throughout. The AER-1631 diff to
  `tools/svs_capture.py` was applied via `git apply`, exercised for every
  capture above, then reverted (`git checkout -- tools/svs_capture.py`) --
  clean tree at the end of this session, same as the first.
- `pyefis.service` was stopped exactly once (for the windowed comparison,
  which cannot coexist with pyEfis by construction) and restarted
  immediately after; confirmed `active`/`NRestarts=0` before ending the
  session.

**AER-1692 session bench hygiene.** `~/pyEfis` stayed on `dev` @ `aa7f16c`
throughout; the AER-1631+AER-1692 diff was applied via `git apply`, exercised
for every capture in this update, then reverted, same convention as above.
`pyefis.service` was stopped once for the windowed comparison and restarted
immediately after (confirmed `active`, `NRestarts=0`, display `connected`
at the end). One thing this session did *not* leave clean by choice: while
diagnosing the stale-`--dof`/never-settled crash before finding its real
cause, an early offscreen run crashed hard enough to reboot the Pi 5 outright
(not just the capture process) -- `pyefis.service` came back up on its own
(`Restart=always`) with no action needed, and no data or bench state was
lost, but flagging it plainly rather than only in the narrative above: this
board rebooted once during this session.

---

## First session (2026-09-18): "zero screens" -- superseded above

**This section is retained for the record.** At the time it was written,
the Pi had no HDMI display connected at all, so DoD items 1/2/4 could not
be attempted. A display is now connected (see above) and those items are
now met, with the caveat that part of what looked like a hardware
precondition was actually a missing `QT_QPA_EGLFS_KMS_CONFIG` env var (see
above) -- the original "zero screens" framing was correct as far as it
went, but incomplete.

**Original result: both defects AER-1205 root-caused are fixed and
confirmed fixed on real eglfs hardware (Pi 5, V3D 7.1.10.2). A third,
distinct failure blocks producing an actual frame right now: this Pi
currently has no HDMI display physically connected, and Qt's eglfs
font-engine setup segfaults on a null `QScreen*` whenever zero screens
exist -- for both the offscreen and the windowed path alike.** Per this
issue's own guardrail ("if the repair needs more than the two defects
above, say so and stop"), that third failure was reported here, not
patched around.

Bench: Pi 5, `wpballard@10.110.10.199`, `~/pyEfis` fast-forwarded to
`origin/dev` @ `aa7f16c` (was stale at `4a16d54`, ~110 commits behind; clean
fast-forward, no local changes lost). The AER-1631 fix (this branch's diff to
`tools/svs_capture.py`) was applied as a patch, tested, then reverted so the
bench checkout was left clean on `dev`.

`pyefis.service` was not running during this test: it was crash-looping in
its own `wait-for-display` pre-start gate (`NRestarts` in the high 20s),
for the exact same root cause described below -- both HDMI connectors
reported `disconnected` in `/sys/class/drm/card1-HDMI-A-{1,2}/status`. So
DoD item 2 ("concurrently with pyEfis holding the display") could not be
attempted at all in this session; pyEfis never reached DRM master.

### 1. Offscreen path, with the AER-1631 fix applied

```bash
cd ~/pyEfis
export QT_QPA_PLATFORM=eglfs
export PYTHONPATH=src:tests
.venv/bin/python tools/svs_capture.py --offscreen \
  --lat 34.4275 --lon -119.8546 --alt 500 --heading 87 --range 8 \
  --width 800 --height 600 \
  --tiles /data/makerplane-data/terrain/tiles \
  --water /data/makerplane-data/water/current/water.sqlite \
  --nasr /data/makerplane-data/airports/airports-canada/2026.06/airports.sqlite \
  --dof /data/makerplane-data/obstacles/260611/obstacles.sqlite \
  --out /tmp/aer1631_offscreen_coastal.png --timeout 30 --verbose
```

Result: `Segmentation fault` (exit 139). This was progress, not a
regression -- see the `gdb` backtrace below and the "before/after"
comparison.

`gdb --batch -ex run -ex "thread apply all bt"` on the same command:

```
AI: FIX key 'VPATH' not defined — Flight Path Marker disabled

Thread 1 "python" received signal SIGSEGV, Segmentation fault.
0x00007ffff29d9608 in QScreen::handle() const () from /lib/aarch64-linux-gnu/libQt6Gui.so.6
#0  QScreen::handle() const ()
#1  QEglFSKmsIntegration::nativeResourceForScreen(QByteArray const&, QScreen*) ()
#2  QFontconfigDatabase::setupFontEngine(QFontEngineFT*, QFontDef const&) const ()
#3  QFontconfigDatabase::fontEngine(QFontDef const&, void*) ()
#4  QFontDatabasePrivate::loadSingleEngine(...) ()
...
#15 QGraphicsSimpleTextItem::setText(QString const&) ()
#16 QGraphicsScene::addSimpleText(QString const&, QFont const&) ()
#17 <PyQt6 QtWidgets shim>
```

`addSimpleText` is `AI.resizeEvent`'s `fail_scene` "XXX" text (`ai_widget.py`,
built every resize regardless of offscreen/windowed). The crash is inside
Qt's own font-engine setup, reached via the eglfs KMS platform integration's
`nativeResourceForScreen`, which calls `.handle()` on a `QScreen*` that is
null because `QGuiApplication::screens()` is empty (zero connected HDMI
connectors -> eglfs creates zero `QScreen` objects). This is a Qt/eglfs
platform bug triggered by *any* text rendering when zero screens exist --
unrelated to `--offscreen` specifically.

### 2. Confirms this is a "zero screens" problem, not an offscreen-path problem

Same pose, same bench, windowed (non-`--offscreen`) path, no code changes
needed (this path predates AER-1631):

```bash
.venv/bin/python tools/svs_capture.py \
  --lat 34.4275 --lon -119.8546 --alt 500 --heading 87 --range 8 \
  --width 800 --height 600 --tiles ... --water ... --nasr ... --dof ... \
  --out /tmp/aer1631_windowed_coastal.png --timeout 10 --verbose
```

Result: `Cannot create window: no screens available`, then `SIGABRT` inside
`QWindowPrivate::init` (Qt's own `qFatal` on window creation with no screen
to place it on) -- the original AER-763 failure mode, reproduced exactly as
documented, confirming the windowed path was equally unable to run at that
time for the identical underlying reason (zero screens), not something the
offscreen fix introduced or could have avoided.

### 3. Confirms the two AER-1205 defects are actually fixed

Before AER-1631, the offscreen path failed at `AttributeError: 'AI' object
has no attribute 'overlay'` inside `_paint_overlays`, called from
`render_offscreen_frame` at `pump()`'s very first tick -- i.e. before the
scene was ever built. After AER-1631, the same command instead ran through:
`QApplication` init -> `make_offscreen_target` (surface valid, context
created, `makeCurrent` succeeded, FBO valid -- none of these printed the
tool's own `"could not create an offscreen GL surface/context"` failure
message, so all four succeeded) -> `AI.__init__` (reaches the `VPATH` FIX-key
warning, which only fires from inside the constructor) -> `set_svs_config`
-> the explicit `resizeEvent()` call -> `QGraphicsScene` construction ->
`addSimpleText` for the fail-scene placeholder. That is deep inside real
scene construction, well past both the resize-event-delivery defect and the
first FBO-paint attempt (which is later in the same function, and never
reached that time only because the process died first on the font-engine
call). No "context needs to be current" / "Painter not active" error
occurred in that run before the segfault, consistent with the makeCurrent
re-assertion fix holding up as far as it got exercised.
