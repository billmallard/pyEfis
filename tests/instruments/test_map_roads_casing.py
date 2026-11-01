#  SPDX-License-Identifier: GPL-2.0-or-later
#  RD2 (pyEfis #162, AER-622): moving-map roads draw at true scale close
#  in -- pen width max(tier_px, width_m / mpp) from the SVS ribbon's class
#  width table -- with a darker casing 2 px wider stroked under the fill.
#  Zoomed out every class sits on its tier floor and the image must be
#  today's, byte for byte; rivers never change.

import math

import numpy as np
import pytest
from PyQt6.QtGui import QImage, QPainter

from pyefis.instruments import map as moving_map
from pyefis.instruments.ai import road_ribbon
from pyefis.instruments.ai.camera import M_PER_DEG_LAT
from pyefis.instruments.map.layers import roads
from pyefis.instruments.map.layers.rivers import RiversLayer
from pyefis.instruments.map.layers.roads import (
    RoadsLayer, decimate_polylines, polyline_paths)

LAT0, LON0 = 34.5, -120.5
#: bench-like map: range is ownship -> top edge, 650 px (5.7 m/px at 2 NM,
#: the figure brief section 3.2 is written against)
W, H, ANCHOR = 600, 800, 0.1875


class _FakeDB:
    ready = True

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


def _ns_line(fclass, dlon=0.0):
    """A north-south line through (or *dlon* east of) the ownship."""
    return (fclass, np.array([[LAT0 - 0.3, LON0 + dlon],
                              [LAT0 + 0.3, LON0 + dlon]], dtype=np.float32))


def _network(seed=622, count=300, span_deg=0.35, step_deg=0.004):
    rng = np.random.default_rng(seed)
    classes = ["motorway", "motorway_link", "trunk", "primary",
               "secondary", "secondary_link"]
    out = []
    for i in range(count):
        k = int(rng.integers(2, 13))
        start = rng.uniform(-span_deg, span_deg, 2)
        steps = rng.normal(0.0, step_deg, (k - 1, 2))
        v = np.vstack([start, start + np.cumsum(steps, axis=0)])
        out.append((classes[i % len(classes)],
                    (v + (LAT0, LON0)).astype(np.float32)))
    return out


def _layer(cls, lines, casing=None):
    lay = cls()
    lay._db = _FakeDB(lines)
    if casing is not None:
        lay._casing_color = casing

    class Owner:
        perf = None
    lay._owner = Owner
    return lay


def _job(range_nm):
    x = moving_map.MapTransform(LAT0, LON0, range_nm, 0.0, W, H, ANCHOR)
    return x, (None, x.lat0, x.lon0, x.range_nm, x.w, x.h, x.cy)


def _pre_rd2_render(layer, job):
    """The MP11 render loop as it stood before RD2: one fetch and one
    tier pen per tier, no casing. Independent of _pen_groups."""
    key, lat0, lon0, range_nm, w, h, cy = job
    px_per_m = max(1.0, cy) / max(1.0, range_nm * 1852.0)
    half_diag_m = 0.5 * math.hypot(w, h) / px_per_m * 1.25
    n = int(min(1024, max(64, 2 * half_diag_m * px_per_m)))
    mpp = 2 * half_diag_m / n
    half = (n - 1) / 2.0
    ppd_lat = M_PER_DEG_LAT / mpp
    ppd_lon = M_PER_DEG_LAT * math.cos(math.radians(lat0)) / mpp
    by_tier = {}
    for fclass in layer._classes_for_range(range_nm):
        by_tier.setdefault(layer._tier_for(fclass), []).append(fclass)
    budget = roads._MAX_VERTICES
    paths = []
    for tier in sorted(by_tier):
        v, ends = layer._fetch(lat0, lon0, half_diag_m / 1852.0,
                               by_tier[tier])
        if ends.size == 0:
            continue
        starts = np.concatenate(([0], ends[:-1]))
        ends = ends[starts < budget]
        budget -= int(ends[-1])
        xs = (v[:, 1] - lon0) * ppd_lon + half
        ys = (lat0 - v[:, 0]) * ppd_lat + half
        xs, ys, first = decimate_polylines(xs, ys, ends, n)
        paths.append((tier, polyline_paths(xs, ys, first)))
    img = QImage(n, n, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    pens = layer._pens()
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    for tier, tier_paths in reversed(paths):
        for path in tier_paths:
            p.strokePath(path, pens[tier])
    p.end()
    return img


def _bgra(img):
    buf = img.constBits()
    buf.setsize(img.sizeInBytes())
    a = np.frombuffer(buf, np.uint8).reshape(
        img.height(), img.bytesPerLine() // 4, 4)
    return a[:, :img.width()].copy()


def _screen(layer, x, job):
    """Render, then blit through paint() as the widget does: pixels in
    screen space, at screen scale (the window image may be coarser)."""
    img, meta = layer._render(job)
    key = layer._key(x)
    layer._img = (img, key, meta)
    out = QImage(W, H, QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(0)
    p = QPainter(out)
    layer.paint(p, x)
    p.end()
    return _bgra(out)


# --- the shared width table ----------------------------------------------

def test_map_uses_the_svs_width_table():
    """One table, imported by both surfaces (brief section 3.2)."""
    assert RoadsLayer._WIDTH_M is road_ribbon.DEFAULT_WIDTH_M
    assert RiversLayer._WIDTH_M is None


def test_pen_groups_floor_when_zoomed_out():
    lay = RoadsLayer()
    _, job = _job(40.0)
    mpp = _mpp(job)
    groups = lay._pen_groups(lay._classes_for_range(40.0), mpp)
    # one group per tier, every one on its tier pen: the pre-RD2 batching
    assert [(t, w, r) for t, w, r, _ in groups] == [(0, 1.8, False)]
    assert groups[0][3] == ["motorway", "motorway_link", "trunk",
                            "trunk_link"]


def test_pen_groups_true_scale_close_in():
    lay = RoadsLayer()
    _, job = _job(1.0)
    mpp = _mpp(job)
    groups = lay._pen_groups(lay._classes_for_range(1.0), mpp)
    by_class = {c: (t, w, r) for t, w, r, cls in groups for c in cls}
    t, w, r = by_class["motorway"]
    assert r and w == pytest.approx(16.0 / mpp)
    assert by_class["trunk"][1] == pytest.approx(13.0 / mpp)
    # boldest tier first, widest first inside a tier
    keys = [(t, -w) for t, w, _, _ in groups]
    assert keys == sorted(keys)


def _mpp(job):
    key, lat0, lon0, range_nm, w, h, cy = job
    px_per_m = max(1.0, cy) / max(1.0, range_nm * 1852.0)
    half_diag_m = 0.5 * math.hypot(w, h) / px_per_m * 1.25
    n = int(min(1024, max(64, 2 * half_diag_m * px_per_m)))
    return 2 * half_diag_m / n


# --- DoD: 16 m road at 1 NM is 5-7 px, cased -------------------------------

def test_motorway_at_one_nm_is_true_width_and_cased(qapp):
    x, job = _job(1.0)
    px = _screen(_layer(RoadsLayer, [_ns_line("motorway")]), x, job)
    row = px[int(x.cy) - 150]           # well clear of the line's ends
    red, alpha = row[:, 2].astype(int), row[:, 3].astype(int)
    fill = red >= (0xc0 + 0x5a) // 2    # nearer the fill grey than casing
    casing = (alpha >= 128) & ~fill
    expected = 16.0 * x.cy / 1852.0     # true width in screen px
    assert 5.0 <= expected <= 7.0
    assert 5 <= int(fill.sum()) <= 7
    # casing shows on both sides of the fill
    cols = np.flatnonzero(fill)
    assert casing[:cols[0]].any() and casing[cols[-1] + 1:].any()


def test_casing_color_option(qapp):
    class Owner:
        road_casing_color = "#ff0000"
        highway_db_path = ""
    lay = RoadsLayer()
    lay.configure(Owner())
    assert lay._casing_color == "#ff0000"
    Owner.road_casing_color = ""
    lay.configure(Owner())
    assert lay._casing_color == "#5a5a5a"     # empty -> the default


# --- zoomed out: today's picture exactly -----------------------------------

@pytest.mark.parametrize("range_nm", [20.0, 40.0, 80.0])
def test_far_ranges_are_byte_identical_to_pre_rd2(qapp, range_nm):
    """Guardrail: at 20 NM and beyond the overlay equals the current image
    within 1 %. Measured here: 0 %, it is the same bytes."""
    scale = range_nm / 5.0
    lay = _layer(RoadsLayer, _network(count=600, span_deg=0.35 * scale,
                                      step_deg=0.004 * scale))
    _, job = _job(range_nm)
    new = _bgra(lay._render(job)[0])
    ref = _bgra(_pre_rd2_render(lay, job))
    assert (ref[..., 3] > 0).sum() > 1000            # the fixture draws
    assert np.array_equal(new, ref)


def test_far_range_adds_no_strokes(qapp, monkeypatch):
    """80 NM renders no worse than before: same stroke calls, no casing."""
    calls = []
    real = QPainter.strokePath

    def counting(self, path, pen):
        calls.append(path.elementCount())
        return real(self, path, pen)
    monkeypatch.setattr(QPainter, "strokePath", counting)
    lay = _layer(RoadsLayer, _network(count=600, span_deg=5.6, step_deg=0.064))
    _, job = _job(80.0)
    _pre_rd2_render(lay, job)
    before = list(calls)
    calls.clear()
    lay._render(job)
    assert before and calls == before


def test_near_range_casing_is_batched(qapp, monkeypatch):
    """The casing is a second strokePath over the same batched paths,
    not a per-polyline loop."""
    calls = []
    real = QPainter.strokePath

    def counting(self, path, pen):
        calls.append(pen.widthF())
        return real(self, path, pen)
    monkeypatch.setattr(QPainter, "strokePath", counting)
    monkeypatch.setattr(QPainter, "drawPolyline",
                        lambda *a: pytest.fail("per-polyline draw"))
    lay = _layer(RoadsLayer, _network(span_deg=0.05))
    _, job = _job(1.0)
    lay._render(job)
    groups = lay._pen_groups(lay._classes_for_range(1.0), _mpp(job))
    ribbons = sum(1 for g in groups if g[2])
    assert ribbons >= 2
    assert len(calls) <= 2 * (len(groups) + 300 // roads._LINES_PER_PATH)


# --- casing under a translucent fill ----------------------------------------

def test_casing_does_not_tint_a_translucent_fill(qapp):
    """The arterial fills are translucent by design (tier alpha 170 for
    secondary). The casing under them must not bleed through: every
    interior fill pixel is byte-identical to the uncased render."""
    lines = [_ns_line("secondary")]
    _, job = _job(0.5)
    cased = _bgra(_layer(RoadsLayer, lines)._render(job)[0])
    bare = _bgra(_layer(RoadsLayer, lines, casing="")._render(job)[0])
    a = bare[..., 3].astype(int)
    full = a == RoadsLayer._TIER_PEN[2][1]
    # interior: full-coverage pixels whose 4-neighbours are too
    interior = full.copy()
    interior[1:-1, 1:-1] &= (full[:-2, 1:-1] & full[2:, 1:-1]
                             & full[1:-1, :-2] & full[1:-1, 2:])
    interior[[0, -1], :] = False
    interior[:, [0, -1]] = False
    assert interior.sum() > 500
    assert np.array_equal(cased[interior], bare[interior])
    # and the casing really drew around it
    assert ((cased[..., 3] > 0) & (a == 0)).sum() > 100


# --- rivers --------------------------------------------------------------

@pytest.mark.parametrize("range_nm", [1.0, 5.0, 40.0])
def test_rivers_are_unaffected(qapp, range_nm):
    lines = [_ns_line("river"), _ns_line("stream", dlon=0.01)]
    lay = _layer(RiversLayer, lines)
    assert lay._casing_color == ""
    _, job = _job(range_nm)
    assert np.array_equal(_bgra(lay._render(job)[0]),
                          _bgra(_pre_rd2_render(lay, job)))
