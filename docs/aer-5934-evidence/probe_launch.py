"""SVSCEIL1 (AER-5934) unprofiled probe: launch pyEfis with counters on the
SVS frame clock, the AI paint and the top-level window's UpdateRequest
(repaint + flush/swap). No py-spy. Writes one JSON line per REPORT_S to
$PROBE_OUT. Knobs (env):
  PROBE_OUT       output jsonl path (required)
  PROBE_FPS       if set, AI.set_frame_rate(<value>) after start
  PROBE_SWAP      if set, QSurfaceFormat default swapInterval (0 = no vsync)
  PROBE_NOMAP     if 1, hide every moving_map widget (A/B: map cost)
"""
import json
import os
import sys
import time

OUT = os.environ["PROBE_OUT"]
REPORT_S = 5.0

from PyQt6.QtCore import QObject, QEvent, QTimer
from PyQt6.QtGui import QSurfaceFormat
from PyQt6.QtWidgets import QApplication

if os.environ.get("PROBE_SWAP") is not None:
    f = QSurfaceFormat.defaultFormat()
    f.setSwapInterval(int(os.environ["PROBE_SWAP"]))
    QSurfaceFormat.setDefaultFormat(f)

from pyefis.instruments.ai import ai_widget  # noqa: E402

pc = time.perf_counter
S = {"tick": [], "tick_paint": 0, "paint": [], "ur": [], "paint_any": {}}

_orig_tick = ai_widget.AI._frame_tick
_orig_update = ai_widget.AI.update
_orig_paint = ai_widget.AI.paintEvent
_in_tick = [False, False]


def _tick(self):
    t0 = pc()
    _in_tick[0] = True
    _in_tick[1] = False
    try:
        return _orig_tick(self)
    finally:
        _in_tick[0] = False
        S["tick"].append((t0, pc() - t0, _in_tick[1]))


def _update(self):
    if _in_tick[0]:
        _in_tick[1] = True
    return _orig_update(self)


def _paint(self, ev):
    t0 = pc()
    try:
        return _orig_paint(self, ev)
    finally:
        S["paint"].append((t0, pc() - t0))


ai_widget.AI._frame_tick = _tick
ai_widget.AI.update = _update
ai_widget.AI.paintEvent = _paint


class _URFilter(QObject):
    """Time the top-level window's UpdateRequest: deliver it ourselves."""

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.UpdateRequest:
            t0 = pc()
            obj.event(ev)
            S["ur"].append((t0, pc() - t0))
            return True
        return False


def _q(a, p):
    a = sorted(a)
    return round(a[min(len(a) - 1, int(p * len(a)))] * 1000, 1) if a else None


def _report():
    now = pc()
    tk, pt, ur = S["tick"], S["paint"], S["ur"]
    S["tick"], S["paint"], S["ur"] = [], [], []
    gaps = [b[0] - a[0] for a, b in zip(tk, tk[1:])]
    pgaps = [b[0] - a[0] for a, b in zip(pt, pt[1:])]
    rec = {
        "t": round(time.time(), 1), "secs": REPORT_S,
        "ticks_s": len(tk) / REPORT_S,
        "ticks_upd_s": sum(1 for x in tk if x[2]) / REPORT_S,
        "tick_gap_med": _q(gaps, .5), "tick_gap_p90": _q(gaps, .9),
        "tick_gap_max": _q(gaps, 1.0),
        "tick_ms_med": _q([x[1] for x in tk], .5),
        "tick_ms_p90": _q([x[1] for x in tk], .9),
        "paints_s": len(pt) / REPORT_S,
        "paint_ms_med": _q([x[1] for x in pt], .5),
        "paint_ms_p90": _q([x[1] for x in pt], .9),
        "paint_gap_med": _q(pgaps, .5), "paint_gap_p90": _q(pgaps, .9),
        "ur_s": len(ur) / REPORT_S,
        "ur_ms_med": _q([x[1] for x in ur], .5),
        "ur_ms_p90": _q([x[1] for x in ur], .9),
        "ur_busy_pct": round(100 * sum(x[1] for x in ur) / REPORT_S, 1),
        "tick_busy_pct": round(100 * sum(x[1] for x in tk) / REPORT_S, 1),
    }
    # how many UpdateRequests contained an AI paint
    i = 0
    with_ai = 0
    ps = sorted(x[0] for x in pt)
    for t0, d in ur:
        while i < len(ps) and ps[i] < t0:
            i += 1
        if i < len(ps) and ps[i] <= t0 + d:
            with_ai += 1
    rec["ur_with_ai_s"] = with_ai / REPORT_S
    with open(OUT, "a") as fh:
        fh.write(json.dumps(rec) + "\n")


_hooked = []


def _install():
    app = QApplication.instance()
    if app is None:
        QTimer.singleShot(1000, _install)
        return
    tops = [w for w in app.topLevelWidgets() if w.isVisible()]
    ais = [w for w in app.allWidgets() if isinstance(w, ai_widget.AI)]
    if not tops or not ais:
        QTimer.singleShot(1000, _install)
        return
    f = _URFilter()
    _hooked.append(f)
    for w in tops:
        w.installEventFilter(f)
    if os.environ.get("PROBE_FPS"):
        for a in ais:
            a.set_frame_rate(float(os.environ["PROBE_FPS"]))
    if os.environ.get("PROBE_NOMAP") == "1":
        from pyefis.instruments import map as _map
        for w in app.allWidgets():
            if type(w).__module__.startswith(_map.__name__) and \
                    type(w).__name__ in ("MovingMap", "Map", "MapWidget"):
                w.hide()
    with open(OUT, "a") as fh:
        fh.write(json.dumps({"installed": time.time(),
                             "tops": [type(w).__name__ for w in tops],
                             "ais": len(ais),
                             "env": {k: v for k, v in os.environ.items()
                                     if k.startswith(("PROBE_", "vblank"))}})
                 + "\n")
    t = QTimer(app)
    t.timeout.connect(_report)
    t.start(int(REPORT_S * 1000))
    _hooked.append(t)


def _boot():
    # QApplication does not exist yet; poll from a plain thread-free hook:
    # schedule once the app is constructed by patching QApplication.exec.
    orig_exec = QApplication.exec

    def _exec(*a):
        QTimer.singleShot(3000, _install)
        return orig_exec()
    QApplication.exec = _exec


_boot()
from pyefis.main import main  # noqa: E402
sys.argv[0] = "pyefis"
sys.exit(main())
