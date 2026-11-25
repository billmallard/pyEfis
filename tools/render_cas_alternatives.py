"""Evidence renders for the CAS marker on the alternative layouts (AER-6602).

Builds each portrait and left-buttons screen file whole, through the real
screen builder (``Screen.init_screen``, shipped preferences, includes
expanded), with the mock FIX db from ``render_instrument`` and the demo CAS
list (AP LINK LOST red, unacknowledged), so the marker shows WARNING; it
flashes, so a grab catches it filled or outlined. Portrait files render at
600 x 1024, left-buttons files at 1024 x 600.
Writes ``<file stem>.png`` per screen file to the output directory. Name
screen files after OUTDIR to render those instead (``pfd.yaml`` for the stock
reference).

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python3 tools/render_cas_alternatives.py OUTDIR [FILE ...]
"""

import os
import sys
import time

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "src"))

from tools import render_instrument as ri  # noqa: E402  (installs the mock FIX db)

import yaml  # noqa: E402
from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402

import pyefis  # noqa: E402
import pyefis.cfg as cfg  # noqa: E402
from pyefis.main import merge_dict  # noqa: E402

CONFIG = os.path.join(os.path.dirname(pyefis.__file__), "config")
FILES = [
    "pfd-portrait.yaml", "ems-portrait.yaml", "ems2-portrait.yaml",
    "radio-portrait.yaml", "pfd-left-buttons.yaml", "ems-left-buttons.yaml",
    "ems2-left-buttons.yaml", "radio-left-buttons.yaml",
]


def _preferences():
    with open(os.path.join(CONFIG, "preferences.yaml")) as f:
        prefs = yaml.safe_load(f)
    custom = os.path.join(CONFIG, "preferences.yaml.custom")
    if os.path.exists(custom):
        with open(custom) as f:
            merge_dict(prefs, yaml.safe_load(f) or {})
    return prefs


class _Parent(QWidget):
    def __init__(self, screen_config, preferences):
        super().__init__()
        self._screen_config = screen_config
        self.config_path = CONFIG
        self.nodeID = 1
        self.preferences = preferences

    def get_config_item(self, child, key):
        return self._screen_config.get(key)

    def getRunningScreen(self):
        return "TEST"


def _settle(app, seconds=1.5):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


def render(app, fname, outdir):
    from pyefis.screens.screenbuilder import Screen
    prefs = _preferences()
    loaded = cfg.from_yaml(os.path.join(CONFIG, "screens", fname),
                           bpath=CONFIG, preferences=prefs)
    (name, sc), = [(k, v) for k, v in loaded.items()
                   if isinstance(v, dict) and "instruments" in v]
    w, h = (600, 1024) if "portrait" in fname else (1024, 600)
    parent = _Parent(sc, prefs)
    parent.resize(w, h)
    screen = Screen(parent)
    screen.resize(w, h)
    screen.screenName = name  # buttons read it, as gui.py sets it
    screen.init_screen()
    parent.show()
    screen.show()
    _settle(app)
    out = os.path.join(outdir, fname[:-len(".yaml")] + ".png")
    screen.grab().save(out)
    parent.close()
    print(name, fname, "->", out)


def main(outdir, files=FILES):
    os.makedirs(outdir, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    ri._load_fonts()
    ri._setup_fix()
    ri._demo_cas("cas_marker")
    # The display-state timer: any interval, callbacks never fire (as in
    # tests/safety/boot_probe.py), so each screen stays in display state 1.
    import pyavtools.scheduler as scheduler  # the mock, once ri is imported

    class _Scheduler(scheduler.ScheduleThread):
        def getTimer(self, interval):
            for t in self.timers:
                if t.interval == interval:
                    return t
            self.timers.append(scheduler.IntervalTimer(interval))
            return self.timers[-1]

    scheduler.scheduler = _Scheduler()
    import pyefis.hmi as hmi
    if hmi.actions is None:
        hmi.initialize({})
    for fname in files:
        render(app, fname, outdir)


if __name__ == "__main__":
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "out"
    names = sys.argv[2:] or FILES
    if len(names) == 1:
        main(out_dir, names)
    else:
        # One process per screen: the CAS model is shared process-wide, so a
        # screen rendered after another would see the first one's aged state.
        import subprocess
        for n in names:
            subprocess.run([sys.executable, __file__, out_dir, n], check=True)
