#!/usr/bin/env python3
"""AER-4457 / MP13 evidence: grab the moving map MID-PINCH, 10 -> 40 NM,
after the 40 NM rung has rendered once, and count the dark-fill pixels.

Reuses tools/bench_map_gestures.py for everything (mock FIX bus, widget
construction, event pacing, the MP1 gesture bracket), so the pinch runs
through the widget's own gating exactly as the bench scenarios do. The only
addition is a warm-up at 40 NM before the pinch, and a widget.grab() at
chosen points during the gesture.

Run from a pyEfis checkout root (the checkout under test):

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src:tools python3 \\
        docs/aer-4457-evidence/pinch_out_frames.py --out DIR \\
        --tile-path /data/makerplane-data/terrain/tiles \\
        --water-db /data/makerplane-data/water/current/water.sqlite \\
        --highway-db /data/makerplane-data/highways/current/highways.sqlite

Writes DIR/frame_<range>nm.png for each grab, and prints one JSON object:
per-frame dark-fill fraction plus paint-time stats over the gesture (every
paint while the fingers are down, the grabs included).
"""
import json
import sys
import time
from pathlib import Path

import bench_map_gestures as bmg

#: MovingMap.paintEvent's background fill -- what a bare edge shows.
DARK = (16, 24, 32)
GRAB_AT_NM = (15.0, 25.0, 35.0, 40.0)


def _dark_fraction(img):
    import numpy as np
    from PyQt6.QtGui import QImage
    img = img.convertToFormat(QImage.Format.Format_RGB888)
    w, h, bpl = img.width(), img.height(), img.bytesPerLine()
    a = np.frombuffer(img.constBits().asstring(bpl * h), np.uint8)
    a = a.reshape(h, bpl)[:, :3 * w].reshape(h, w, 3)
    return float(np.all(a == DARK, axis=2).mean())


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    out = Path(argv[argv.index("--out") + 1])
    del argv[argv.index("--out"):argv.index("--out") + 2]
    out.mkdir(parents=True, exist_ok=True)
    args = bmg._parse_args(argv)

    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    bmg._bootstrap_fix_db(args.lat, args.lon, args.track, args.alt)
    w = bmg.build_widget(args)
    w.show()
    w._build_layers()

    # Warm-up: the 40 NM rung renders once, then back to 10 NM. This is
    # the "once that wider rung has rendered at least once" precondition.
    for nm in (40.0, 10.0):
        w.range_nm = nm
        w.update()
        bmg._pump(app, 0.2)
        bmg._wait_for_layers_to_settle(app, w)
        bmg._pump(app, 0.3)

    n_events = bmg._PINCH_EVENTS
    factor = (10.0 / 40.0) ** (1.0 / n_events)
    started, finished = bmg._gesture_bracket(w)
    grabs = list(GRAB_AT_NM)
    frames = []
    started()
    w.perf.paint_ms._buf.clear()     # paint stats over the gesture only
    t0 = time.perf_counter()
    for i in range(n_events):
        target = t0 + i / bmg._EVENT_HZ
        rem = target - time.perf_counter()
        if rem > 0:
            bmg._pump(app, rem)
        w.zoom_by(factor)
        while grabs and w.range_nm >= grabs[0] * 0.999:
            nm = grabs.pop(0)
            img = w.grab().toImage()
            path = out / ("frame_%02dnm.png" % int(round(nm)))
            img.save(str(path))
            frames.append(dict(range_nm=round(w.range_nm, 2),
                               png=path.name,
                               dark_fraction=round(_dark_fraction(img), 4)))
    p50, p95, mx, n = w.perf.paint_ms.stats()
    finished()
    bmg._wait_for_settle(app, w)
    print(json.dumps(dict(rev=bmg._git_rev(), w=args.w, h=args.h,
                          lat=args.lat, lon=args.lon, frames=frames,
                          paint_ms=dict(p50=p50, p95=p95, max=mx, n=n)),
                          indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
