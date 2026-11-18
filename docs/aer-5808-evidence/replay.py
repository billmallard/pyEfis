#  SPDX-License-Identifier: GPL-2.0-or-later
"""Replay a real X-Plane autopilot session into the AFC4 strip (see README.md).

    python3 docs/aer-5808-evidence/replay.py <fix-gateway checkout>

The checkout's ``tests/plugins/xplane/data/afc2_c172_bf3a33402db4_raw.jsonl``
is the AFC2 adapter's own raw dataref log from sim-bench session
bf3a33402db4 (X-Plane 12.4.3, Laminar C172 G1000). Step 1 replays it through
the real adapter (``fixgw.plugins.xplane.autopilot``) on fix-gateway's
shipped database, the way that repo's playback test does, and records every
change of the keys the strip reads. Step 2 feeds those changes, in order and
on the session's own clock, to the real ``ap_annunciator`` and renders the
strip 0.25 s after each mode change (the flash's ON phase), and once more
after the flash ends. Writes replay.png here.
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
FGW = os.path.abspath(sys.argv[1])
RAW = os.path.join(FGW, "tests/plugins/xplane/data/afc2_c172_bf3a33402db4_raw.jsonl")

STRIP_KEYS = ("APENG", "YDENG", "APLAT", "APLATARM", "APVERT", "APVERTARM",
              "APALTCAP", "APALTREF", "APDISC", "VSSEL", "IASSEL", "ALTSEL")
MODE_KEYS = ("APENG", "APLAT", "APLATARM", "APVERT", "APVERTARM", "APDISC")


# -- step 1: the raw log through the real adapter ------------------------------

def replay_adapter():
    sys.path.insert(0, os.path.join(FGW, "src"))
    import fixgw.database as fdb
    import fixgw.plugin as plugin_base
    from fixgw.plugins.xplane import autopilot as ap

    fdb.init(os.path.join(FGW, "src/fixgw/config/database.yaml"))
    index = {name: ap.AP_RREF_BASE + i for i, (name, _d) in enumerate(ap.DATAREFS)}
    rows = [json.loads(line) for line in open(RAW)]
    t0 = rows[0]["t"]
    clock = [1000.0]
    adapter = ap.Autopilot(plugin_base.PluginBase("xplane", {}, {}),
                           lambda packet: None, clock=lambda: clock[0])
    timeline, last, state = [], None, {}
    for row in rows:
        clock[0] = 1000.0 + row["t"] - t0
        state.update(row["refs"])
        for name, value in state.items():
            adapter.feed(index[name], value)
        adapter.publish()
        adapter.poll()
        snap = {}
        for key in STRIP_KEYS:
            v = fdb.read(key)
            snap[key] = (v[0], bool(v[2]))
        if snap != last:
            timeline.append((row["t"] - t0, snap))
            last = snap
    return timeline


# -- step 2: the published keys into the real strip ----------------------------

def render(timeline, path):
    sys.path[:0] = [os.path.join(ROOT, "src"), ROOT]
    import tests.mock_db.client
    import tests.mock_db.scheduler
    sys.modules["pyavtools.fix.client"] = tests.mock_db.client
    sys.modules["pyavtools.scheduler"] = tests.mock_db.scheduler
    from PyQt6.QtCore import QRectF, Qt
    from PyQt6.QtGui import QColor, QFont, QImage, QPainter
    from PyQt6.QtWidgets import QApplication
    import pyavtools.fix as fix

    app = QApplication.instance() or QApplication(sys.argv)
    fix.initialize({"main": {"FixServer": "localhost", "FixPort": "3490"}})
    from tests.instruments.autopilot.conftest import AFC1_KEYS
    for key, dtype, lo, hi, tol in AFC1_KEYS:
        fix.db.define_item(key, key, dtype, lo, hi, "", tol, "")
    fix.db.define_item("ALTSEL", "ALTSEL", "int", -1000, 60000, "ft", 0, "")
    from pyefis.instruments.autopilot import fma

    clock = [0.0]

    def apply(snap):
        for key, (value, old) in snap.items():
            item = fix.db.get_item(key)
            item.value = value
            item.old, item.bad, item.fail = old, False, False

    # Mode changes, and one frame after the flash of the last of a burst ends.
    marks = []
    prev = None
    for t, snap in timeline:
        modes = tuple(snap[k][0] for k in MODE_KEYS)
        if modes != prev:
            marks.append(t)
            prev = modes
    frames = []
    def on_phase(t):
        # The flash blinks on the absolute clock (fma.BLINK_HALF_S): move to
        # the next ON half-second so a boxed mode shows its text.
        while int(t / fma.BLINK_HALF_S) % 2:
            t += fma.BLINK_HALF_S / 2
        return t

    for i, t in enumerate(marks):
        nxt = marks[i + 1] if i + 1 < len(marks) else t + 60
        ft = on_phase(t + 0.25)
        if ft < nxt:            # else the next change's own frame shows it
            frames.append(ft)
        if nxt - t > fma.DEFAULT_FLASH_S + 1:
            frames.append(t + fma.DEFAULT_FLASH_S + 0.75)

    apply(timeline[0][1])
    w = fma.ModeAnnunciator(clock=lambda: clock[0])
    W, H, LW = 640, 40, 520
    w.resize(W, H)
    rows, ti = [], 0
    for ft in frames:
        while ti < len(timeline) and timeline[ti][0] <= ft:
            clock[0] = timeline[ti][0]
            apply(timeline[ti][1])
            ti += 1
        clock[0] = ft
        app.processEvents()
        snap = timeline[ti - 1][1]
        img = QImage(W, H, QImage.Format.Format_ARGB32)
        img.fill(QColor("#1d3a5f"))
        # Children only, no palette background: the strip composites over
        # the attitude display on the glass, here a sky-blue ground.
        w.render(img, flags=type(w).RenderFlag.DrawChildren)
        ref = snap["APALTREF"][0]
        cap = "t=%5.1f  ALTSEL %5d  APALTREF %5d  VSSEL %+4d  IASSEL %3d" % (
            ft, snap["ALTSEL"][0], ref, snap["VSSEL"][0], snap["IASSEL"][0])
        rows.append((cap, img))
    sheet = QImage(LW + W + 20, len(rows) * (H + 8) + 8, QImage.Format.Format_ARGB32)
    sheet.fill(QColor("#202020"))
    p = QPainter(sheet)
    f = QFont("DejaVu Sans Mono")
    f.setPixelSize(13)
    for i, (cap, img) in enumerate(rows):
        y = 8 + i * (H + 8)
        p.setFont(f)
        p.setPen(QColor("#c0c0c0"))
        p.drawText(QRectF(8, y, LW - 8, H),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, cap)
        p.drawImage(LW, y, img)
    p.end()
    sheet.save(path)
    return len(rows)


if __name__ == "__main__":
    tl = replay_adapter()
    n = render(tl, os.path.join(HERE, "replay.png"))
    print("timeline", len(tl), "changes; wrote replay.png,", n, "rows")
