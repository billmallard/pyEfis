"""Render the airspeed tape's V-speed bands for pyEfis #396 (AER-5143).

Usage: QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python render_tape.py OUT.png [--no-vs]
Run from the repo root. Vs1=56, Vs0=48, Vfe=85, Vno=140, Vne=180 kt; IAS 65 kt.
"""
import sys

import tests.mock_db.client
import tests.mock_db.scheduler

sys.modules["pyavtools.fix.client"] = tests.mock_db.client
sys.modules["pyavtools.scheduler"] = tests.mock_db.scheduler

import pyavtools.fix as fix
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)
fix.initialize({"main": {"FixServer": "localhost", "FixPort": "3490"}})
fix.db.define_item("IAS", "IAS", "float", 0, 2000.0, "knots", 50000,
                   "Min,Max,V1,V2,Vne,Vfe,Vmc,Va,Vno,Vs,Vs0,Vx,Vy")
fix.db.define_item("TAS", "TAS", "float", 0, 2000.0, "knots", 50000, "")
fix.db.set_value("TAS", 70)
ias = fix.db.get_item("IAS")
fix.db.set_value("IAS", 65)
ias.bad = ias.fail = False
ias.old = False
for k, v in {"Vs": None if "--no-vs" in sys.argv else 56.0, "Vs0": 48.0,
             "Vfe": 85.0, "Vno": 140.0, "Vne": 180.0}.items():
    ias.set_aux_value(k, v)

from pyefis.instruments import airspeed

w = airspeed.Airspeed_Tape()
w.resize(140, 480)
w.show()
for _ in range(5):
    app.processEvents()
w.setAirspeed(65)
app.processEvents()
w.grab().save(sys.argv[1])
