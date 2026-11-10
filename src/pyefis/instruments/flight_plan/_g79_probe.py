"""G79 / pyEfis #328 measurement probe. NOT FOR MERGE.

Writes JSON lines to /tmp/g79_probe.log so a bench run can line up, for one
tap: the X server's event time, when Qt delivered the press/release, when
the flight_plan handler returned, when flight_plan painted, and how long each
top-level window repaint+flush took. A 10 ms heartbeat records GUI-thread
stalls. Every record carries time.time() (wall) and time.monotonic().
"""
import json
import threading
import time

from PyQt6.QtCore import QEvent, QObject, QTimer
from PyQt6.QtWidgets import QApplication

_PATH = "/tmp/g79_probe.log"
_lock = threading.Lock()
_fh = None
_installed = None


def log(kind, **kw):
    global _fh
    rec = {"k": kind, "w": round(time.time(), 4), "m": round(time.monotonic(), 4)}
    rec.update(kw)
    with _lock:
        if _fh is None:
            _fh = open(_PATH, "a", buffering=1)
        _fh.write(json.dumps(rec) + "\n")


_INPUT = {
    QEvent.Type.MouseButtonPress: "press",
    QEvent.Type.MouseButtonRelease: "release",
    QEvent.Type.TouchBegin: "tbegin",
    QEvent.Type.TouchEnd: "tend",
    QEvent.Type.KeyPress: "key",
}


class _Filter(QObject):
    def __init__(self):
        super().__init__()
        self._in_update = False

    def eventFilter(self, obj, ev):
        t = ev.type()
        name = _INPUT.get(t)
        if name is not None:
            extra = {}
            try:
                extra["xts"] = int(ev.timestamp())
            except Exception:
                pass
            try:
                p = ev.globalPosition()
                extra["gx"], extra["gy"] = round(p.x()), round(p.y())
            except Exception:
                pass
            log(name, obj=type(obj).__name__, **extra)
            return False
        if (t == QEvent.Type.UpdateRequest and not self._in_update
                and getattr(obj, "isWindow", lambda: False)()):
            # Time the whole repaint + flush of the top-level window by
            # delivering the event ourselves and consuming it.
            self._in_update = True
            t0 = time.monotonic()
            try:
                obj.event(ev)
            finally:
                self._in_update = False
            log("upd", obj=type(obj).__name__, dur=round(time.monotonic() - t0, 4))
            return True
        return False


def install():
    global _installed
    if _installed is not None:
        return
    app = QApplication.instance()
    if app is None:
        return
    f = _Filter()
    app.installEventFilter(f)
    hb = QTimer()
    hb.setInterval(10)
    last = [time.monotonic()]

    def beat():
        now = time.monotonic()
        gap = now - last[0]
        last[0] = now
        if gap > 0.06:
            log("stall", gap=round(gap, 4))

    hb.timeout.connect(beat)
    hb.start()
    _installed = (f, hb)
    log("start")
