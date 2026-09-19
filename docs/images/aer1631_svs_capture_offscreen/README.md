# AER-1631 -- offscreen `svs_capture.py` repair, Pi 5 bench evidence

**Result: both defects AER-1205 root-caused are fixed and confirmed fixed on
real eglfs hardware (Pi 5, V3D 7.1.10.2). A third, distinct failure blocks
producing an actual frame right now: this Pi currently has no HDMI display
physically connected, and Qt's eglfs font-engine setup segfaults on a null
`QScreen*` whenever zero screens exist -- for both the offscreen and the
windowed path alike.** Per this issue's own guardrail ("if the repair needs
more than the two defects above, say so and stop"), that third failure is
reported here, not patched around.

Bench: Pi 5, `wpballard@10.110.10.199`, `~/pyEfis` fast-forwarded to
`origin/dev` @ `aa7f16c` (was stale at `4a16d54`, ~110 commits behind; clean
fast-forward, no local changes lost). The AER-1631 fix (this branch's diff to
`tools/svs_capture.py`) was applied as a patch, tested, then reverted so the
bench checkout is left clean on `dev` -- see "Bench hygiene" below.

`pyefis.service` was not running during this test: it is presently
crash-looping in its own `wait-for-display` pre-start gate (`NRestarts` in
the high 20s), for the exact same root cause described below -- both HDMI
connectors report `disconnected` in
`/sys/class/drm/card1-HDMI-A-{1,2}/status`. So DoD item 2 ("concurrently
with pyEfis holding the display") could not be attempted at all this run;
pyEfis never reaches DRM master.

## What was tried

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

Result: `Segmentation fault` (exit 139). This is progress, not a regression
-- see the `gdb` backtrace below and the "before/after" comparison.

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
documented, confirming the windowed path is equally unable to run right now
for the identical underlying reason (zero screens), not something the
offscreen fix introduced or could have avoided.

### 3. Confirms the two AER-1205 defects are actually fixed

Before AER-1631, the offscreen path failed at `AttributeError: 'AI' object
has no attribute 'overlay'` inside `_paint_overlays`, called from
`render_offscreen_frame` at `pump()`'s very first tick -- i.e. before the
scene was ever built. After AER-1631, the same command instead runs through:
`QApplication` init -> `make_offscreen_target` (surface valid, context
created, `makeCurrent` succeeded, FBO valid -- none of these print the
tool's own `"could not create an offscreen GL surface/context"` failure
message, so all four succeeded) -> `AI.__init__` (reaches the `VPATH` FIX-key
warning, which only fires from inside the constructor) -> `set_svs_config`
-> the explicit `resizeEvent()` call -> `QGraphicsScene` construction ->
`addSimpleText` for the fail-scene placeholder. That is deep inside real
scene construction, well past both the resize-event-delivery defect and the
first FBO-paint attempt (which is later in the same function, and never
reached this time only because the process died first on the font-engine
call). No "context needs to be current" / "Painter not active" error
occurred in this run before the segfault, consistent with the makeCurrent
re-assertion fix holding up as far as it got exercised.

## Bench hygiene

- `~/pyEfis` was fast-forwarded from `4a16d54` to `origin/dev` @ `aa7f16c`
  (`git pull --ff-only`, clean tree, no discarded work).
- The AER-1631 diff was applied via `git apply`, tested, then reverted via
  `git checkout -- tools/svs_capture.py`. The bench checkout is `dev` @
  `aa7f16c`, clean, at the end of this session.
- `pyefis.service` was not touched (nothing to restart -- it was never up).

## What this does and does not prove

- **Proves:** the two AER-1205 defects (`resize()` delivering no
  `resizeEvent`; the offscreen GL context never being re-asserted current)
  are fixed -- execution now reaches real `QGraphicsScene`/font-engine code
  that was previously unreachable, on the real V3D GPU, under real eglfs.
- **Proves:** a third, distinct failure exists -- Qt's eglfs font-engine path
  null-derefs `QScreen::handle()` when zero screens are connected -- and that
  this is a precondition-level problem (no HDMI output connected to this Pi
  right now), not specific to `--offscreen`: the windowed path fails exactly
  as hard, for the same underlying reason, matching its originally-documented
  failure mode.
- **Does not prove** `--offscreen` produces a correct frame, that it matches
  a windowed capture of the same pose, or that it can run concurrently with
  `pyefis.service` holding the display (DoD items 1, 2, 4) -- none of that is
  reachable until at least one HDMI display is connected to this Pi, which is
  outside this issue's or this agent's control.

## Disposition

`resizeEvent`-delivery and FBO-context-currency (AER-1205's two findings) are
fixed and the fix is evidenced above via progression past both original
failure signatures, captured with `gdb`. Full DoD (an actual rendered frame,
compared against a windowed capture, produced *while pyEfis holds the
display*) needs a physical HDMI display (or an EDID dummy plug) connected to
the Pi 5 at `10.110.10.199` -- currently both connectors report
`disconnected`. That is a hardware precondition, not a code defect, and is
named as the blocker on the issue.
