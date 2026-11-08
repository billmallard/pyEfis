#!/usr/bin/env python3
#  SPDX-License-Identifier: GPL-2.0-or-later
"""Evidence for G66 (billmallard/pyEfis#392): the HSI under each failure it
annunciates -- a fail-only CDI, a failed COURSE, a failed HEAD and a failed
glideslope.

The real ``HSI`` widget with the in-memory mock FIX database from
render_instrument.py, on a GPS source (magenta), heading 000, course 045, CDI
at its failed value of 0, a glideslope expected (GSV = 1) and GSI at 0. Each scene sets the quality flags through the
widget's own setters, then grabs the viewport, which is the HSI's paint
surface. Run it from the repo root on each checkout being compared::

    QT_QPA_PLATFORM=offscreen python docs/aer-5028-evidence/render_g66.py OUTDIR

Writes ``<OUTDIR>/<orientation>_<scene>.png``.
"""

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (_REPO, os.path.join(_REPO, "src"), os.path.join(_REPO, "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import render_instrument as ri  # noqa: E402  (mock FIX swap happens here)

from PyQt6.QtWidgets import QApplication  # noqa: E402

W, H = 360, 400

# scene: (CDI old, bad, fail), (COURSE bad, fail), HEAD fail, GSI fail
_OK3 = (False, False, False)
SCENES = {
    "valid": (_OK3, (False, False), False, False),
    "cdi_fail_only": ((False, False, True), (False, False), False, False),
    "course_fail": (_OK3, (False, True), False, False),
    "head_fail": (_OK3, (False, False), True, False),
    "gs_fail": (_OK3, (False, False), False, True),
}


def _settle(app):
    for _ in range(20):
        app.processEvents()
        time.sleep(0.01)


def main(out_dir):
    app = QApplication.instance() or QApplication(sys.argv[:1])
    ri._load_fonts()
    ri._setup_fix()
    from pyefis.instruments import hsi
    os.makedirs(out_dir, exist_ok=True)
    for orientation in ("heading_up", "arc"):
        for name, (cdi, crs, head_fail, gsi_fail) in SCENES.items():
            w = hsi.HSI(cdi_enabled=True, gsi_enabled=True)
            w.orientation = orientation
            w.resize(W, H)
            w.show()
            _settle(app)
            w.setNavsrc(2)                       # GPS: magenta
            w.setCdiv(1)                         # receiving (the mock's 0 = no signal)
            w.setGsv(1)                          # glideslope expected
            w.setGsiOld(False); w.setGsiBad(False); w.setGsiFail(gsi_fail)
            w._glideSlopeIndicator = 0.0
            w.setHeadOld(False); w.setHeadBad(False); w.setHeadFail(head_fail)
            w._heading = 0.0
            w._courseDeviation = 0.0             # the failed value
            w.setCourseBad(crs[0]); w.setCourseFail(crs[1])
            # A failed COURSE reads 000; a valid one 045.
            w._courseSelect = 0.0 if (crs[0] or crs[1]) else 45.0
            w.setCdiOld(cdi[0]); w.setCdiBad(cdi[1]); w.setCdiFail(cdi[2])
            w.update()
            _settle(app)
            path = os.path.join(out_dir, f"{orientation}_{name}.png")
            w.viewport().grab().save(path)
            print(path)
            w.close()
            w.deleteLater()
            _settle(app)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "out")
