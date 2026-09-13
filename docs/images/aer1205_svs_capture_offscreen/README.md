# AER-1205 -- offscreen `svs_capture.py` bench proof

**Result: the merged `--offscreen` path (pyEfis#179 / AER-763, commit `ba5592e`)
does not render on real hardware. It crashes before producing a frame.**
This is a genuine finding, not a setup mistake -- see "What was tried" below.

Bench: Beelink, `10.110.10.241` (`beelinkpyefis`), pyEfis checkout
`~/src/pyEfis` -- staged at the time on `aer-1149/wide-water-cliff` @
`0393723` for an unrelated review (left untouched, per
`bench_deploy.md`'s "hands off a staged branch that's still under review").
That checkout already contained `ba5592e` (merged into `dev` before this
branch's last merge-from-dev), so no branch switch was needed to test the
merged offscreen code.

`pyefis.service` was `active` the whole time (X/xcb kiosk on `DISPLAY=:0`,
confirmed via `~/start-pyefis.sh`: `QT_QPA_PLATFORM=xcb`, not eglfs) and
remained `active`, with no traceback in its journal, for the entire test.

**Correction to the AER-763 premise:** the commit message states "pyEfis
holds DRM master under eglfs." On this box pyEfis runs under a real X11
session (`X/xcb kiosk`), not eglfs -- confirmed from `~/start-pyefis.sh` and
the running process's environment. X11 multiplexes clients, so a *second
on-screen* window does not in fact contend for the display here (see the
windowed contrast capture below, taken with `pyefis.service` active and
undisturbed) -- the specific constraint `--offscreen` was built to route
around does not hold on this hardware. That does not make `--offscreen`
pointless (eglfs deployments, e.g. the Pi, would still hit it), but it means
this box could not have exercised the "no window has anywhere to go" failure
mode even if the offscreen code worked.

## What was tried

### 1. Offscreen path, exactly as merged

```bash
DISPLAY=:0 QT_QPA_PLATFORM=xcb ~/pyefis-venv/bin/python tools/svs_capture.py \
  --lat 34.4275 --lon -119.8546 --alt 1500 --heading 87 --pitch 5 --roll -12 \
  --range 15 --width 1920 --height 1080 \
  --tiles /data/makerplane-data/terrain/tiles \
  --water /data/makerplane-data/water/current/water.sqlite \
  --nasr /data/makerplane-data/navdata/current/airports.sqlite \
  --dof /data/makerplane-data/obstacles/current/obstacles.sqlite \
  --highways /data/makerplane-data/highways/current/highways.sqlite \
  --water-max-vertices 1000000 \
  --offscreen --verbose \
  --out /tmp/aer1205_offscreen.png
```

Result: no PNG. Traceback (exit 134, `SIGABRT` -- Qt's `qFatal` on an
uncaught Python exception inside a Qt callback):

```
AI: FIX key 'VPATH' not defined — Flight Path Marker disabled
Traceback (most recent call last):
  File "/home/pyefis/src/pyEfis/tools/svs_capture.py", line 597, in pump
    render_offscreen_frame(widget, fbo, paint_device)
  File "/home/pyefis/src/pyEfis/tools/svs_capture.py", line 357, in render_offscreen_frame
    widget._paint_overlays(painter)
  File "/home/pyefis/src/pyEfis/src/pyefis/instruments/ai/ai_widget.py", line 1196, in _paint_overlays
    p.drawImage(self.rect(), self.overlay)
                             ^^^^^^^^^^^^
AttributeError: 'AI' object has no attribute 'overlay'
```

(A first attempt with no `DISPLAY`/`QT_QPA_PLATFORM` set failed earlier and
differently -- Qt's default platform-plugin probe hit `xcb` with no `$DISPLAY`
at all and aborted before any application code ran
(`qt.qpa.xcb: could not connect to display`). That's an SSH-session artifact,
not a finding; setting `QT_QPA_PLATFORM=xcb` explicitly, matching how
`pyefis.service` itself is launched, gets past it and reaches the real
result above.)

### 2. Root-caused with a scratch-instrumented copy (not committed)

`self.overlay` is built inside `AI.resizeEvent` (`ai_widget.py:641`).
`svs_capture.py`'s offscreen path calls `widget.resize(args.width,
args.height)` in place of `win.show()`, on the documented assumption that
resize "Triggers resizeEvent -> builds the scene and calls redraw() once."
A one-off instrumented copy of the tool (patched on the bench, run, then
deleted -- never committed) printed widget state right after that call:

```
DEBUG after resize(): has overlay= False WA_WState_Created= False
DEBUG after processEvents(): has overlay= False
```

`WA_WState_Created=False` is the root cause: a top-level `QWidget` that has
never been shown has no native window, and Qt does not synthesize a
`resizeEvent` for it purely from `.resize()` -- `app.processEvents()`
afterward doesn't help either, because no event was ever queued. The
assumption in the `--offscreen` docstring/commit message is the specific
thing that was wrong; this is a Qt widget-lifecycle fact, not a GL or
hardware limitation, and would reproduce identically on any platform --
the original sandbox just never got Qt running at all, so there was no way
to catch it there.

A further scratch experiment forced `widget.create()` + a manually
constructed `resizeEvent()` call to see how much further the path gets: the
scene now builds, but the FBO's `QOpenGLPaintDevice`-backed `QPainter`
reports "Painter not active" / "QOpenGLPaintDevice's context needs to be
current" throughout the paint, and the scene never settles (30 s timeout).
That points at a second problem -- context-current bookkeeping around
`widget.create()` -- layered under the first. Neither scratch change was
committed; per the issue, the job here was to characterize the failure, not
patch it into working silently.

### 3. Windowed (known-good) capture, same pose, for contrast

Confirms the rest of the pipeline -- scene construction, terrain, water,
obstacles, airport symbology, collectors settling -- is sound on this
hardware, and that the defect is isolated to the offscreen code path, not
the tool or the data.

```bash
DISPLAY=:0 QT_QPA_PLATFORM=xcb ~/pyefis-venv/bin/python tools/svs_capture.py \
  --lat 34.4275 --lon -119.8546 --alt 1500 --heading 87 --pitch 5 --roll -12 \
  --range 15 --width 1920 --height 1080 \
  --tiles /data/makerplane-data/terrain/tiles \
  --water /data/makerplane-data/water/current/water.sqlite \
  --nasr /data/makerplane-data/navdata/current/airports.sqlite \
  --dof /data/makerplane-data/obstacles/current/obstacles.sqlite \
  --highways /data/makerplane-data/highways/current/highways.sqlite \
  --water-max-vertices 1000000 \
  --verbose \
  --out windowed_contrast.png
```

Exit 0, `captured windowed_contrast.png`. Run while `pyefis.service` was
`active` throughout (a second on-screen X client, not offscreen --
uncontended on this X11 box per the correction above).

![windowed contrast frame -- Santa Barbara coastal pose, terrain + water + obstacles + SBA airport marker](https://raw.githubusercontent.com/billmallard/pyEfis/8c9293b2c8bb12619ec4fc3fb944838c7ae5f838/docs/images/aer1205_svs_capture_offscreen/windowed_contrast.png)

`pyefis.service` was confirmed `active` before and after every attempt above,
with no `traceback`/`error`/`segfault` in its journal for the test window --
the crashes are confined to the `svs_capture.py` process; pyEfis on the glass
was never disturbed.

## What this does and does not prove

- **Proves:** the offscreen path as merged does not initialize on real
  hardware -- it crashes deterministically, every run, at the same line, for
  a documented and now-understood reason (a false assumption about Qt
  resize-event delivery to an unshown widget, not a GL/driver issue).
- **Proves:** the rest of the SVS capture pipeline (scene, terrain, water,
  obstacles, symbology, collector settling) is sound on this bench, isolating
  the defect to the offscreen-specific code added in `ba5592e`.
- **Proves:** `pyefis.service` is undisturbed by attempting the offscreen
  path -- no crash, no journal error, `active` throughout.
- **Does not prove** the offscreen path would work correctly once the
  `resizeEvent`/paint-device-current issues are fixed, nor whether its output
  would then match the windowed path pixel-for-pixel -- there is no offscreen
  frame to compare. That comparison is only possible after both defects
  found above are fixed.
- **Does not prove or disprove** the eglfs-specific DRM-contention premise
  that motivated AER-763 in the first place -- this box runs X11, so that
  specific contention could not be exercised here either way (see the
  correction above). A DRM-holding (eglfs) rig would be needed to test that
  half of the original claim.

## Disposition

AER-763 stays `blocked`: the offscreen renderer does not yet render anything,
on this hardware, at all. This issue (AER-1205) is what was asked for --
one bench run that executes the merged path end to end and reports the
result, including a traceback as a valid outcome. The two bugs identified
above (resize-event delivery; FBO context-current bookkeeping) are follow-up
work for whoever picks AER-763 back up, not something invented or fixed
here.
