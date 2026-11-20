#  SPDX-License-Identifier: GPL-2.0-or-later
"""Boot pyEfis the way the service does, against the fake FIX database, and report.

Run as a child process by the core checks, never imported by pytest, so that
``sys.modules`` starts empty and holds only what the boot itself loaded:

    python tests/safety/boot_probe.py --config DIR --out result.json [--writes] [--drive]

--config DIR is a complete pyEfis config directory (default.yaml beside a
preferences.yaml). It runs ``pyefis.main.main()`` with ``--config-file DIR/default.yaml``
under the offscreen Qt platform, with the same fake FIX client the test suite uses
(conftest.py), so no gateway is needed. A key the boot asks for and the fake database
does not hold is defined on first use, as a gateway would have defined it.

``QApplication.exec`` is replaced by a short event loop, so ``main()`` returns after the
screens have been built and shown.

The result file holds:
  modules -- every name in sys.modules after the boot (the runtime import check, R4).
  screens -- the instrument classes each screen built, so a boot that built nothing
             cannot pass for a clean one.
  writes  -- with --writes, every write to the FIX database made from pyefis code: the key,
             the writing module's repository path and line (the innermost pyefis frame),
             every pyefis module on the call stack, and how (value or output). A write is
             recorded at the database item itself, so every route -- a widget, an HMI
             action, a button, the encoder -- is seen the same way (the R5 audit).
  driven  -- with --drive, what the pilot-input sweep did (see drive()).
  errors  -- exceptions that escaped a Qt slot while driving; the boot carries on.

--src points the boot at a copy of the source tree (DIR/pyefis), which is how the
checks plant a violation without touching the repository.
"""

import argparse
import json
import os
import pathlib
import sys
import traceback

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "src"  # --src replaces it: a copy of the source with a planted violation


def install_fake_fix():
    """The fake client and scheduler the suite uses (conftest.py), and keys on demand."""
    sys.path[:0] = [str(SRC), str(ROOT)]
    import tests.mock_db.client
    import tests.mock_db.scheduler
    sys.modules["pyavtools.fix.client"] = tests.mock_db.client
    sys.modules["pyavtools.scheduler"] = tests.mock_db.scheduler

    class Scheduler(tests.mock_db.scheduler.ScheduleThread):
        """A timer for any interval asked for. Its callbacks never fire."""

        def getTimer(self, interval):
            for t in self.timers:
                if t.interval == interval:
                    return t
            self.timers.append(tests.mock_db.scheduler.IntervalTimer(interval))
            return self.timers[-1]

    tests.mock_db.scheduler.scheduler = Scheduler()
    import pyavtools.fix as fix

    orig = fix.Database.get_item

    def get_item(self, key, create=False, wait=True):
        try:
            return orig(self, key, create, wait)
        except KeyError:
            up = str(key).upper()
            if up.startswith(("TSBTN", "BTN", "EGTBTN")) or "BUTTON" in up:
                self.define_item(key, key, "bool", None, None, "", 50000, "")
            else:
                self.define_item(key, key, "float", 0, 100, "", 50000,
                                 "Min,Max,lowWarn,lowAlarm,highWarn,highAlarm")
            item = orig(self, key, create, wait)
            item.bad = item.fail = item.old = False
            return item

    fix.Database.get_item = get_item
    # An aux the gateway has not reported reads as unset (None), as for a declared aux
    # whose value has not arrived, rather than raising.
    fix.DB_Item.get_aux_value = lambda self, name: self.aux.get(name)
    return fix


def _pyefis_frames(frames):
    """(repository path, line) of every frame in pyefis source, outermost first."""
    out = []
    for f in frames:
        path = pathlib.Path(f.filename).resolve()
        try:
            rel = path.relative_to(SRC.parent)
        except ValueError:
            continue
        if rel.parts[:2] == ("src", "pyefis"):
            out.append((rel.as_posix(), f.lineno))
    return out


def record_writes(fix, writes):
    """Wrap DB_Item's value setter and output_value so each write names its writer."""
    item_cls = fix.DB_Item
    prop = item_cls.value
    orig_output = item_cls.output_value

    def note(key, how):
        chain = _pyefis_frames(traceback.extract_stack()[:-2])
        if chain:
            writes.append({"key": key, "writer": chain[-1][0], "line": chain[-1][1],
                           "how": how, "stack": sorted({p for p, _ in chain})})

    def set_value(self, x):
        note(self.key, "value")
        prop.fset(self, x)

    def output_value(self):
        note(self.key, "output")
        return orig_output(self)

    item_cls.value = property(prop.fget, set_value)
    item_cls.output_value = output_value


GRID = (0.03, 0.2, 0.5, 0.8, 0.97)


def drive(app, gui, driven):
    """Pilot inputs on every screen: buttons, the knob walk, and taps.

    For each screen in turn: show it, click every pyefis Button on it once, turn the
    knob through every encoder-selectable instrument (on each one push, one detent each
    way, push again), then tap a grid over every instrument and work the knob on
    whatever the tap focused. Each step drains the event loop. This exercises the write
    paths the shipped config wires to pilot controls, so the write audit sees them, not
    only the writes a boot makes. It reaches what these inputs reach and no more: a
    path behind a long press, a drag, a timer or a gateway reply is not driven.
    """
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QAbstractButton, QAbstractScrollArea
    from pyefis.instruments.button import Button

    def home(idx):
        # A screen-change button or tap moves away; come back before the next input.
        app.processEvents()
        if gui.mainWindow.running_screen != idx:
            gui.mainWindow.showScreen(idx)
            app.processEvents()

    for idx, scr in enumerate(gui.screens):
        obj = scr.object
        if obj is None:
            continue
        gui.mainWindow.showScreen(idx)
        app.processEvents()
        clicks = 0
        for b in obj.findChildren(Button):
            for qb in b.findChildren(QAbstractButton):
                qb.click()
                home(idx)
                clicks += 1
        # The knob walk, through the same slots the encoder FIX keys drive.
        stops = 0
        if hasattr(obj, "encoderChanged") and obj.encoder_list_sorted:
            for _ in range(len(obj.encoder_list_sorted)):
                obj.encoderChanged(1)            # walk to the next instrument
                obj.encoderButtonChanged(True)   # push: take control
                obj.encoderButtonChanged(False)
                obj.encoderChanged(1)            # one detent each way
                obj.encoderChanged(-1)
                obj.encoderButtonChanged(True)   # push again
                obj.encoderButtonChanged(False)
                home(idx)
                stops += 1
        # Touch: a 5 x 5 grid of taps over every instrument, edges included, each
        # followed by a knob detent each way on the inner and outer ring and a push,
        # then focus released. A tap lands on whatever box is under it (the baro box
        # along a tape's bottom edge, a value box on the autopilot head), as a pilot's
        # finger would. A scroll area (the tapes, the HSI) takes it on its viewport.
        taps = 0
        ctl = getattr(obj, "encoder_controller", None)
        for inst in list((getattr(obj, "instruments", None) or {}).values()):
            try:
                if not inst.isVisible():
                    continue
                target = inst.viewport() if isinstance(inst, QAbstractScrollArea) else inst
                w, h = target.width(), target.height()
            except RuntimeError:
                continue
            for fx in GRID:
                for fy in GRID:
                    try:
                        QTest.mouseClick(target, Qt.MouseButton.LeftButton,
                                         Qt.KeyboardModifier.NoModifier,
                                         QPoint(int(w * fx), int(h * fy)))
                    except RuntimeError:
                        break
                    if ctl is not None:
                        ctl.wheel_turn(1)
                        ctl.wheel_turn(-1)
                        ctl.wheel_turn(1, outer=True)
                        ctl.wheel_turn(-1, outer=True)
                        ctl.wheel_push(True)
                        ctl.wheel_push(False)
                        ctl.release_focus()
                    home(idx)
                    taps += 1
        driven.append({"screen": scr.name, "button_clicks": clicks, "knob_stops": stops,
                       "taps": taps})


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--writes", action="store_true")
    ap.add_argument("--drive", action="store_true")
    ap.add_argument("--settle-ms", type=int, default=500)
    ap.add_argument("--src", help="source root holding pyefis/ (default: this repository's src)")
    args = ap.parse_args(argv)
    global SRC
    if args.src:
        SRC = pathlib.Path(args.src).resolve()

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    fix = install_fake_fix()
    writes, driven, errors = [], [], []

    def excepthook(kind, value, tb):
        # PyQt6 aborts the process on an exception escaping a slot unless a hook is
        # set. A driven input can raise (a shipped button names a screen that is not
        # loaded); keep going and report it.
        errors.append("".join(traceback.format_exception_only(kind, value)).strip())

    sys.excepthook = excepthook
    if args.writes:
        record_writes(fix, writes)

    from PyQt6.QtCore import QElapsedTimer
    from PyQt6.QtWidgets import QApplication

    import pyefis.main
    import pyefis.gui as gui
    pyefis.main.gui.BOOT_GROUND_WAIT_S = 0

    snapshot = {}

    def short_exec(app_self=None):
        # The running app: let it settle, drive it if asked, then record what it holds.
        app = QApplication.instance()
        t = QElapsedTimer()
        t.start()
        while t.elapsed() < args.settle_ms:
            app.processEvents()
        if args.drive:
            drive(app, gui, driven)
        snapshot["modules"] = sorted(sys.modules)
        snapshot["writes"] = list(writes)
        snapshot["screens"] = {
            scr.name: sorted({"%s.%s" % (type(i).__module__, type(i).__name__)
                              for i in (getattr(scr.object, "instruments", None) or {}).values()})
            for scr in gui.screens}
        return 0

    QApplication.exec = short_exec
    sys.argv = ["pyEfis", "--config-file", os.path.join(args.config, "default.yaml")]
    try:
        pyefis.main.main()
    except BaseException:
        # Shutdown after exec() is not under test (the fake scheduler has no stop());
        # a failure before exec() leaves no snapshot and is reported as one.
        if not snapshot:
            traceback.print_exc()
    import pyefis
    result = {"status": "ok" if snapshot else "boot failed before the event loop",
              "pyefis": str(pathlib.Path(pyefis.__file__).resolve()),
              "modules": snapshot.get("modules", []), "writes": snapshot.get("writes", []),
              "screens": snapshot.get("screens", {}),
              "driven": driven, "errors": errors}
    pathlib.Path(args.out).write_text(json.dumps(result, indent=1), encoding="utf-8")
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)  # the fake client's threads would otherwise hold the process open


if __name__ == "__main__":
    main()
