#!/usr/bin/env python3
#  SPDX-License-Identifier: GPL-2.0-or-later
"""Draw the example evidence image for ``describe_platform()`` (CERT20a).

Reads this machine's CPU state once, paints it as text onto an offscreen QImage, saves
the PNG and writes its sidecar with the same record, so the picture and the sidecar's
``platform`` object state the same read. QPainter on a QImage only: no window, no GL,
nothing that competes with a live display for the screen.

    QT_QPA_PLATFORM=offscreen EVIDENCE_RUN="local: ..." \\
        python tools/render_platform_example.py docs/images/cert20a_platform/pi5_example.png
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from evidence_sidecar import describe_platform, write_sidecar  # noqa: E402


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    out = pathlib.Path(argv[0])
    commit = argv[1] if len(argv) > 1 else None
    record = describe_platform()

    from PyQt6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter

    app = QGuiApplication.instance() or QGuiApplication(["render_platform_example"])  # noqa: F841
    text = json.dumps(record, indent=1)
    lines = text.splitlines()
    font = QFont("DejaVu Sans Mono", 11)
    img = QImage(720, 22 + 17 * len(lines), QImage.Format.Format_RGB32)
    img.fill(QColor("#101418"))
    p = QPainter(img)
    p.setFont(font)
    p.setPen(QColor("#d8e0e8"))
    for i, line in enumerate(lines):
        p.drawText(12, 22 + 17 * i, line)
    p.end()
    out.parent.mkdir(parents=True, exist_ok=True)
    if not img.save(str(out)):
        print(f"could not write {out}", file=sys.stderr)
        return 1
    rec = write_sidecar(out, commit=commit, platform_state=record)
    print(json.dumps(rec, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
