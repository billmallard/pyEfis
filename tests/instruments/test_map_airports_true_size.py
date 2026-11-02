"""RWY1 (AER-4631): the moving map draws an airport's runways at true size
and position once its longest runway is longer on screen than its symbol,
and today's symbol below that.

The KSBA coordinates are the surveyed thresholds from the NASR
``airports.sqlite`` on the bench (``runway_ends``), copied verbatim.
"""
import math
import sqlite3

import pytest
from PyQt6.QtCore import QPointF
from PyQt6.QtGui import QColor, QImage, QPainter

from pyefis.instruments.ai.airport_db import NASRAirportDB
from pyefis.instruments.map import MapTransform
from pyefis.instruments.map.layers.airports import (AirportsLayer,
                                                    surface_class)

SCHEMA = """
CREATE TABLE airports (site_no TEXT PRIMARY KEY, icao TEXT NOT NULL, name TEXT,
  lat REAL NOT NULL, lon REAL NOT NULL, elev_ft REAL, mag_var REAL, state TEXT, city TEXT);
CREATE TABLE runways (site_no TEXT, rwy_id TEXT, length_ft REAL, width_ft REAL,
  surface TEXT, lighting TEXT, PRIMARY KEY (site_no, rwy_id));
CREATE TABLE runway_ends (site_no TEXT, rwy_id TEXT, end_id TEXT, true_alignment_deg REAL,
  lat REAL, lon REAL, elev_ft REAL, displaced_thr_lat REAL, displaced_thr_lon REAL,
  displaced_thr_len_ft REAL, tdz_elev_ft REAL, marking_type TEXT, apch_lgt_code TEXT,
  end_lgts_flag TEXT, cntrln_lgts_flag TEXT, tdz_lgt_flag TEXT,
  vgsi_code TEXT, visual_gpa REAL,
  PRIMARY KEY (site_no, rwy_id, end_id));
"""

KSBA = (34.42619166, -119.84149277)
#: rwy_id -> (length, width, surface, [(end_id, lat, lon, displaced_ft)])
KSBA_RWYS = {
    "07/25": (6052, 150, "ASPH", [("07", 34.427499, -119.85464161, 0),
                                  ("25", 34.42791763, -119.83457877, 0)]),
    "15L/33R": (4180, 75, "ASPH", [("15L", 34.43078061, -119.84036891, 0),
                                   ("33R", 34.41965252, -119.83693927, 0)]),
    "15R/33L": (4184, 100, "ASPH", [("15R", 34.43054038, -119.84153694, 0),
                                    ("33L", 34.41940166, -119.8381015, 0)]),
}
# A fictional turf strip (wide, so its interior is many px across) and a
# paved strip with a displaced threshold, each far from KSBA.
TURF = (35.0, -118.0)
TURF_RWYS = {"18/36": (2600, 300, "TURF", [("18", 35.0036, -118.0, 0),
                                           ("36", 34.9964, -118.0, 0)])}
DISP = (36.0, -117.0)
DISP_RWYS = {"09/27": (5000, 150, "CONC", [("09", 36.0, -117.0137, 800),
                                           ("27", 36.0, -116.9863, 0)])}


def _mkdb(path):
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    for site, icao, (lat, lon), rwys in (("1", "SBA", KSBA, KSBA_RWYS),
                                         ("2", "TRF", TURF, TURF_RWYS),
                                         ("3", "DSP", DISP, DISP_RWYS)):
        con.execute("INSERT INTO airports VALUES (?,?,?,?,?,?,?,?,?)",
                    (site, icao, icao, lat, lon, 10, 0, "CA", "City"))
        for rid, (ln, wd, surf, ends) in rwys.items():
            con.execute("INSERT INTO runways VALUES (?,?,?,?,?,?)",
                        (site, rid, ln, wd, surf, "MED"))
            for end_id, la, lo, disp in ends:
                con.execute(
                    "INSERT INTO runway_ends VALUES "
                    "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (site, rid, end_id, 0, la, lo, 10, None, None, disp,
                     None, "", "", "", "", "", None, None))
    con.commit()
    con.close()


class _Owner:
    def __init__(self, path):
        self.nasr_db_path = str(path)
        self.perf = None

    def update(self):
        pass


class _Rec(QPainter):
    """QPainter that records what the layer asks it to draw (the layer
    calls these from Python, so the overrides see every call) and still
    paints, so pixels can be checked too."""

    def __init__(self, dev):
        super().__init__(dev)
        self.polys, self.ellipses, self.texts, self.lines = [], [], [], []

    def drawPolygon(self, poly, *a):
        self.polys.append([QPointF(poly[i]) for i in range(poly.size())])
        return super().drawPolygon(poly, *a)

    def drawEllipse(self, *a):
        self.ellipses.append(a)
        return super().drawEllipse(*a)

    def drawText(self, rect, flags, text):
        self.texts.append((text, self.transform(), rect))
        return super().drawText(rect, flags, text)

    def drawLine(self, *a):
        self.lines.append(a)
        return super().drawLine(*a)


@pytest.fixture
def layer(tmp_path):
    db = tmp_path / "airports.sqlite"
    _mkdb(db)
    lay = AirportsLayer()
    lay.configure(_Owner(db))
    assert lay._db_all.ready
    return lay


def _xform(centre, range_nm, rot=0.0, size=400):
    return MapTransform(centre[0], centre[1], range_nm, rot, size, size, 0.5)


def _paint(lay, x):
    """Collect synchronously (no worker thread), then paint once."""
    key = lay._key(x)
    lay._snap = (key, lay._collect((key, x.lat0, x.lon0, x.range_nm)))
    img = QImage(x.w, x.h, QImage.Format.Format_RGB32)
    img.fill(QColor(0, 0, 0))
    p = _Rec(img)
    lay.paint(p, x)
    p.end()
    return p, img


def _near(a, b, tol=1.0):
    return math.hypot(a.x() - b.x(), a.y() - b.y()) <= tol


@pytest.mark.parametrize("rot", [0.0, 87.0])
def test_ksba_2nm_draws_three_runways_on_their_thresholds(qapp, layer, rot):
    x = _xform(KSBA, 2.0, rot)
    p, _ = _paint(layer, x)
    assert len(p.polys) == 3
    assert p.ellipses == []                 # the ring gives way
    ends = []
    for poly in p.polys:
        assert len(poly) == 4
        # Short-edge midpoints are the thresholds (corners 0/3 and 1/2).
        m1 = (poly[0] + poly[3]) / 2.0
        m2 = (poly[1] + poly[2]) / 2.0
        ends.append((m1, m2))
    for _rid, (_l, _w, _s, ((_e1, la1, lo1, _), (_e2, la2, lo2, _))) \
            in KSBA_RWYS.items():
        t1, t2 = x.to_screen(la1, lo1), x.to_screen(la2, lo2)
        assert any(_near(m1, t1) and _near(m2, t2) for m1, m2 in ends), _rid


def test_ksba_polygon_width_is_published_width(qapp, layer):
    x = _xform(KSBA, 1.0)
    p, _ = _paint(layer, x)
    want = sorted(x.nm_to_px(w / 6076.12) for (_l, w, _s, _e)
                  in KSBA_RWYS.values())
    got = sorted(math.hypot(*(lambda d: (d.x(), d.y()))(poly[0] - poly[3]))
                 for poly in p.polys)
    assert got == pytest.approx(want, abs=0.01)


def test_ksba_20nm_draws_the_symbol(qapp, layer):
    x = _xform(KSBA, 20.0)
    p, _ = _paint(layer, x)
    assert p.polys == []
    assert len(p.ellipses) == 1
    c = x.to_screen(*KSBA)
    assert _near(p.ellipses[0][0], c)


def test_threshold_is_per_airport_symbol_diameter(qapp, layer):
    """The switch happens where the longest runway's screen length crosses
    the symbol diameter -- not at a fixed range."""
    x = _xform(KSBA, 2.0)
    snap = layer._collect((layer._key(x), x.lat0, x.lon0, x.range_nm))
    a = next(a for a in snap if a["icao"] == "KSBA")
    r = max(6.0, min(14.0, x.w * 0.018))
    # 200 px from ownship to top edge, so span_px = span_nm * 200 / range:
    # the range where that equals the ring diameter 2r is the switch.
    edge = a["span_nm"] * 200.0 / (2.0 * r)
    assert layer._true_size(_xform(KSBA, edge * 0.98), a, r)
    assert not layer._true_size(_xform(KSBA, edge * 1.02), a, r)


def test_airport_without_end_coordinates_keeps_the_symbol(qapp, layer):
    x = _xform(KSBA, 2.0)
    layer._snap = (layer._key(x), [{
        "icao": "KXYZ", "lat": KSBA[0], "lon": KSBA[1], "longest": 3000.0,
        "hard": True, "rwys": [], "runways": [], "span_nm": 0.0}])
    img = QImage(400, 400, QImage.Format.Format_RGB32)
    p = _Rec(img)
    layer.paint(p, x)
    p.end()
    assert p.polys == []
    assert len(p.ellipses) == 1


def test_ident_label_stays_with_true_size(qapp, layer):
    p, _ = _paint(layer, _xform(KSBA, 2.0))
    assert "KSBA" in [t for t, _tr, _r in p.texts]


def test_runway_numbers_read_from_the_approach_end(qapp, layer):
    # Zoomed in far enough that the 15L/15R pair have room for both numbers.
    x = _xform(KSBA, 0.5, 30.0, size=800)
    p, _ = _paint(layer, x)
    drawn = {t: tr for t, tr, _r in p.texts}
    for _rid, (_l, _w, _s, ((e1, la1, lo1, _), (e2, la2, lo2, _))) \
            in KSBA_RWYS.items():
        t1, t2 = x.to_screen(la1, lo1), x.to_screen(la2, lo2)
        for end, here, there in ((e1, t1, t2), (e2, t2, t1)):
            assert end in drawn, end
            tr = drawn[end]
            d = there - here
            n = math.hypot(d.x(), d.y())
            u = (d.x() / n, d.y() / n)
            o = tr.map(QPointF(0, 0))
            up = tr.map(QPointF(0, -1)) - o
            # Text "up" points down the runway (landing direction)...
            assert up.x() * u[0] + up.y() * u[1] == pytest.approx(1.0,
                                                                  abs=1e-6)
            # ...and the label sits on the approach side of the threshold.
            assert (o - here).x() * u[0] + (o - here).y() * u[1] < 0


def _number_centres(p):
    out = []
    for t, tr, _r in p.texts:
        if t in {"07", "25", "15L", "33R", "15R", "33L"}:
            o = tr.map(QPointF(0, 0))
            out.append((t, o))
    return out


def test_close_parallel_numbers_do_not_overprint(qapp, layer):
    """At 1 NM on a 400 px map the 15L/15R thresholds are ~12 px apart:
    one number of the pair is drawn, never both on top of each other."""
    x = _xform(KSBA, 1.0, 0.0)
    p, _ = _paint(layer, x)
    nums = _number_centres(p)
    names = {t for t, _o in nums}
    assert {"07", "25"} <= names
    assert len(names & {"15L", "15R"}) == 1
    assert len(names & {"33L", "33R"}) == 1
    font_px = max(8, int(x.w * 0.022))
    for i, (ta, oa) in enumerate(nums):
        for tb, ob in nums[i + 1:]:
            gap = math.hypot(oa.x() - ob.x(), oa.y() - ob.y())
            assert gap >= (len(ta) + len(tb)) * 0.3 * font_px, (ta, tb)


def test_runway_numbers_wait_for_room(qapp, layer):
    p, _ = _paint(layer, _xform(KSBA, 8.0))
    assert len(p.polys) == 3                # true size already...
    texts = {t for t, _tr, _r in p.texts}
    assert texts.isdisjoint({"07", "25", "15L", "33R", "15R", "33L"})


def test_hard_fills_white_turf_draws_hollow(qapp, layer):
    _p, img = _paint(layer, _xform(KSBA, 1.0))
    c = _xform(KSBA, 1.0).to_screen(34.4277, -119.8446)  # on 07/25
    assert QColor(img.pixel(int(c.x()), int(c.y())))  == QColor(255, 255, 255)
    x = _xform(TURF, 0.5)
    p, img = _paint(layer, x)
    assert len(p.polys) == 1
    c = x.to_screen(*TURF)
    assert QColor(img.pixel(int(c.x()), int(c.y()))) == QColor(0, 0, 0)


@pytest.mark.parametrize("surface, kind", [
    ("ASPH", "hard"), ("CONC", "hard"), ("PEM", "hard"),
    ("ASPH-TURF", "hard"), ("TURF", "soft"), ("GRVL-DIRT", "soft"),
    ("MATS", "soft"), ("", "soft"), ("WATER", "water")])
def test_surface_class(surface, kind):
    assert surface_class(surface) == kind


def test_reader_carries_surface(tmp_path):
    db = tmp_path / "a.sqlite"
    _mkdb(db)
    aps = {a.icao: a for a in NASRAirportDB(db, paved_only=False)
           .airports_in_range(*TURF, 5)}
    assert [r.surface for r in aps["KTRF"].runways] == ["TURF"]


def test_displaced_threshold_bar(qapp, layer):
    x = _xform(DISP, 1.0)
    p, _ = _paint(layer, x)
    assert len(p.lines) == 1
    a, b = p.lines[0]
    mid = (a + b) / 2.0
    t1 = x.to_screen(36.0, -117.0137)
    assert mid.y() == pytest.approx(t1.y(), abs=0.5)
    assert mid.x() - t1.x() == pytest.approx(x.nm_to_px(800 / 6076.12),
                                             abs=0.5)


def test_runways_drawn_when_reference_point_is_off_screen(qapp, layer):
    """Zoomed in past the airport reference point: the runway in view still
    draws, though the ARP itself is outside the frame."""
    x = _xform((34.4275, -119.8626), 0.5)
    c = x.to_screen(*KSBA)
    assert not (0 <= c.x() <= x.w)
    p, _ = _paint(layer, x)
    assert p.polys
