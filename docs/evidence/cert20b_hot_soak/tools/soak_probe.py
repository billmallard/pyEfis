"""CERT20b (AER-6451) in-process probe: run the real pyEfis main() with
timestamp hooks and a screen cycler. Bench tool, not shipped code; it
changes no pyEfis source and is started in place of ``python pyEfis.py``.

Every timestamp is ``time.monotonic_ns()`` (CLOCK_MONOTONIC), the same clock
``soak_feed.py`` and ``soak_thermal.py`` stamp with, so the three logs join
without any clock alignment.

Records, one CSV line each, to $SOAK_OUT:
  P,<t0>,<dur>,<roll>,<screen>   an AI paintEvent (only a visible AI paints)
  U,<t0>,<dur>,<class>           an UpdateRequest to any object (a widget window
                                 composes and swaps there), with its class
  R,<t>,<roll>                   AI.setRollAngle (the ROLL value reached the widget)
  S,<t>,<screen>                 the cycler showed a screen
  I,<t>,<json>                   install record (screens, AI count, env)

Knobs (env):
  SOAK_OUT     output path (required)
  SOAK_DWELL   seconds on each screen before the next (default 15; 0 = no cycling)
The file is flushed once a second and on SIGTERM, which quits the Qt loop
cleanly (the recorder must not lose its tail; see the AER-6243 lesson).
"""
import json
import os
import signal
import sys
import time

OUT = os.environ["SOAK_OUT"]
DWELL = float(os.environ.get("SOAK_DWELL", "15"))

from PyQt6.QtCore import QObject, QEvent, QTimer  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from pyefis.instruments.ai import ai_widget  # noqa: E402

now = time.monotonic_ns
_buf = []
_fh = open(OUT, "a", buffering=1)
_screen = ["?"]


def _flush():
    if _buf:
        _fh.write("".join(_buf))
        _buf.clear()
        _fh.flush()


_orig_paint = ai_widget.AI.paintEvent
_orig_roll = ai_widget.AI.setRollAngle


def _paint(self, ev):
    t0 = now()
    try:
        return _orig_paint(self, ev)
    finally:
        _buf.append("P,%d,%d,%r,%s\n" % (t0, now() - t0, self._rollAngle, _screen[0]))


def _roll(self, angle):
    _buf.append("R,%d,%r\n" % (now(), angle))
    return _orig_roll(self, angle)


ai_widget.AI.paintEvent = _paint
ai_widget.AI.setRollAngle = _roll


class _URFilter(QObject):
    """Time every UpdateRequest in the application by delivering it ourselves.
    Installed on the QApplication, so it also sees the QWindow of any widget
    that composes on its own surface, not only the Main widget."""

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.UpdateRequest:
            t0 = now()
            r = obj.event(ev)
            _buf.append("U,%d,%d,%s\n" % (t0, now() - t0, type(obj).__name__))
            return r
        return False


_keep = []


def _cycle():
    from pyefis import gui
    win = gui.mainWindow
    n = len(gui.screens)
    if n == 0:
        return
    nxt = (win.running_screen + 1) % n
    win.showScreen(nxt)
    _screen[0] = gui.screens[win.running_screen].name
    _buf.append("S,%d,%s\n" % (now(), _screen[0]))


def _install():
    app = QApplication.instance()
    from pyefis import gui
    win = getattr(gui, "mainWindow", None)
    tops = [w for w in app.topLevelWidgets() if w.isVisible()] if app else []
    if app is None or win is None or not tops:
        QTimer.singleShot(1000, _install)
        return
    f = _URFilter()
    _keep.append(f)
    app.installEventFilter(f)
    _screen[0] = gui.screens[win.running_screen].name
    ais = [w for w in app.allWidgets() if isinstance(w, ai_widget.AI)]
    rec = {"wall": time.time(), "pid": os.getpid(),
           "screens": [s.name for s in gui.screens],
           "dropped": sorted(getattr(win, "dropped_screens", ()) or ()),
           "start_screen": _screen[0], "ais": len(ais),
           "tops": [type(w).__name__ for w in tops], "dwell_s": DWELL,
           "env": {k: v for k, v in os.environ.items() if k.startswith(("SOAK_", "QT_"))}}
    _buf.append("I,%d,%s\n" % (now(), json.dumps(rec)))
    _buf.append("S,%d,%s\n" % (now(), _screen[0]))
    if DWELL > 0:
        t = QTimer(app)
        t.timeout.connect(_cycle)
        t.start(int(DWELL * 1000))
        _keep.append(t)


def _on_term(signum, frame):
    _flush()
    app = QApplication.instance()
    if app is not None:
        app.quit()
    else:
        sys.exit(0)


def _boot():
    orig_exec = QApplication.exec

    def _exec(*a):
        app = QApplication.instance()
        ft = QTimer(app)
        ft.timeout.connect(_flush)   # also hands Python the GIL for signals
        ft.start(1000)
        _keep.append(ft)
        QTimer.singleShot(3000, _install)
        try:
            return orig_exec()
        finally:
            _flush()
    QApplication.exec = _exec


signal.signal(signal.SIGTERM, _on_term)
_boot()
from pyefis.main import main  # noqa: E402
sys.argv[0] = "pyefis"
try:
    sys.exit(main())
finally:
    _flush()
