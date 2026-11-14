"""G82 reproducer: does a flushed frame wait for the next unrelated repaint?

A fullscreen window shaped like the pyEfis panel: a QGraphicsView whose
viewport is a QOpenGLWidget (as the AI/SVS), a plain raster "pane" that
toggles black/white (the tapped widget), and a clock label repainted once a
second (the stale-data background repaint). Each toggle and each top-level
flush is logged with time.time(); recorder.py times the X image.

argv: out.jsonl n_toggles [options]
  --no-gl        no QOpenGLWidget anywhere (pure raster backing store)
  --windowed     a normal 1600x900 window instead of fullscreen
  --gl-anim      the GL view repaints continuously at 30 Hz (live-data case)
  --fix=repaint  toggle with pane.repaint() instead of pane.update()
  --fix=kick     after a flush, one follow-up window flush 1 frame later
  --swap=N       QSurfaceFormat default swapInterval N
  --double=MS    a tap: flush a small "pressed" highlight first, then toggle
                 the pane MS later (press, then release + page change)
"""
import json, random, sys, time
from PyQt6.QtCore import Qt, QTimer, QEvent, QObject, QRectF
from PyQt6.QtGui import QPainter, QColor, QSurfaceFormat
from PyQt6.QtWidgets import (QApplication, QWidget, QHBoxLayout, QVBoxLayout,
                             QLabel, QGraphicsView, QGraphicsScene)

out, N = sys.argv[1], int(sys.argv[2])
opts = sys.argv[3:]
NO_GL = "--no-gl" in opts
WINDOWED = "--windowed" in opts
GL_ANIM = "--gl-anim" in opts
FIX = next((o.split("=", 1)[1] for o in opts if o.startswith("--fix=")), None)
DOUBLE = next((int(o.split("=", 1)[1]) for o in opts if o.startswith("--double=")), None)
SWAP = next((int(o.split("=", 1)[1]) for o in opts if o.startswith("--swap=")), None)

if SWAP is not None:
    f = QSurfaceFormat.defaultFormat(); f.setSwapInterval(SWAP)
    QSurfaceFormat.setDefaultFormat(f)
QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
app = QApplication(sys.argv[:1])
log = open(out, "w", buffering=1)
def rec(k, **kw):
    kw.update(k=k, w=round(time.time(), 4)); log.write(json.dumps(kw) + "\n")


class Pane(QWidget):
    def __init__(self):
        super().__init__(); self.on = False
    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(255, 255, 255) if self.on else QColor(0, 0, 0))
        p.end(); rec("paint", on=self.on)


class Flush(QObject):
    """Times the top-level UpdateRequest (repaint + flush) by delivering it."""
    def __init__(self, win):
        super().__init__(); self.win = win; self.busy = False
        self.kick = QTimer(); self.kick.setSingleShot(True); self.kick.setInterval(17)
        self.kick.timeout.connect(self._kick); self.kicking = False
    def eventFilter(self, obj, ev):
        if obj is self.win and ev.type() == QEvent.Type.UpdateRequest and not self.busy:
            self.busy = True; t0 = time.time()
            obj.event(ev)
            rec("flush", dur=round(time.time() - t0, 4), kick=self.kicking)
            self.busy = False
            if FIX == "kick":
                if self.kicking:
                    self.kicking = False
                else:
                    self.kick.start()
            return True
        return False
    def _kick(self):
        self.kicking = True
        # 1x1 dirty rect on the clock: forces one more compose + swap
        clock.update(0, 0, 1, 1)


win = QWidget(); win.setStyleSheet("background:#203040; color:white;")
lay = QHBoxLayout(win)
if not NO_GL:
    from PyQt6.QtOpenGLWidgets import QOpenGLWidget
    view = QGraphicsView(); scene = QGraphicsScene(0, 0, 800, 800)
    item = scene.addRect(QRectF(100, 100, 300, 300), brush=QColor(120, 80, 40))
    view.setScene(scene)
    glw = QOpenGLWidget(); fmt = QSurfaceFormat(); fmt.setSamples(2); glw.setFormat(fmt)
    view.setViewport(glw)
    view.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
    lay.addWidget(view, 3)
    if GL_ANIM:
        anim = QTimer(); anim.setInterval(33)
        anim.timeout.connect(lambda: item.setRotation((item.rotation() + 1) % 360))
        anim.start()
right = QVBoxLayout(); lay.addLayout(right, 2)
clock = QLabel("--"); clock.setFixedHeight(60); right.addWidget(clock)
btn = QLabel("btn"); btn.setFixedHeight(60); right.addWidget(btn)
pane = Pane(); right.addWidget(pane, 1)
tick = QTimer(); tick.setInterval(1000)
tick.timeout.connect(lambda: clock.setText(time.strftime("%H:%M:%S"))); tick.start()
flt = Flush(win); win.installEventFilter(flt)

state = {"i": 0}
rng = random.Random(5478)
def toggle():
    i = state["i"]
    if i >= N:
        rec("end"); app.quit(); return
    state["i"] = i + 1
    if DOUBLE is not None:
        btn.setStyleSheet("background:#%s;" % ("c0c000" if i % 2 else "00c0c0"))
        rec("press", i=i)
        QTimer.singleShot(DOUBLE, lambda: flip(i))
    else:
        flip(i)
    QTimer.singleShot(int(rng.uniform(1.2, 2.5) * 1000), toggle)

def flip(i):
    pane.on = not pane.on
    rec("toggle", i=i, on=pane.on)
    if FIX == "repaint":
        pane.repaint()
    else:
        pane.update()

def started():
    g = pane.mapToGlobal(pane.rect().center())
    rec("start", px=g.x(), py=g.y(), opts=opts, platform=app.platformName(),
        qt=__import__("PyQt6.QtCore").QtCore.QT_VERSION_STR)
    QTimer.singleShot(3000, toggle)

if WINDOWED:
    win.setGeometry(100, 80, 1600, 900); win.show()
else:
    win.showFullScreen()
QTimer.singleShot(1500, started)
app.exec()
