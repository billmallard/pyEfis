#!/usr/bin/env python3
#  SPDX-License-Identifier: GPL-2.0-or-later
"""FP5c evidence renderer: the flight_plan encoder focus ring (AER-810, #188).

Run from the root of a pyEfis checkout of the branch under review:

  render_evidence.py <outdir> [WxH]

Drives the real widget through the enc_* protocol only (enc_highlight /
enc_select / enc_changed / enc_clicked -- no touch, no keyboard) and writes
one PNG per state plus a captioned 4-up strip, ``fp_encoder_4up.png``:

  1_fpl_row_focused   FPL page, knob turned twice: second row focused
  2_row_menu          push on that row, then turn to Activate Leg
  3_entry_editing     ADD WPT by knob, "KS" dialled in: the cursor sits on
                      the blank after S and FastFind shows the cyan "BA"
  4_dto_shortcut      push with nothing focused: Direct To on the active
                      waypoint with ACTIVATE focused (second push activates)

Environment: QT_QPA_PLATFORM=offscreen. The FIX db is the test harness's
in-memory one (tests.mock_db), as docs/images/fp_font_scale/render_evidence.py
does -- the real client starts a non-daemon network thread. The fixture
waypoint index is the one the unit tests use (KSBA, KSMX, GVO).
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.getcwd()
for _p in (ROOT, os.path.join(ROOT, "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from PyQt6.QtCore import QRect, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter, QPen  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

_FONT_DIRS = ("C:/Windows/Fonts", "/usr/share/fonts/truetype/dejavu")


def _load_fonts():
    # Condensed faces only -- see fp_font_scale/render_evidence.py.
    for d in _FONT_DIRS:
        if os.path.isdir(d):
            for name in sorted(os.listdir(d)):
                if name.lower().startswith("dejavusanscondensed"):
                    QFontDatabase.addApplicationFont(os.path.join(d, name))


def main(outdir, size="657x1003"):
    app = QApplication.instance() or QApplication(sys.argv)
    _load_fonts()
    import tests.mock_db.client
    import tests.mock_db.scheduler
    sys.modules["pyavtools.fix.client"] = tests.mock_db.client
    sys.modules["pyavtools.scheduler"] = tests.mock_db.scheduler
    import pyavtools.fix as fix
    fix.initialize({"main": {"FixServer": "localhost", "FixPort": "3490"}})

    from pyefis.flightplan import model as fp_model
    from pyefis.instruments import flight_plan
    from tests.instruments.flight_plan import test_flight_plan as base

    base._define_all_fp1_keys(fix)
    w_px, h_px = (int(v) for v in size.split("x"))
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)

    def widget():
        w = flight_plan.FlightPlan(None)
        w.resize(w_px, h_px)
        base._install_index(w, base._build_fixture_index(Path(tempfile.mkdtemp())))
        w._aircraft_position = lambda: (34.45, -119.9)
        return w

    def plan():
        return fp_model.FlightPlan(name="KSBA-KSMX", waypoints=[
            fp_model.Waypoint(id="KSBA", type="airport", lat=34.42621, lon=-119.84037),
            fp_model.Waypoint(id="GVO", type="vor", lat=34.53142, lon=-120.09106),
            fp_model.Waypoint(id="KSMX", type="airport", lat=34.89892, lon=-120.45758),
        ])

    def take(w):
        w.enc_highlight(True)
        w.enc_select()

    shots = []

    def shot(w, name, caption):
        img = w.grab().toImage()
        path = out / f"{name}.png"
        img.save(str(path))
        shots.append((img, caption))
        print("wrote", path)

    w = widget()
    w._plan = plan()
    w._commit()
    take(w)
    w.enc_changed(1)
    w.enc_changed(1)
    shot(w, "1_fpl_row_focused", "1  FPL: turn x2, row GVO focused")

    w.enc_clicked()
    labels = [label for label, _a in flight_plan._ROW_MENU_ITEMS]
    w.enc_changed(labels.index("Activate Leg"))
    shot(w, "2_row_menu", "2  push, turn: Activate Leg")

    w = widget()
    w._plan = fp_model.FlightPlan()   # the bus still holds shot 1's plan
    w._commit()
    take(w)
    w.enc_changed(1)             # empty plan: first soft key, ADD WPT
    w.enc_clicked()
    cs = flight_plan.ENC_CHARSET
    for ch in "KS":
        w.enc_changed((cs.index(ch) - cs.index(" ")) % len(cs))
        w.enc_clicked()
    shot(w, "3_entry_editing", "3  Entry: KS dialled, push accepts KSBA")

    w = widget()
    w._plan = plan()
    w._commit()
    fix.db.set_value("FPLACTLEG", 2)
    w._sync_engine_from_bridge()
    take(w)
    w.enc_clicked()
    shot(w, "4_dto_shortcut", "4  push, nothing focused: DTO GVO, ACTIVATE")

    cap_h = 40
    strip = QImage(w_px * len(shots), h_px + cap_h, QImage.Format.Format_RGB32)
    strip.fill(QColor("#202020"))
    p = QPainter(strip)
    f = QFont("DejaVu Sans Condensed")
    f.setPixelSize(22)
    p.setFont(f)
    for i, (img, caption) in enumerate(shots):
        p.drawImage(i * w_px, cap_h, img)
        p.setPen(QPen(QColor("#ffffff")))
        p.drawText(QRect(i * w_px, 0, w_px, cap_h), Qt.AlignmentFlag.AlignCenter, caption)
    p.end()
    strip.save(str(out / "fp_encoder_4up.png"))
    print("wrote", out / "fp_encoder_4up.png")
    del app


if __name__ == "__main__":
    main(*sys.argv[1:])
