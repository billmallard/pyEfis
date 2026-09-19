# AER-1631 -- offscreen `svs_capture.py` repair, Pi 5 bench evidence

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

Pixel diff between `offscreen_1920x1200.png` and `windowed_1920x1200.png`
(matching resolution, same pose, same command modulo `--offscreen`):

| region | agreement |
|---|---|
| terrain / ground (bottom ~50% of frame) | **byte-identical** -- sampled RGB at y=700/900/1100 matched to the integer across the frame width |
| sky (top ~40% of frame) | **disagrees smoothly and systematically** -- not noise. Offscreen sky reads visibly brighter/more saturated than windowed sky at the same screen position; both follow the same gradient direction and hue |
| whole frame | 46.4% of pixels differ at all; 37.0% differ by >30/255 in some channel; mean abs diff 16.4/255 |

`sidebyside_full_1920x1200.png` shows the full frames and diff side by
side (downscaled for legibility). `sky_diff_crop_zoom3x.png` is a 3x
crop of the sky band (x700-1220, y200-400) where the difference
concentrates, offscreen/windowed/diff stacked.

**Likely cause, not confirmed, not fixed here.** The sky is a flat
`QLinearGradient` `QGraphicsScene` rect item (`ai_widget.py:508-523`) with
no data dependency -- a geometry or pose mismatch would shift/blur it, not
recolor it uniformly, and the identical terrain proves pose/geometry
*are* identical between the two runs. The most likely remaining explanation
is a rendering-pipeline difference between the two paint targets: the
windowed path's viewport is a `QOpenGLWidget` built with an explicit MSAA
`QSurfaceFormat` (`ai_widget.py:688-703`, `set_svs_config`), while the
offscreen path's `QOpenGLFramebufferObject` is built directly in
`make_offscreen_target()` (`tools/svs_capture.py:285-331`) with `setSamples(0)`
and no other format negotiation -- a color-space/sRGB-handling difference
between an app-configured `QOpenGLWidget` surface and a bare manually-built
FBO would produce exactly this signature (flat gradient content reads
correct in hue/direction but off in brightness/saturation, edges/geometry
otherwise unaffected). Per this issue's instruction ("disagreement is a
finding worth more than a green tick -- report it, do not tune until it
matches"), this is reported and not chased further here; it's a candidate
for its own follow-up issue if the offscreen path is meant to be a
pixel-exact stand-in for the windowed one rather than just a
render-something-real proof.

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
- **Does not prove** the two paths are pixel-identical overall -- the sky
  gradient disagrees systematically, cause not confirmed (see above).
- **Does not prove** this generalizes to poses/configs untested here
  (single coastal SBA pose, terrain_only=False, default MSAA/AA settings).
- **Does not prove** `QT_QPA_EGLFS_KMS_CONFIG` is unnecessary on a
  single-DRM-node box -- this Pi has two nodes; a box with one might not
  need it, untested.

## Bench hygiene

- `~/pyEfis` stayed on `dev` @ `aa7f16c` throughout. The AER-1631 diff to
  `tools/svs_capture.py` was applied via `git apply`, exercised for every
  capture above, then reverted (`git checkout -- tools/svs_capture.py`) --
  clean tree at the end of this session, same as the first.
- `pyefis.service` was stopped exactly once (for the windowed comparison,
  which cannot coexist with pyEfis by construction) and restarted
  immediately after; confirmed `active`/`NRestarts=0` before ending the
  session.

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
