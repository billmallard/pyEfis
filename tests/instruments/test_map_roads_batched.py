#  SPDX-License-Identifier: GPL-2.0-or-later
#  MP11 (pyEfis #204, AER-4458): the roads/rivers worker draws from numpy
#  arrays -- bulk query, vectorised cull + pixel-grid decimation, batched
#  QPainterPaths -- instead of one HighwayLine + QPolygonF per polyline.
#  These pin the batched path's rules and its pixel agreement with the
#  per-line QPointF loop it replaced (kept here, test-local, as the
#  reference).

import math
import sqlite3

import numpy as np
import pytest
from PyQt6.QtCore import QPointF
from PyQt6.QtGui import QImage, QPainter, QPainterPath, QPolygonF

from pyefis.instruments.ai.camera import M_PER_DEG_LAT
from pyefis.instruments.ai.highway_db import HighwayDB, encode_vertices
from pyefis.instruments.map.layers import roads
from pyefis.instruments.map.layers.roads import (
    RoadsLayer, decimate_polylines, polyline_paths)

LAT0, LON0 = 34.5, -120.5


def _ends(*lens):
    return np.cumsum(lens).astype(np.int64)


# --- decimate_polylines --------------------------------------------------

def test_decimate_drops_short_and_offscreen_polylines():
    xs = np.array([5.0,                 # 1 vertex: draws nothing
                   10.0, 20.0,          # on screen
                   -30.0, -10.0,        # wholly left of the image
                   90.0, 120.0])        # straddles the right edge: kept
    ys = np.array([5.0, 10.0, 20.0, 50.0, 60.0, 50.0, 50.0])
    x, y, first = decimate_polylines(xs, ys, _ends(1, 2, 2, 2), 100)
    assert list(x) == [10.0, 20.0, 90.0, 120.0]
    assert list(first) == [True, False, True, False]


def test_decimate_collapses_pixel_runs_but_keeps_both_ends():
    # one polyline: four vertices inside pixel (10, 10), then a jump,
    # then a tail that ends inside the previous vertex's pixel
    xs = np.array([10.0, 10.1, 10.2, 9.9, 30.0, 30.2])
    ys = np.array([10.0, 10.1, 9.8, 10.2, 30.0, 30.1])
    x, y, first = decimate_polylines(xs, ys, _ends(6), 100)
    # the run collapses to its FIRST member, at its exact float position;
    # the last vertex survives even though it shares a pixel
    assert list(x) == [10.0, 30.0, 30.2]
    assert list(y) == [10.0, 30.0, 30.1]
    assert list(first) == [True, False, False]


def test_decimate_subpixel_polyline_survives_as_two_vertices():
    xs = np.array([10.0, 10.1, 10.2])
    ys = np.array([10.0, 10.1, 10.2])
    x, _, first = decimate_polylines(xs, ys, _ends(3), 100)
    assert list(x) == [10.0, 10.2] and list(first) == [True, False]


def test_decimate_never_bridges_polylines():
    # two polylines whose junction shares a pixel: the second one's
    # start must survive as a MoveTo, not merge into the first
    xs = np.array([0.0, 10.0, 10.2, 20.0])
    ys = np.array([0.0, 10.0, 10.2, 20.0])
    x, _, first = decimate_polylines(xs, ys, _ends(2, 2), 100)
    assert list(x) == [0.0, 10.0, 10.2, 20.0]
    assert list(first) == [True, False, True, False]


def test_decimate_empty():
    x, y, first = decimate_polylines(np.empty(0), np.empty(0),
                                     np.empty(0, np.int64), 100)
    assert x.size == y.size == first.size == 0


# --- polyline_paths ------------------------------------------------------

def test_polyline_paths_one_subpath_per_polyline(qapp):
    xs = np.array([0.0, 1.0, 2.0, 5.0, 6.0, 9.0, 8.0, 7.0])
    ys = np.array([0.0, 1.0, 0.0, 5.0, 6.0, 9.0, 8.0, 9.5])
    first = np.array([1, 0, 0, 1, 0, 1, 0, 0], dtype=bool)
    paths = polyline_paths(xs, ys, first, per_path=64)
    assert len(paths) == 1
    p = paths[0]
    assert p.elementCount() == 8
    types = [p.elementAt(i).type for i in range(8)]
    move = QPainterPath.ElementType.MoveToElement
    assert [t == move for t in types] == list(first)
    assert [(p.elementAt(i).x, p.elementAt(i).y) for i in range(8)] \
        == list(zip(xs, ys))


def test_polyline_paths_chunks_on_polyline_boundaries(qapp):
    # 5 two-vertex polylines, 2 per path -> 3 paths of 4, 4, 2 elements,
    # each starting with a MoveTo
    xs = np.arange(10, dtype=float)
    first = np.tile([True, False], 5)
    paths = polyline_paths(xs, xs, first, per_path=2)
    assert [p.elementCount() for p in paths] == [4, 4, 2]
    move = QPainterPath.ElementType.MoveToElement
    assert all(p.elementAt(0).type == move for p in paths)
    assert polyline_paths(xs[:0], xs[:0], first[:0]) == []


# --- HighwayDB.polyline_arrays_in_range ----------------------------------

def _write_pack(path, lines):
    """lines: [(fclass, (N, 2) lat/lon array)]"""
    con = sqlite3.connect(str(path))
    con.executescript(
        "CREATE TABLE highway_lines (id INTEGER PRIMARY KEY, fclass TEXT,"
        " min_lat REAL, max_lat REAL, min_lon REAL, max_lon REAL,"
        " verts BLOB, flags INTEGER NOT NULL DEFAULT 0, ref TEXT);"
        "CREATE VIRTUAL TABLE highway_rtree USING rtree(id, min_lat, max_lat,"
        " min_lon, max_lon);")
    for rid, (fc, v) in enumerate(lines, start=1):
        bb = (float(v[:, 0].min()), float(v[:, 0].max()),
              float(v[:, 1].min()), float(v[:, 1].max()))
        con.execute("INSERT INTO highway_lines VALUES (?,?,?,?,?,?,?,0,NULL)",
                    (rid, fc) + bb + (encode_vertices(v),))
        con.execute("INSERT INTO highway_rtree VALUES (?,?,?,?,?)",
                    (rid,) + bb)
    con.commit()
    con.close()


def _network(seed=4458, count=400, span_deg=0.35):
    """A dense synthetic road network around (LAT0, LON0): random-walk
    polylines of 2-12 vertices across every roads class, many of them
    crossing and some running off the window."""
    rng = np.random.default_rng(seed)
    classes = ["motorway", "motorway_link", "trunk", "primary",
               "secondary", "secondary_link"]
    out = []
    for i in range(count):
        k = int(rng.integers(2, 13))
        start = rng.uniform(-span_deg, span_deg, 2)
        steps = rng.normal(0.0, 0.004, (k - 1, 2))
        v = np.vstack([start, start + np.cumsum(steps, axis=0)])
        v = v + (LAT0, LON0)
        out.append((classes[i % len(classes)], v.astype(np.float32)))
    return out


def test_bulk_reader_matches_the_per_line_generator(tmp_path):
    p = tmp_path / "h.sqlite"
    _write_pack(p, _network(span_deg=0.1))
    db = HighwayDB(str(p))
    cls = ("motorway", "primary")
    v, ends = db.polyline_arrays_in_range(LAT0, LON0, 30.0, classes=cls)
    lines = list(db.polylines_in_range(LAT0, LON0, 30.0, classes=cls))
    assert len(lines) > 50
    assert ends.tolist() == np.cumsum([len(l.vertices) for l in lines]
                                      ).tolist()
    assert np.array_equal(v, np.concatenate([l.vertices for l in lines]))
    # empty class set and an unready reader both yield empty arrays
    for got in (db.polyline_arrays_in_range(LAT0, LON0, 30.0, classes=()),
                HighwayDB("").polyline_arrays_in_range(LAT0, LON0, 30.0)):
        assert got[0].shape == (0, 2) and got[1].shape == (0,)


def test_bulk_reader_box_is_true_distance_in_longitude(tmp_path):
    """The bulk box is range_nm wide in true distance (lon half-width
    range/cos(lat)), not the generator's fixed 2x: a line 1.15 range
    east is inside it at 34.5 N (1/cos = 1.21), one 1.6 range east is
    not -- though the generator's 2x box returns both."""
    d = 10.0 / 60.0                       # 10 NM in degrees of latitude

    def stub(dlon):
        lon = LON0 + dlon * d
        return np.array([[LAT0, lon], [LAT0 + 0.001, lon + 0.001]],
                        dtype=np.float32)
    p = tmp_path / "h.sqlite"
    _write_pack(p, [("motorway", stub(1.15)), ("motorway", stub(1.6))])
    db = HighwayDB(str(p))
    _, ends = db.polyline_arrays_in_range(LAT0, LON0, 10.0)
    assert ends.size == 1
    assert len(list(db.polylines_in_range(LAT0, LON0, 10.0))) == 2


# --- render: batched vs the per-line reference ---------------------------

class _FakeDB:
    """Only the per-line generator, like the other map tests' fakes: the
    layer must fall back to concatenating it."""

    def __init__(self, lines):
        self._lines = lines

    def polylines_in_range(self, lat, lon, range_nm, classes=None):
        class L:
            pass
        for fc, v in self._lines:
            if classes is None or fc in classes:
                ln = L()
                ln.vertices, ln.fclass = v, fc
                yield ln


class _GeneratorOnly:
    """A real HighwayDB seen through its per-line generator only."""

    def __init__(self, db):
        self.polylines_in_range = db.polylines_in_range


def _reference_render(layer, job):
    """The pre-MP11 per-line loop: one QPolygonF of QPointFs and one
    drawPolyline per polyline, in query order."""
    key, lat0, lon0, range_nm, w, h, cy = job
    px_per_m = max(1.0, cy) / max(1.0, range_nm * 1852.0)
    half_diag_m = 0.5 * math.hypot(w, h) / px_per_m * 1.25
    n = int(min(1024, max(64, 2 * half_diag_m * px_per_m)))
    mpp = 2 * half_diag_m / n
    half = (n - 1) / 2.0
    ppd_lat = M_PER_DEG_LAT / mpp
    ppd_lon = M_PER_DEG_LAT * math.cos(math.radians(lat0)) / mpp
    img = QImage(n, n, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pens = layer._pens()
    for line in layer._db.polylines_in_range(
            lat0, lon0, half_diag_m / 1852.0,
            classes=layer._classes_for_range(range_nm)):
        v = line.vertices
        xs = (v[:, 1] - lon0) * ppd_lon + half
        ys = (lat0 - v[:, 0]) * ppd_lat + half
        if xs.max() < 0 or xs.min() > n or ys.max() < 0 or ys.min() > n:
            continue
        p.setPen(pens[layer._tier_for(line.fclass)])
        p.drawPolyline(QPolygonF([QPointF(float(a), float(b))
                                  for a, b in zip(xs, ys)]))
    p.end()
    return img


def _alpha(img):
    buf = img.constBits()
    buf.setsize(img.sizeInBytes())
    a = np.frombuffer(buf, np.uint8).reshape(
        img.height(), img.bytesPerLine() // 4, 4)
    return a[:, :img.width(), 3].astype(int)


@pytest.mark.parametrize("range_nm", [3.0, 15.0])
def test_batched_render_matches_per_line_reference(qapp, tmp_path,
                                                   range_nm):
    """No visible change (G21 DoD), at the tolerance measured on the
    Raleigh scene at 5-80 NM: every solid (alpha >= 128) road pixel of
    the reference is still covered and none is invented, and the covered
    footprint agrees to IoU >= 0.99. Pixel-grid decimation alone moves
    almost nothing; the remaining difference is antialiased fringe where
    polylines of one tier overlap -- a batched path covers the union
    once, where separate drawPolyline calls composited the fringe twice.
    Also: the bulk reader and the per-line fallback render
    byte-identically from the same pack."""
    network = _network()
    layer = RoadsLayer()
    layer._db = _FakeDB(network)
    job = (None, LAT0, LON0, range_nm, 400, 400, 200.0)
    ref = _alpha(_reference_render(layer, job))
    new = _alpha(layer._render(job)[0])

    covered_ref, covered_new = ref > 0, new > 0
    assert covered_ref.sum() > 2000          # the fixture really draws
    iou = (covered_ref & covered_new).sum() / (covered_ref | covered_new).sum()
    assert iou >= 0.99
    assert ((ref >= 128) & ~covered_new).sum() == 0     # nothing omitted
    assert ((new >= 128) & ~covered_ref).sum() == 0     # nothing invented

    # same rows in the same (R-tree) order through both readers: the
    # bulk query's tighter box only drops lines the image cannot show
    p = tmp_path / "h.sqlite"
    _write_pack(p, network)
    db = HighwayDB(str(p))
    bulk = RoadsLayer()
    bulk._db = db
    per_line = RoadsLayer()
    per_line._db = _GeneratorOnly(db)
    assert np.array_equal(_alpha(bulk._render(job)[0]),
                          _alpha(per_line._render(job)[0]))


def test_render_strokes_batched_paths_not_per_polyline(qapp, monkeypatch):
    """The point of MP11: draw calls scale with polylines / per_path,
    not with polylines."""
    calls = []
    real = QPainter.strokePath

    def counting(self, path, pen):
        calls.append(path.elementCount())
        return real(self, path, pen)
    monkeypatch.setattr(QPainter, "strokePath", counting)
    monkeypatch.setattr(QPainter, "drawPolyline",
                        lambda *a: pytest.fail("per-polyline draw"))
    layer = RoadsLayer()
    layer._db = _FakeDB(_network())
    layer._render((None, LAT0, LON0, 3.0, 400, 400, 200.0))
    # 400 polylines over 3 pen tiers, 64 to a path: a handful of strokes
    assert 3 <= len(calls) <= 3 + 400 // roads._LINES_PER_PATH
