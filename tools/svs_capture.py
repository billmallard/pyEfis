"""Deterministic SVS frame capture.

Renders the AI/SVS at one commanded pose, waits until the scene is genuinely
*settled*, writes a PNG, and exits. Intended for golden-image regression tests and
for any automated tool that needs to judge a frame rather than look at one.

Why this exists (and why ``SVS_SCREENSHOT`` is not enough)
---------------------------------------------------------
``tests/visual_svs_test.py`` already has a capture hook, and it is not safe to
regress against. Three defects compound:

1. **The scene is racy.** Water, highways, obstacles and airports are each built on
   a daemon thread, serialised behind a single ``_collect_slot``, and their results
   are promoted into the render *only on a subsequent paint* -- there is no signal,
   callback or timer anywhere that says "done". Whatever happens to have landed by
   the deadline is what you capture.

2. **Repaints stop at t ~= 2.0 s, so a longer delay does not help.** With a static
   pose the only thing driving repaints is dead reckoning, and ``PoseSource`` caps
   extrapolation at ``extrap_cap_s = 2.0``. Past that the pose stops changing,
   ``_frame_tick`` short-circuits, painting ceases, and the scene freezes
   **half-loaded, permanently**. The default ``SVS_SCREENSHOT_DELAY_MS`` of 2000 sits
   exactly on that knife-edge.

3. **The captured aircraft is not where you put it.** That same dead reckoning runs
   the seeded ``GS = 120 kt`` forward for two seconds before it saturates, so the
   rendered position is displaced ~124 m downtrack of the commanded lat/lon. Every
   committed golden carries the error.

And the capture is a *screen* grab (``QScreen.grabWindow``), so anything overlapping
the window -- a notification, a second harness window, a locked session -- lands in
the PNG.

What this tool does instead
---------------------------
* **Pins the pose** (``extrap_cap_s = 0``), so the render is at the exact commanded
  lat/lon/alt.
* **Drives the repaints itself**, since nothing else will once the pose is static.
* **Waits on the settled predicate** -- every collector has finished, promoted, and
  is idle, and terrain has actually drawn -- rather than on a stopwatch. Timing out
  is a hard failure, not a silently half-drawn frame.
* **Reads the pixels back inside the paint**, where the widget's FBO holds the fully
  composited frame. This is why ``grabFramebuffer()`` cannot work here:
  ``QOpenGLWidget::grabFramebuffer()`` re-renders through ``paintGL()``, and as a
  ``QGraphicsView`` *viewport* the widget never paints through ``paintGL()`` -- so it
  hands back an empty user-paint. Reading at the end of ``paintEvent`` sidesteps it,
  and needs no visible window.
* **Disables MSAA**, because ``glReadPixels`` on a multisample FBO is invalid -- and
  because the sample pattern is driver-specific, which a golden should not be.

Exit codes: 0 ok, 2 never settled (timeout), 3 GL unavailable, 4 PNG write
failed, 5 requested/delivered size mismatch (windowed path only -- see
``--width``/``--height`` below).

On success a ``<out>.json`` sidecar is written alongside the frame, naming not
just *when* it was rendered but *which path* drew it (AER-1675, AER-1795):
``pyefis_rev`` (the checkout, ``<short-sha>[-dirty]``, resolved live each run
rather than a constant someone has to remember to bump), ``capture_mode``
(``"windowed"`` or ``"offscreen"``), ``requested_size`` and ``actual_size``
(the AER-1785 defect was a window resized out from under the request -- a
sidecar recording both would have named it without a bench session),
``argv`` (the exact invocation) and ``sha256`` of the PNG itself (so a reader
can confirm the sidecar in hand belongs to the file sitting next to it, not a
stale one from a previous run). A reader holding only the PNG and its
sidecar can answer "which capture path produced these bytes, at what size,
from what command" without reading a commit message or trusting anybody's
prose -- which is exactly what a byte-identical windowed/offscreen pair
otherwise cannot say for itself (#251/AER-1793).

Usage::

    python tools/svs_capture.py --lat 24.5561 --lon -81.7595 --alt 500 \\
        --heading 270 --range 15 --out frame.png

    # flat, unlit terrain -- for automated pixel classification
    python tools/svs_capture.py ... --flat --terrain-only

    # symbology only, terrain suppressed -- for judging a constant attitude
    # bias, which a terrain-and-symbology frame can hide
    python tools/svs_capture.py ... --symbology-only

``--offscreen`` (AER-763): capturing needs a window today (a ``QMainWindow``
that gets ``.show()``n so its ``QOpenGLWidget`` viewport can initialise). Under
eglfs that window needs a screen, and eglfs hands out at most one -- so this
tool cannot run at all while pyEfis is already on the glass and holding DRM
master ("Cannot create window: no screens available"). ``--offscreen`` avoids
that by never creating a window: it drives a ``QOffscreenSurface`` +
``QOpenGLContext`` + ``QOpenGLFramebufferObject`` directly, which eglfs can
grant without a free screen (probed and confirmed working alongside a running
pyEfis; see AER-763). The AI widget is used exactly as before for pose,
config and the scene graph, but rendering goes through
``QGraphicsView.render()`` onto the FBO's paint device instead of through the
widget's own (window-bound) viewport compositing --
``AI._paint_overlays()`` is the extracted half of ``paintEvent`` that isn't
scene items (the bank cluster, FPM, chevrons, ...) and gets driven the same
way. AER-1205 proved the first cut of this path never actually rendered
(two defects: ``resize()`` on a never-``show()``n widget delivers no
``resizeEvent``, so the scene was never built; and the offscreen GL context
was made current once at setup and never again, so the FBO's QPainter came
up inactive on every real paint attempt). AER-1631 fixes both -- see the
issue thread for the Pi validation evidence (concurrent with a live pyEfis,
diffed against a windowed capture of the same pose) before treating this as
a second golden source in a new context.

``--width``/``--height`` on the windowed path (AER-1810): eglfs has no window
manager, so a windowed top-level does not get the size it asks for -- the
platform forces it to the screen size regardless, delivering the requested
geometry as a first resizeEvent and the forced one as a second (the same
two-resize sequence AER-1785 diagnosed for ``bankAngleRadius``). The
requested size is not silently dropped; it does briefly reach the widget,
which makes the failure sharper than "the flag is ignored" -- a caller who
asked for 800x600 gets a real, fully-rendered 1920x1200 PNG at exit 0, with
nothing about the name or the exit code saying so. This tool refuses that
capture instead: once the scene settles, the delivered viewport geometry is
compared against the requested size, and a mismatch exits ``5`` before any
PNG or sidecar is written -- never a warning that still exits 0, and never a
silent substitution of a different render path. A caller that needs a
specific size guaranteed on eglfs has that already, in ``--offscreen``: its
FBO is allocated at exactly the requested size and cannot be resized out
from under the request by a window manager that isn't there. This is
complementary to, not a replacement for, AER-1795's sidecar
``requested_size``/``actual_size`` fields above: those two keys can now
never disagree for a *windowed* capture that reached the sidecar at all
(a mismatch is refused before ``_write_manifest`` runs), but the other three
AER-1795 fields -- ``capture_mode``, ``argv``, ``sha256`` -- answer questions
this refusal does nothing about (which path drew a frame, from what
invocation, and whether the sidecar in hand still belongs to the PNG next to
it), and remain exactly as load-bearing as before.
"""

import argparse
import hashlib
import json
import logging
import subprocess
import sys
from pathlib import Path

# Dependencies live in C:\pylib on the Windows dev box, not site-packages.
if r"C:\pylib" not in sys.path:
    sys.path.insert(0, r"C:\pylib")

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "src"))
sys.path.insert(0, str(_REPO / "tests"))

# Run against the mock FIX db, exactly as the visual harness does -- no gateway.
import mock_db.client  # noqa: E402
import mock_db.scheduler  # noqa: E402

sys.modules["pyavtools.fix.client"] = mock_db.client
sys.modules["pyavtools.scheduler"] = mock_db.scheduler

import pyavtools.fix as fix  # noqa: E402
from OpenGL import GL as gl  # noqa: E402
from PyQt6.QtCore import Qt, QRectF, QSize, QTimer  # noqa: E402
from PyQt6.QtGui import QImage, QPainter, QResizeEvent  # noqa: E402
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget  # noqa: E402

from pyefis.instruments.ai import AI  # noqa: E402

EXIT_OK = 0
EXIT_NOT_SETTLED = 2
EXIT_GL_FAILED = 3
EXIT_SAVE_FAILED = 4
EXIT_SIZE_MISMATCH = 5

PUMP_INTERVAL_MS = 16
CONFIRM_FRAMES = 2  # settled must hold this many paints running


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--out", required=True, help="PNG path to write")

    pose = p.add_argument_group("pose")
    pose.add_argument("--lat", type=float, required=True)
    pose.add_argument("--lon", type=float, required=True)
    pose.add_argument("--alt", type=float, required=True, help="feet MSL")
    pose.add_argument("--heading", type=float, default=0.0, help="degrees")
    pose.add_argument("--pitch", type=float, default=0.0, help="degrees")
    pose.add_argument("--roll", type=float, default=0.0, help="degrees")
    pose.add_argument(
        "--magvar",
        type=float,
        default=0.0,
        help="magnetic variation, degrees, west-positive (FAA 'West is best': "
        "MAG = TRUE + W_VAR). HEAD is magnetic; the AI widget derives true "
        "heading as HEAD - MAGVAR. Default 0.0 reproduces every existing "
        "capture byte-for-byte",
    )

    view = p.add_argument_group("view")
    view.add_argument("--range", type=float, default=30.0, dest="range_nm")
    view.add_argument(
        "--auto-range",
        action="store_true",
        help="let the renderer shrink range with altitude (off by default here: a "
        "capture should render the range it was asked for)",
    )
    view.add_argument(
        "--width", type=int, default=800,
        help="on the windowed path, eglfs (no window manager) may force the "
        "delivered geometry to the screen size regardless of what's "
        "requested here -- if so, the tool refuses to capture (exit 5) "
        "rather than write a PNG whose name lies. --offscreen always gets "
        "the exact size requested",
    )
    view.add_argument(
        "--height", type=int, default=600,
        help="see --width",
    )
    view.add_argument(
        "--offscreen",
        action="store_true",
        help="render into a QOffscreenSurface + FBO instead of opening a window. "
        "Use this when another process (pyEfis) already holds the display -- a "
        "second on-screen window has nowhere to go there, but an offscreen "
        "surface does not contend for it. See the module docstring for how "
        "this differs from the default path and what is not yet verified "
        "about it (AER-763)",
    )

    look = p.add_argument_group("appearance")
    look.add_argument(
        "--flat",
        action="store_true",
        help="disable haze, ground texture and the grid. Terrain and water become "
        "their flat base colours, so a frame can be classified by pixel value "
        "instead of eyeballed",
    )
    look.add_argument(
        "--terrain-only",
        action="store_true",
        help="terrain and sky only, no symbology",
    )
    look.add_argument(
        "--symbology-only",
        action="store_true",
        help="mirror of --terrain-only: horizon line, pitch ladder, bank "
        "scale, aircraft symbol and FPM, against the flat two-tone "
        "sky/ground background -- terrain is disabled outright (svs.enabled "
        "= False), not merely hidden, so nothing terrain-derived can leak "
        "into a symbology-bias judgement. Mutually exclusive with "
        "--terrain-only",
    )
    look.add_argument(
        "--msaa",
        type=int,
        default=1,
        help="samples. Must be 1 for readback; >1 is accepted but will fail",
    )

    data = p.add_argument_group("data")
    data.add_argument("--tiles", default=r"D:\EarthData\srtm3")
    data.add_argument("--water", default=None)
    data.add_argument("--nasr", default=None)
    data.add_argument("--cifp", default=None)
    data.add_argument("--dof", default=None)
    data.add_argument("--highways", default="")
    data.add_argument(
        "--water-max-vertices",
        type=int,
        default=1024,
        help="per-polygon vertex cap at load. MUST be >= the pack's largest ring. "
        "WaterDB.DEFAULT_MAX_VERTICES is 32, and at that cap _decode_vertices "
        "stride-decimates the ring while _decode_triangles keeps the ORIGINAL "
        "indices -- which are then clamped, collapsing most triangles to "
        "degenerate slivers. Omitting this silently renders corrupt water",
    )

    p.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="seconds to wait for the scene to settle before failing",
    )
    p.add_argument("--verbose", action="store_true")
    p.add_argument(
        "--perf-log",
        action="store_true",
        help="enable the SVS per-frame profiler (collector/draw timings, "
        "mirrors the screen-config svs_perf_log option) and force one "
        "summary report to stderr once the capture settles -- a "
        "single-shot capture usually finishes well under the profiler's "
        "own 2s report interval, so without forcing this would silently "
        "never print",
    )
    args = p.parse_args(argv)
    if args.terrain_only and args.symbology_only:
        p.error("--terrain-only and --symbology-only are mirror images of "
                 "each other; pick one")
    if args.offscreen and args.msaa != 1:
        # Same constraint the windowed path already has (see --msaa's help):
        # glReadPixels on a multisample FBO is invalid. The offscreen FBO is
        # always allocated with 0 samples, so a non-default --msaa here would
        # silently be ignored rather than failing at readback -- reject it
        # up front instead.
        p.error("--offscreen always renders at 1 sample; --msaa must be 1 "
                "(or omitted)")
    return args


def _default(path, *parts):
    if path is not None:
        return path
    candidate = _REPO.joinpath(*parts)
    return str(candidate) if candidate.exists() else ""


def _default_water():
    found = sorted((_REPO / "water").glob("water_rtree*.sqlite"))
    return str(found[0]) if found else ""


def resolve_pyefis_rev(repo_root=None):
    """Identify the pyEfis checkout actually rendering this frame (AER-1675).

    A cross-renderer differential (Beelink vs Pi) only localises a defect if
    a disagreement can be attributed to *different code* vs *different GPU*
    -- which needs the rendering identity read from the checkout that is
    live right now, not a constant someone has to remember to bump (a
    constant is a lie waiting to happen). Dirty is reported rather than
    silently collapsed into the clean SHA: a frame rendered from uncommitted
    changes is not reproducible from that SHA alone.

    Never raises -- this is metadata for archival/attribution, not something
    a capture should fail over. Returns "unknown" if this isn't a git
    checkout or git is unavailable.
    """
    root = repo_root or _REPO
    try:
        sha = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        if sha.returncode != 0:
            return "unknown"
        rev = sha.stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True, text=True, timeout=10,
        )
        if dirty.returncode == 0 and dirty.stdout.strip():
            rev += "-dirty"
        return rev
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _write_manifest(
    out_path, *, pyefis_rev, capture_mode, requested_size, actual_size,
):
    """Sidecar `<out>.json` naming not just when `<out>` was rendered but
    which path drew it, at what size, from what command (AER-1795).

    A sidecar carrying only ``pyefis_rev`` cannot distinguish "windowed and
    offscreen agree because they draw the same scene through the same
    deterministic renderer" from "one is a copy of the other" -- exactly the
    ambiguity that sent #251's byte-identical pair back around as AER-1793.
    ``sha256`` is self-referential by design: it lets a reader confirm the
    sidecar sitting next to a PNG actually belongs to it, rather than a
    stale one left over from a previous run at the same ``--out`` path.
    Called after the PNG is written, never before -- it has to hash the
    bytes that were actually saved.
    """
    out_path = Path(out_path)
    manifest_path = Path(str(out_path) + ".json")
    manifest = {
        "pyefis_rev": pyefis_rev,
        "capture_mode": capture_mode,
        "requested_size": list(requested_size),
        "actual_size": list(actual_size),
        "argv": " ".join(sys.argv),
        "sha256": hashlib.sha256(out_path.read_bytes()).hexdigest(),
    }
    manifest_path.write_text(json.dumps(manifest, indent=1))


def _report_perf(svs):
    """Force one SVS perf-profiler summary line for --perf-log, bypassing
    the profiler's own 2s report interval (svs.py's ``_SVSPerfLog``) --
    a single-shot capture settles well under that, so without forcing this
    call, --perf-log would enable the profiler and still print nothing."""
    perf = getattr(svs, "_perf", None)
    if perf is not None:
        perf.maybe_report(force=True)


class CapturingAI(AI):
    """AI that can read its own composited framebuffer back at end of paint."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.capture_to = None
        self.capture_ok = None
        self.capture_actual_size = None

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.capture_to is None:
            return
        path, self.capture_to = self.capture_to, None
        self.capture_ok, self.capture_actual_size = _readback(
            self.viewport(), path)


def _readback_pixels(w, h, path):
    """Read the currently bound framebuffer. Must run with the GL context
    current and the framebuffer to be read already bound."""
    from OpenGL import GL as gl

    gl.glPixelStorei(gl.GL_PACK_ALIGNMENT, 1)
    buf = gl.glReadPixels(0, 0, w, h, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE)

    # GL's origin is bottom-left; QImage's is top-left. copy() detaches from buf.
    img = QImage(bytes(buf), w, h, QImage.Format.Format_RGBA8888)
    return bool(img.mirrored(False, True).copy().save(path, "PNG"))


def _delivered_size(viewport):
    """The pixel geometry a readback of ``viewport`` would actually produce --
    the same width/height math ``_readback`` uses, exposed separately so a
    caller can check it *before* spending a readback (AER-1810)."""
    dpr = viewport.devicePixelRatioF()
    return int(round(viewport.width() * dpr)), int(round(viewport.height() * dpr))


def _readback(viewport, path):
    """Read the widget's FBO. Must run with the GL context current, i.e. in
    paint. Returns ``(ok, (w, h))`` -- the actual pixel size read back,
    which the caller records in the sidecar alongside the requested size
    (AER-1795): devicePixelRatioF() scaling or a window resized out from
    under the request (AER-1785) can make them differ."""
    w, h = _delivered_size(viewport)
    return _readback_pixels(w, h, path), (w, h)


def check_delivered_size(viewport, requested_width, requested_height):
    """``None`` if ``viewport``'s delivered geometry matches what was
    requested; otherwise the actual ``(w, h)`` it settled at (AER-1810).

    On eglfs (no window manager) a windowed top-level is forced to the
    screen size regardless of ``--width``/``--height`` -- the requested size
    reaches the widget as a first resizeEvent, the platform's forced
    fullscreen as a second (AER-1785's two-resize sequence), and only the
    second is what a readback would actually capture. The caller must treat
    a non-``None`` result as a hard failure, not a warning: a mismatch here
    means the requested geometry was never, even briefly, the one the scene
    settled and rendered at, so a PNG saved under that name would misstate
    its own size.
    """
    actual = _delivered_size(viewport)
    if actual == (requested_width, requested_height):
        return None
    return actual


def make_offscreen_target(width, height):
    """Build a render target that needs no platform window: a
    QOffscreenSurface + QOpenGLContext + QOpenGLFramebufferObject.

    This is the AER-763 unlock -- unlike a QOpenGLWidget/QGraphicsView
    viewport (which under eglfs needs a real, screen-backed platform window,
    the exact resource pyEfis already holds), a QOffscreenSurface does not
    contend for the display. Returns ``None`` on any failure so the caller
    can report EXIT_GL_FAILED instead of dereferencing a half-built target.
    """
    from PyQt6.QtGui import QOffscreenSurface, QOpenGLContext, QSurfaceFormat
    from PyQt6.QtOpenGL import (
        QOpenGLFramebufferObject,
        QOpenGLFramebufferObjectFormat,
        QOpenGLPaintDevice,
    )

    fmt = QSurfaceFormat()
    fmt.setSamples(0)  # glReadPixels on a multisample FBO is invalid

    surface = QOffscreenSurface()
    surface.setFormat(fmt)
    surface.create()
    if not surface.isValid():
        return None

    ctx = QOpenGLContext()
    ctx.setFormat(fmt)
    if not ctx.create():
        return None
    if not ctx.makeCurrent(surface):
        return None

    fbo_fmt = QOpenGLFramebufferObjectFormat()
    fbo_fmt.setSamples(0)
    fbo_fmt.setAttachment(
        QOpenGLFramebufferObject.Attachment.CombinedDepthStencil)
    fbo = QOpenGLFramebufferObject(width, height, fbo_fmt)
    if not fbo.isValid():
        return None
    fbo.bind()

    paint_device = QOpenGLPaintDevice(width, height)
    # surface and ctx are returned only to keep them alive (Qt does not hold
    # a reference for us); this tool is short-lived and never tears them
    # down, letting process exit reclaim the context/surface.
    return surface, ctx, fbo, paint_device


def render_offscreen_frame(widget, ctx, surface, fbo, paint_device):
    """Paint one frame of ``widget`` directly into ``fbo``.

    Stands in for ``AI.paintEvent`` in the offscreen path: ``paintEvent``
    itself is unreachable without a live QOpenGLWidget viewport, which in
    turn needs the real platform window this path exists to avoid.
    ``QGraphicsView.render()`` reproduces the scene compositing
    ``super().paintEvent()`` does -- including the view's roll-rotation and
    pitch-offset transform applied by ``redraw()`` -- onto an arbitrary
    QPainter, with no dependency on the viewport widget's own paint device.
    ``AI._paint_overlays()`` is the extracted non-scene half of paintEvent
    (bank cluster, FPM, chevrons, ...); it takes a QPainter directly for
    exactly this reason.

    Re-asserts the offscreen context as current every call (AER-1631):
    ``ctx.makeCurrent(surface)`` was previously done once at setup and
    never again, on the assumption a QOpenGLContext stays the thread's
    current context indefinitely. It does not -- nothing here promises
    that across repeated Qt event-loop iterations, which is exactly why
    QOpenGLWidget's own paintGL() always re-asserts its context before
    invoking user paint code. Without the re-assert, ``fbo.bind()``
    silently fails and the paint device's QPainter never becomes active
    ("context needs to be current"), and the scene never settles.

    Ends every call with ``glFinish()`` (AER-1697): this FBO is never
    presented through ``eglSwapBuffers`` -- there is no window, and
    ``QOffscreenSurface`` has no swap chain -- so the V3D kernel driver
    never gets the "frame boundary" signal it uses to reclaim the
    per-submission scratch/binning BOs each draw call allocates. A
    windowed ``QOpenGLWidget`` gets that boundary for free from Qt's own
    swap-on-repaint; this path has to ask for it explicitly. Measured on
    the Pi 5 (real terrain, ``pyefis.service`` holding the display
    concurrently) without this call: ~100-120 new BOs (~1.9 MB) leaked
    on *every* 16ms ``pump()`` tick while waiting for ``settled()``,
    unbounded and linear in tick count (confirmed via
    ``/sys/kernel/debug/dri/*/bo_stats``) -- the mechanism behind
    AER-1692's/AER-1789's ``Failed to allocate device memory for BO``
    crashes and the one board reboot. With this call, the same
    ``bo_stats`` counters go flat within the first couple of ticks and
    stay flat for 1000+ subsequent ticks, regardless of how long the
    scene takes to settle.
    """
    if not ctx.makeCurrent(surface):
        raise RuntimeError("offscreen GL context failed to become current")
    widget._update_land_brush()
    if not fbo.bind():
        raise RuntimeError("offscreen FBO failed to bind")
    painter = QPainter(paint_device)
    if not painter.isActive():
        raise RuntimeError("offscreen QPainter failed to become active")
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    rect = QRectF(0, 0, widget.width(), widget.height())
    # QGraphicsView.render()'s ``source`` (view coordinates, mapped to the
    # scene via the current transform) defaults to viewport().rect() when
    # left unset -- which is exactly the value AER-1692 found stuck at Qt's
    # implicit 640x480 top-level default in this never-shown offscreen
    # widget. Passing it explicitly, matching ``target``, removes the
    # dependency on that fallback tracking the widget's real size.
    source = widget.rect()
    if widget.terrain_only:
        hl = getattr(widget, "_horizon_line", None)
        if hl is not None:
            hl.setOpacity(0.0)
        for _i, _item in widget.pitchItems:
            _item.setOpacity(0.0)
        widget.render(painter, rect, source)
    else:
        widget.render(painter, rect, source)
        widget._paint_overlays(painter)
    painter.end()
    gl.glFinish()


def resize_for_offscreen_capture(widget, width, height):
    """Deliver an offscreen ``AI`` widget its first (and only) resize.

    ``resize()`` alone does NOT deliver a resizeEvent here (AER-1631): Qt
    only sends one to a widget carrying WA_WState_Created, which is set on
    show()/window creation -- exactly the call this path exists to avoid
    under eglfs DRM contention. The scene/overlay construction that a real
    resize would trigger lives entirely in AI.resizeEvent (ai_widget.py), is
    pure CPU/QPainter work with no GL dependency, and doesn't chain to
    QGraphicsView.resizeEvent -- so it's safe and faithful to call it
    directly instead of forcing a real window.

    But calling resizeEvent() as a plain Python method, rather than
    delivering it through Qt's real event dispatch, also skips
    QAbstractScrollArea's own Resize handling -- the code that resizes
    QGraphicsView's internal viewport() child widget to track the view's
    size. AI never constructs a window, so that viewport is never shown or
    laid out either, and it never gets a first real resize: it is left at
    whatever size it had when set_svs_config() installed it.
    AI.resizeEvent's own scene/pixelsPerDeg math reads self.width()/height()
    (the outer widget, resized below) and is unaffected, but redraw()'s
    centerOn() call positions the scene using viewport().width()/height() --
    so with that stuck at its installed size, every capture composites the
    AI overlay about the wrong centre row, regardless of the requested
    --width/--height (AER-1692; the symptom was a constant ~240px centre
    row, half of Qt's implicit 640x480 top-level default).

    set_svs_config() unconditionally installs a live QOpenGLWidget as this
    view's viewport, for the windowed path's native-GL SVS painting --
    exactly the DRM/GPU resource --offscreen exists to never touch (see the
    module docstring). render_offscreen_frame() never paints through it: it
    reads back through a separate QOffscreenSurface/FBO, so the live GL
    viewport is dead weight here, kept only because set_svs_config() doesn't
    know which path called it. Resizing that widget directly -- the first
    fix attempted here -- forces Qt to try to create its native GL surface
    on eglfs while pyefis.service already holds DRM master, and repeating
    that every pump() tick exhausted GPU memory and crashed the Pi 5 bench
    outright (a board reboot, not just a process crash). Swap in an inert
    QWidget instead: a plain (non-native, non-GL) child needs no DRM/GPU
    resource to resize, and centerOn()/render()'s implicit viewport().rect()
    fallback only need its *size* to be right, not its paint capability --
    this process never shows it or paints through it either way.
    """
    widget.setViewport(QWidget())
    widget.resize(width, height)
    widget.viewport().resize(width, height)
    widget.resizeEvent(QResizeEvent(QSize(width, height), QSize(0, 0)))


def settled(svs, expect_layers, require_terrain=True):
    """True once every asynchronous collector has finished and been promoted.

    Each layer parks its result in ``_async_state[name]["res"]`` and nothing wakes
    the UI, so a result only becomes visible on the *next* paint. A layer is done
    when no worker is alive, no result is pending promotion, and a key has actually
    been recorded -- ``val`` may legitimately be empty (nothing in range), so the
    test is on ``key``, never on ``val``.

    ``expect_layers`` is the set of layers whose data source was configured. Without
    it a cold first frame looks settled purely because no collector has run yet.

    ``require_terrain`` gates the ``drew_terrain`` check. ``--symbology-only``
    runs with ``svs.enabled = False``, so the SVS graphics item's ``paint()``
    is a no-op (``not self._renderer.ready``, svs.py's ``make_svs_item``) --
    ``drew_terrain`` never becomes True and never will, by design. There are
    also no terrain-side collectors to wait for in that mode, so the caller
    passes ``expect_layers=set()`` alongside ``require_terrain=False``.
    """
    if svs is None:
        return False
    if require_terrain and (svs.gl_failed or not svs.drew_terrain):
        return False

    for name in expect_layers:
        state = svs._async_state.get(name)
        if state is None:  # not even requested yet
            return False
        if state.get("res") is not None:
            return False
        worker = state.get("worker")
        if worker is not None and worker.is_alive():
            return False
        if state.get("key") is None:
            return False

    for db_attr, result, worker, key in (
        ("water_db", "_water_result", "_water_worker", "_water_tris_cache_key"),
        ("highway_db", "_hwy_result", "_hwy_worker", "_hwy_cache_key"),
    ):
        db = getattr(svs, db_attr, None)
        if db is None or not getattr(db, "ready", False):
            continue
        if getattr(svs, result) is not None:
            return False
        w = getattr(svs, worker)
        if w is not None and w.is_alive():
            return False
        if getattr(svs, key) is None:
            return False

    return True


def seed_mock_fix(args):
    """Define and populate the mock FIX keys the AI widget reads.

    Isolated from ``main`` so it can be exercised without a GL context: it
    touches only ``fix.db``, never Qt/GL. Returns the pose values actually
    written, keyed by FIX name, so a test can assert on them directly.
    """
    fix.initialize({"main": {"FixServer": "localhost", "FixPort": "3490"}})
    for key, desc, lo, hi, units in (
        ("PITCH", "Pitch", -90.0, 90.0, "deg"),
        ("ROLL", "Roll", -180.0, 180.0, "deg"),
        ("ALAT", "LatAccel", -30.0, 30.0, "g"),
        ("TAS", "TAS", 0.0, 2000.0, "knots"),
        ("HEAD", "Heading", 0.0, 359.9, "deg"),
        ("VS", "VS", -30000, 30000, "ft/min"),
        ("GS", "GS", 0.0, 2000.0, "knots"),
        ("TRACK", "Track", 0.0, 359.9, "deg"),
        # VPATH is optional in real operation (ai_widget.py falls back to
        # atan2(VS, GS) when a source doesn't publish it), but leaving it
        # undefined here makes the FPM's VPATH-preferred branch permanently
        # unexercised by this harness and logs a "Flight Path Marker
        # disabled" warning that overstates the effect (AER-1790) -- VS=0
        # above, so 0.0 is the same steady-state value the atan2 fallback
        # would compute anyway.
        ("VPATH", "VPath", -90.0, 90.0, "deg"),
        ("LAT", "Lat", -90.0, 90.0, "deg"),
        ("LONG", "Lon", -180.0, 180.0, "deg"),
        ("ALT", "Alt", -2000, 60000, "ft"),
        ("MAGVAR", "MagVar", -30.0, 30.0, "deg"),
    ):
        fix.db.define_item(key, desc, "float", lo, hi, units, 50000, "")
        item = fix.db.get_item(key)
        item.bad = False
        item.fail = False

    heading = args.heading % 360.0  # HEAD's range is 0..359.9; 360 would clamp
    values = {
        "PITCH": args.pitch,
        "ROLL": args.roll,
        "ALAT": 0.0,
        "TAS": 120.0,
        "HEAD": heading,
        "VS": 0.0,
        "GS": 120.0,
        "TRACK": heading,
        "VPATH": 0.0,
        "LAT": args.lat,
        "LONG": args.lon,
        "ALT": args.alt,
        "MAGVAR": args.magvar,
    }
    for key, value in values.items():
        fix.db.set_value(key, value)
    return values


def main(argv=None):
    args = parse_args(argv)
    pyefis_rev = resolve_pyefis_rev()

    if args.perf_log:
        # svs.py's profiler logs via `logging.getLogger(__name__).info(...)`;
        # with no handler configured, INFO records are swallowed silently
        # (the root logger's default level is WARNING), so --perf-log would
        # look like it did nothing. This is the tool's only user of the
        # logging module, so a plain basicConfig is not fighting anyone else.
        logging.basicConfig(level=logging.INFO, format="%(message)s")

    highways = args.highways
    if args.symbology_only:
        # Terrain is disabled outright below (svs.enabled = False), so none
        # of the terrain-side data sources are ever queried -- the async
        # collectors they'd feed never run and never record a cache key.
        # Forcing every source off here keeps settled()'s bookkeeping empty
        # instead of waiting forever on state that will never arrive.
        water = nasr = cifp = dof = highways = ""
    else:
        water = args.water if args.water is not None else _default_water()
        nasr = _default(args.nasr, "nasr", "airports.sqlite")
        cifp = _default(args.cifp, "cifp", "FAACIFP18")
        dof = _default(args.dof, "dof", "obstacles.sqlite")

    expect_layers = set()
    if nasr or cifp:
        expect_layers.add("airports")
    if dof:
        expect_layers.add("obstacles")

    seed_mock_fix(args)

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication([])

    svs_config = {
        # --symbology-only disables the SVS outright rather than hiding its
        # output: make_svs_item's paint() no-ops on `not ready` (svs.py), so
        # the terrain layer never touches the framebuffer and the AI's own
        # land-brush fallback (flat brown/blue, no data files involved) is
        # what's left below the horizon. This is the cheaper mirror of
        # --terrain-only asked for in AER-707 -- no new suppression path in
        # ai/__init__.py or svs.py.
        "enabled": not args.symbology_only,
        "tile_path": args.tiles,
        "renderer": "opengl",
        "range_nm": args.range_nm,
        "auto_range": args.auto_range,
        "clearance_green_ft": 1000,
        "clearance_yellow_ft": 500,
        "cifp_path": cifp,
        "nasr_db_path": nasr,
        "dof_db_path": dof,
        "water_db_path": water,
        "water_max_vertices": args.water_max_vertices,
        "highway_db_path": highways,
        "paved_only": True,
        "perf_log": args.perf_log,
        "haze": not args.flat,
        "haze_distance_nm": 40.0,
        "msaa_samples": 0 if args.offscreen else args.msaa,
        "safe_gradient": not args.flat,
        "terrain_texture": 0.0 if args.flat else 0.35,
        "terrain_grid": 0.0 if args.flat else 0.35,
    }

    # show_fpm follows terrain_only today; --symbology-only leaves it True
    # (the same as the plain default capture) because the FPM is real
    # symbology and, unlike position, isn't dead-reckoned -- it's drawn
    # straight from the pinned GS/TRACK/HEAD FIX values set above, so it's
    # exactly as deterministic as the horizon line and pitch ladder.
    win = None
    offscreen_target = None
    if args.offscreen:
        offscreen_target = make_offscreen_target(args.width, args.height)
        if offscreen_target is None:
            print("SVS: could not create an offscreen GL surface/context",
                  file=sys.stderr)
            return EXIT_GL_FAILED
        surface, ctx, fbo, paint_device = offscreen_target
        widget = AI(None, show_fpm=not args.terrain_only)
    else:
        win = QMainWindow()
        win.resize(args.width, args.height)
        widget = CapturingAI(win, show_fpm=not args.terrain_only)

    widget.terrain_only = args.terrain_only
    widget.set_svs_config(svs_config)

    # Pin the pose. PoseSource dead-reckons from the seeded GS/TRACK, so without
    # this the frame renders ~124 m downtrack of the commanded position -- and then
    # stops repainting when the 2 s extrapolation cap saturates, which is what
    # freezes the existing goldens half-loaded.
    widget._pose.extrap_cap_s = 0.0

    if args.offscreen:
        resize_for_offscreen_capture(widget, args.width, args.height)
    else:
        win.setCentralWidget(widget)
        win.show()

    state = {"confirmed": 0, "elapsed_ms": 0, "requested": False, "done": False}
    timeout_ms = args.timeout * 1000.0

    def pump():
        svs = getattr(widget, "_svs_renderer", None)

        if svs is not None and svs.gl_failed:
            print("SVS: OpenGL renderer unavailable", file=sys.stderr)
            app.exit(EXIT_GL_FAILED)
            return

        if args.offscreen:
            if state["done"]:
                return
        elif widget.capture_ok is not None:
            if widget.capture_ok:
                _write_manifest(
                    args.out,
                    pyefis_rev=pyefis_rev,
                    capture_mode="windowed",
                    requested_size=(args.width, args.height),
                    actual_size=widget.capture_actual_size,
                )
                _report_perf(svs)
                print(f"captured {args.out}")
                app.exit(EXIT_OK)
            else:
                print(f"failed to write {args.out}", file=sys.stderr)
                app.exit(EXIT_SAVE_FAILED)
            return

        if state["elapsed_ms"] > timeout_ms:
            print(
                f"scene never settled within {args.timeout:.0f}s -- refusing to "
                f"capture a half-loaded frame",
                file=sys.stderr,
            )
            app.exit(EXIT_NOT_SETTLED)
            return

        if args.offscreen:
            # There is no window to dispatch a real paintEvent, so this path
            # drives its own render each tick instead of the widget.update()
            # below -- see render_offscreen_frame's docstring.
            try:
                render_offscreen_frame(widget, ctx, surface, fbo, paint_device)
            except RuntimeError as e:
                print(f"SVS: offscreen render failed: {e}", file=sys.stderr)
                app.exit(EXIT_GL_FAILED)
                return

        if not state["requested"]:
            if settled(svs, expect_layers, require_terrain=not args.symbology_only):
                state["confirmed"] += 1
                if state["confirmed"] >= CONFIRM_FRAMES:
                    if args.offscreen:
                        state["done"] = True
                        # render_offscreen_frame just ran this same tick and left
                        # ctx current, but re-assert explicitly rather than rely
                        # on that -- the whole point of AER-1631 is not trusting
                        # current-ness to persist implicitly.
                        if not ctx.makeCurrent(surface) or not fbo.bind():
                            print("SVS: offscreen context/FBO not available "
                                  "for readback", file=sys.stderr)
                            app.exit(EXIT_GL_FAILED)
                            return
                        ok = _readback_pixels(args.width, args.height, args.out)
                        if ok:
                            _write_manifest(
                                args.out,
                                pyefis_rev=pyefis_rev,
                                capture_mode="offscreen",
                                requested_size=(args.width, args.height),
                                # The offscreen FBO is allocated at exactly
                                # (args.width, args.height) with no DPR
                                # scaling -- actual == requested by
                                # construction, unlike the windowed path.
                                actual_size=(args.width, args.height),
                            )
                            _report_perf(svs)
                            print(f"captured {args.out}")
                            app.exit(EXIT_OK)
                        else:
                            print(f"failed to write {args.out}", file=sys.stderr)
                            app.exit(EXIT_SAVE_FAILED)
                        return
                    mismatch = check_delivered_size(
                        widget.viewport(), args.width, args.height)
                    if mismatch is not None:
                        actual_w, actual_h = mismatch
                        print(
                            f"SVS: requested {args.width}x{args.height} but the "
                            f"scene settled at {actual_w}x{actual_h} -- eglfs "
                            f"(no window manager) forces a windowed top-level to "
                            f"the screen size and cannot grant an arbitrary one. "
                            f"Refusing to capture a frame whose filename would "
                            f"lie about its own size; use --offscreen for a "
                            f"guaranteed exact size.",
                            file=sys.stderr,
                        )
                        app.exit(EXIT_SIZE_MISMATCH)
                        return
                    widget.capture_to = args.out
                    state["requested"] = True
            else:
                state["confirmed"] = 0

        if not args.offscreen:
            # Nothing else will repaint us: _frame_tick short-circuits on an
            # unchanged pose, and the pose is now pinned. Collectors only
            # promote on a paint, so without this the scene can never finish
            # loading.
            widget._frame_dirty = True
            widget.update()
        state["elapsed_ms"] += PUMP_INTERVAL_MS

    timer = QTimer()
    timer.timeout.connect(pump)
    timer.start(PUMP_INTERVAL_MS)

    if args.verbose:
        print(f"pose   : {args.lat}, {args.lon} @ {args.alt} ft, hdg {args.heading}")
        print(f"range  : {args.range_nm} NM (auto_range={args.auto_range})")
        print(f"layers : {sorted(expect_layers) or 'none'}  water={bool(water)}")
        print(f"rev    : {pyefis_rev}")

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
