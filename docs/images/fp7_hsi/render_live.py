"""Render the real pyEfis HSI + nav_status chip against a live fix-gateway
(flightplan engine running), at synthetic positions on KSBA-GVO-RZS-KSMX."""
import math, os, sys, time, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter
from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)
for ttf in glob.glob(os.path.join(os.environ.get("RENDER_FONT_DIR", "/nonexistent"), "*.ttf")):
    QFontDatabase.addApplicationFont(ttf)
import pyavtools.fix as fix
fix.initialize({"main": {"FixServer": "127.0.0.1", "FixPort": os.environ.get("FIXPORT", "3490")}})
from pyefis.instruments.hsi import HSI
from pyefis.instruments.nav_status import NavStatus
from fixio import Fix
import hsi_chain_points as pts

io = Fix()
out = sys.argv[1]
hsi = HSI(cdi_enabled=True, gsi_enabled=False); hsi.resize(400, 400)
chip = NavStatus(); chip.resize(400, 34)
hsi.show(); chip.show()

def pump(sec):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents(); time.sleep(0.02)

tiles = []
cmdseq = [300]
for label, pos, head in pts.points():
    if label.startswith("KSBA-GVO on") or label.startswith("RZS-KSMX"):
        # Move first, then activate: activating with the aircraft still
        # past the new leg's TO would sequence it straight away.
        io.w("LAT", pos[0]); io.w("LONG", pos[1]); pump(0.5)
        cmdseq[0] += 1
        io.w("FPLCMD", "%d ACT %d" % (cmdseq[0], 2 if label.startswith("KSBA") else 4))
    io.w("HEAD", head); io.w("LAT", pos[0]); io.w("LONG", pos[1]); pump(0.7)
    io.w("LAT", pos[0] + 1e-9); pump(1.0)
    vals = {k: io.r(k)[0] for k in ("COURSE", "CDI", "TOFROM")}
    img = QImage(400, 400 + 34 + 30, QImage.Format.Format_ARGB32); img.fill(QColor("#000000"))
    p = QPainter(img)
    p.drawPixmap(0, 0, hsi.grab()); p.drawPixmap(0, 400, chip.grab())
    p.setPen(QColor("#cccccc")); f = QFont("DejaVu Sans"); f.setPixelSize(13); p.setFont(f)
    p.drawText(6, 400 + 34 + 20, "%s  CRS %.0f  CDI %+.2f  TF %s" % (label, float(vals["COURSE"]), float(vals["CDI"]), vals["TOFROM"]))
    p.end()
    name = label.lower().replace(" ", "_").replace(",", "").replace(".", "p").replace("(", "").replace(")", "")
    img.save(os.path.join(out, "hsi_%s.png" % name))
    tiles.append(img)
    print(label, vals, flush=True)

cols = 3; rows = (len(tiles) + cols - 1) // cols
sheet = QImage(cols * 400 + (cols - 1) * 6, rows * tiles[0].height() + (rows - 1) * 6, QImage.Format.Format_ARGB32)
sheet.fill(QColor("#404040")); p = QPainter(sheet)
for i, t in enumerate(tiles):
    p.drawImage((i % cols) * 406, (i // cols) * (t.height() + 6), t)
p.end(); sheet.save(os.path.join(out, "hsi_contact_sheet.png"))
os._exit(0)
