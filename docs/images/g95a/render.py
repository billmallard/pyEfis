"""Render digit-by-digit tuning on a numeric_display built from the knob
options of includes/mgl/v16/square-active-radio-display.yaml, through the
real Screen path (G95a, pyEfis #547). Basic style: DejaVu Sans Mono, blank
character a space. Writes one PNG per state and a strip, all here."""
import os
import sys

from PyQt6.QtGui import QImage, QPainter, QColor
from PyQt6.QtWidgets import QApplication, QWidget

# The in-memory FIX database the test suite uses (run from the repo root).
sys.path.insert(0, os.getcwd())
import tests.mock_db.client
import tests.mock_db.scheduler
sys.modules["pyavtools.fix.client"] = tests.mock_db.client
sys.modules["pyavtools.scheduler"] = tests.mock_db.scheduler
import pyavtools.fix as fix

app = QApplication(sys.argv)
fix.initialize({"main": {"FixServer": "localhost", "FixPort": "3490"}})
fix.db.define_item("COMACTFREQ1", "COM active", "float", 118.0, 136.975,
                   "MHz", 50000, "")
fix.db.set_value("COMACTFREQ1", 121.5)
it = fix.db.get_item("COMACTFREQ1")
it.bad = it.fail = it.old = False

import pyefis.hmi as hmi
from pyefis.screens.screenbuilder import Screen

hmi.initialize({})


class Parent(QWidget):
    def __init__(self, cfg):
        super().__init__()
        self._cfg = cfg
        self.config_path = ""
        self.nodeID = 1
        self.preferences = {
            "style": {"basic": True, "dseg": False, "segmented": False,
                      "ghost": False},
            "styles": {}, "gauges": {}, "enabled": {}, "includes": {},
            "buttons": {}}

    def get_config_item(self, child, key):
        return self._cfg.get(key)

    def getRunningScreen(self):
        return "TEST"


OPTS = {"clipping": True, "font_mask": "000.000",
        "font_family": "DejaVu Sans Mono", "decimal_places": 3,
        "dbkey": "COMACTFREQ1", "encoder_order": 400024,
        "encoder_multiplier": 0.025, "encoder_num_enforce_multiplier": True,
        "encoder_num_mask": "000.000"}
screen = Screen(Parent({
    "layout": {"rows": 7, "columns": 35},
    "instruments": [{"type": "numeric_display", "row": 0, "column": 0,
                     "span": {"rows": 7, "columns": 35}, "options": OPTS}],
    "encoder": None, "encoder_button": None, "encoder_timeout": None}))
screen.resize(420, 84)
screen.init_screen()
screen.show()
app.processEvents()
w = screen.instruments[0]
w.encoder_num_blink_timer.stop()   # drive the blink phase by hand
out = os.path.dirname(os.path.abspath(__file__))
frames = []


def grab(name, blink=None):
    if blink is not None:
        w.encoder_num_blink = blink
    w.update()
    app.processEvents()
    img = w.grab().toImage()
    img.save(os.path.join(out, name + ".png"))
    frames.append(img)
    print(name, repr(w.getValueText()))


grab("1-rest")
w.enc_select()
w.encoder_num_blink_timer.stop()
grab("2-push-blink-on", False)
grab("3-push-blink-off", True)
w.enc_changed(1)
grab("4-turn", False)
w.enc_clicked()
w.encoder_num_blink_timer.stop()
grab("5-push-next-digit", True)

h = sum(f.height() for f in frames) + 4 * (len(frames) - 1)
strip = QImage(frames[0].width(), h, QImage.Format.Format_RGB32)
strip.fill(QColor("#404040"))
p = QPainter(strip)
y = 0
for f in frames:
    p.drawImage(0, y, f)
    y += f.height() + 4
p.end()
strip.scaled(strip.width() * 2, strip.height() * 2).save(
    os.path.join(out, "strip-2x.png"))
