"""INS6 (AER-6684): flag-state render comparison, run on two trees.

For every widget whose flag subscription INS6 moves onto ``BugBinding``, walk
each FIX key through old, bad and fail (on, then off), a combined state, and a
value change. After every step record:

- ``sync``: paint events delivered before control returns from the flag
  write (a ``repaint()`` slot paints here, an ``update()`` slot does not);
- ``async``: paint events delivered by the next ``processEvents``;
- ``md5``: a hash of ``grab()`` -- what the widget draws in that state.

The result is a JSON file. Run it on ``dev`` and on the INS6 branch and diff
the two files; see README.md beside this file for the exact commands.

Not a collected test (the name matches no pytest pattern): pass the path to
pytest explicitly, with ``INS6_OUT`` naming the output file.
"""
import hashlib
import json
import os
import types

from PyQt6.QtCore import QBuffer, QEvent, QIODevice, QObject
from PyQt6.QtWidgets import QApplication, QGraphicsView

import pyefis.hmi as hmi
from pyefis.instruments import airspeed, altimeter, nav_status, tc, vsi

_NAV = {"FPLSTATE": ("int", 1), "FPLPHASE": ("str", "TERM"),
        "WPFROM": ("str", "KSBA"), "WPNAME": ("str", "GVO"),
        "WPNEXT": ("str", "RZS"), "WPDIS": ("float", 12.43),
        "WPETE": ("int", 372)}


class _PaintCounter(QObject):
    def __init__(self, targets):
        super().__init__()
        self.n = 0
        for t in targets:
            t.installEventFilter(self)

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.Paint:
            self.n += 1
        return False


def _nav_keys(fix):
    for key, (dtype, value) in _NAV.items():
        lo, hi = {"float": (0.0, 1e6), "int": (0, 1_000_000),
                  "str": (None, None)}[dtype]
        fix.db.define_item(key, key, dtype, lo, hi, "", 0, "")
        fix.db.set_value(key, value)


def _tc():
    w = tc.TurnCoordinator()
    # resizeEvent reads its config through the screen parent
    w.myparent = types.SimpleNamespace(get_config_item=lambda key: None)
    return w


WIDGETS = {
    "Airspeed": (lambda fix: airspeed.Airspeed(), ["IAS"], (300, 300)),
    "Airspeed_Tape": (lambda fix: airspeed.Airspeed_Tape(show_trend=False),
                      ["IAS", "TAS"], (120, 400)),
    "Airspeed_Box": (lambda fix: (hmi.initialize({}), airspeed.Airspeed_Box())[1],
                     ["TAS", "GS", "IAS"], (160, 60)),
    "Altimeter": (lambda fix: altimeter.Altimeter(), ["ALT"], (300, 300)),
    "Altimeter_Tape": (lambda fix: altimeter.Altimeter_Tape(show_trend=False),
                       ["ALT", "BARO"], (120, 400)),
    "VSI_Dial": (lambda fix: vsi.VSI_Dial(), ["VS"], (300, 300)),
    "VSI_PFD": (lambda fix: vsi.VSI_PFD(), ["VS"], (80, 400)),
    "TurnCoordinator": (lambda fix: _tc(), ["ALAT", "ROT"],
                        (300, 300)),
    "NavStatus": (lambda fix: nav_status.NavStatus(),
                  list(_NAV), (400, 40)),
}


def _md5(widget):
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    widget.grab().toImage().save(buf, "PNG")
    return hashlib.md5(bytes(buf.data())).hexdigest()


def _walk(fix, qtbot, name):
    make, keys, size = WIDGETS[name]
    if name == "NavStatus":
        _nav_keys(fix)
    for key in keys:
        item = fix.db.get_item(key)
        item.old = item.bad = item.fail = False
    w = make(fix)
    qtbot.addWidget(w)
    w.resize(*size)
    w.show()
    qtbot.waitExposed(w)
    targets = [w] + ([w.viewport()] if isinstance(w, QGraphicsView) else [])
    pc = _PaintCounter(targets)
    app = QApplication.instance()
    for _ in range(3):
        app.processEvents()
    steps = []

    def step(label, action):
        pc.n = 0
        action()
        sync = pc.n
        for _ in range(3):
            app.processEvents()
        steps.append({"step": label, "sync": sync, "async": pc.n - sync,
                      "md5": _md5(w)})
        app.processEvents()

    for key in keys:
        item = fix.db.get_item(key)
        for flag in ("old", "bad", "fail"):
            step(f"{key}.{flag}=1", lambda f=flag: setattr(item, f, True))
            step(f"{key}.{flag}=0", lambda f=flag: setattr(item, f, False))
        step(f"{key}.old+bad", lambda: (setattr(item, "old", True),
                                        setattr(item, "bad", True)))
        step(f"{key}.clear", lambda: (setattr(item, "old", False),
                                      setattr(item, "bad", False)))
        step(f"{key}.annunciate=1", lambda: setattr(item, "annunciate", True))
        step(f"{key}.annunciate=0", lambda: setattr(item, "annunciate", False))
    return steps


def test_flag_render_walk(fix, qtbot):
    out = {name: _walk(fix, qtbot, name) for name in WIDGETS}
    with open(os.environ["INS6_OUT"], "w") as f:
        json.dump(out, f, indent=1, sort_keys=True)
