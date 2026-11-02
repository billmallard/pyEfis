#  SPDX-License-Identifier: GPL-2.0-or-later
"""The moving map's procedure legs (PA8, billmallard/pyEfis#239): leg paths
on the canvas, the missed approach and vector styles, altitude constraint
labels, and guardrail 1 on the map -- a route the engine rejected draws
nothing.

The procedure is KSSF RNAV (GPS) 28 via XTEND with its missed approach (CA,
DF GANLE coded right, HM GANLE), the route block fix-gateway's encoder
builds from FAA CIFP cycle 2611 (``tests/flightplan/fixtures/
fplroute_blocks.json``), loaded onto the bus exactly as written there.
"""

import gc
import math

import pytest
from PyQt6.QtCore import QPointF
from PyQt6.QtGui import QColor, QImage, QPainter

from pyefis.flightplan import geo
from pyefis.flightplan import leg_paths as fp_legs
from pyefis.instruments import map as moving_map
from pyefis.instruments.map.layers import flight_plan as fp_layer
from pyefis.instruments.map.perf import MapPerfStats
from tests.flightplan.test_fplroute_conformance import FIXTURE, _route_block
from tests.instruments.test_map_flight_plan_layer import (
    _define, _define_all_fp1_keys, _engine, _golden_route, _owner)

KSSF = "qa1-missed-coded-turn-kssf-r28"
RW28 = (29.33556389, -98.46561944)
BLACK = QColor(0, 0, 0)


def _writes(profile=KSSF, seq=1):
    out = []
    for key, value in FIXTURE["profiles"][profile]["writes"]:
        out.append((key, seq if key == "FPLSEQ" else value))
    return out


def _load(fix, profile=KSSF, seq=1, loaded_seq=None, define=True):
    """Put *profile*'s route block on the bus. *loaded_seq*: the engine's
    FPLLDSEQ (None leaves the key undefined -- a gateway without it)."""
    if define:
        _define_all_fp1_keys(fix)
        _define(fix, "FPLAPRTYPE", "str", "")
        _define(fix, "MAGVAR", "float", FIXTURE["profiles"][profile]["magvar_deg"])
        if loaded_seq is not None:
            _define(fix, "FPLLDSEQ", "int", loaded_seq)
    for key, value in _writes(profile, seq):
        fix.db.set_value(key, value)


def _layer(qtbot):
    layer = fp_layer.FlightPlanLayer()
    layer.configure(_owner(qtbot))
    return layer


def _render(layer, centre=RW28, range_nm=8.0, size=500, rot=0.0):
    x = moving_map.MapTransform(centre[0], centre[1], range_nm, rot, size, size, 0.5)
    img = QImage(size, size, QImage.Format.Format_RGB32)
    img.fill(0)
    p = QPainter(img)
    layer.paint(p, x)
    p.end()
    return img, x


def _inked(img):
    return [(px, py) for px in range(img.width()) for py in range(img.height())
            if img.pixelColor(px, py) != BLACK]


def _ink_near(img, c, rad=2):
    return any(img.pixelColor(int(round(c.x())) + dx, int(round(c.y())) + dy) != BLACK
               for dx in range(-rad, rad + 1) for dy in range(-rad, rad + 1))


# ---------------------------------------------------------------------------
# Guardrail 1 on the map (QA, 2026-09-19; DoD of AER-1607): a procedure the
# engine rejected renders NOTHING.
# ---------------------------------------------------------------------------
def test_rejected_procedure_reaches_no_pixel(fix, qtbot):
    """The KSSF block is on the bus (FPLSEQ 1) but the engine never loaded
    it (FPLLDSEQ 0): not one pixel of it is drawn -- no leg, no fix, no
    label, no hold."""
    _load(fix, seq=1, loaded_seq=0)
    img, _ = _render(_layer(qtbot))
    assert _inked(img) == []


def test_the_same_procedure_draws_once_the_engine_loads_it(fix, qtbot):
    """The control for the test above: the same block, the same view, with
    the engine reporting it loaded, draws plenty -- so "nothing drawn" above
    is the gate, not an empty view."""
    _load(fix, seq=1, loaded_seq=0)
    layer = _layer(qtbot)
    fix.db.set_value("FPLLDSEQ", 1)
    img, _ = _render(layer)
    assert len(_inked(img)) > 500


def test_rejected_replacement_shows_only_the_leg_being_flown(fix, qtbot):
    """A plan the engine is flying, then a commit of the KSSF procedure that
    the engine rejects (FPLLDSEQ stays at the flown plan's seq). The slots
    now hold KSSF; none of it reaches the canvas. What remains is the active
    leg, drawn from the engine's own FROM/TO outputs."""
    _load(fix, seq=1, loaded_seq=1)
    fr = (29.40, -98.30)
    to = (29.40, -98.60)
    for key, value in (("FPLSTATE", 1), ("FPLACTLEG", 2), ("FPLFRLAT", fr[0]),
                       ("FPLFRLON", fr[1]), ("WPLAT", to[0]), ("WPLON", to[1])):
        fix.db.set_value(key, value)
    layer = _layer(qtbot)
    _load(fix, seq=2, define=False)            # the engine answers nothing
    img, x = _render(layer, range_nm=10.0)
    a, b = x.to_screen(*fr), x.to_screen(*to)

    def off_line(px, py):
        # Distance from the FROM -> TO segment, in pixels.
        dx, dy = b.x() - a.x(), b.y() - a.y()
        t = max(0.0, min(1.0, ((px - a.x()) * dx + (py - a.y()) * dy) / (dx * dx + dy * dy)))
        return math.hypot(px - (a.x() + t * dx), py - (a.y() + t * dy)) > 3.0

    inked = _inked(img)
    assert inked                                     # the flown leg is there
    assert [q for q in inked if off_line(*q)] == []  # and nothing else


def test_a_gateway_without_fplldseq_draws_as_before(fix, qtbot):
    _load(fix, seq=1, loaded_seq=None)
    img, _ = _render(_layer(qtbot))
    assert len(_inked(img)) > 500


def test_route_loaded_reads_the_engine_key():
    route = _golden_route()            # seq 1
    assert fp_layer.route_loaded(route, _engine())                  # no key
    assert fp_layer.route_loaded(route, _engine(FPLLDSEQ=1))
    assert not fp_layer.route_loaded(route, _engine(FPLLDSEQ=0))
    assert not fp_layer.route_loaded(route, _engine(FPLLDSEQ=2))


# ---------------------------------------------------------------------------
# The DF's coded turn on the canvas: the map turns right with the engine.
# ---------------------------------------------------------------------------
def _kssf_paths(turn=None):
    route = _route_block(_writes())
    if turn is not None:
        next(s for s in route.waypoints if s.pt == "DF").turn = turn
    paths = fp_legs.build_leg_paths(route.waypoints, -3.0)
    k = next(i for i, s in enumerate(route.waypoints) if s.pt == "DF")
    return next(p for p in paths if p.to_slot == k + 1)


def test_kssf_missed_turn_is_drawn_right_not_the_short_way(fix, qtbot):
    _load(fix, seq=1, loaded_seq=1)
    img, x = _render(_layer(qtbot), centre=(29.30, -98.48), range_nm=8.0)
    right = _kssf_paths().points
    left = _kssf_paths("L").points
    mid_r = right[len(right) // 3: 2 * len(right) // 3]
    # The short-way turn's points, away from where the two turns share
    # their start (they are tangent there) and from the straight run to
    # GANLE they both end on.
    mid_l = [p for p in left[1:-2]
             if min(geo.distance_nm(*p, *q) for q in right) > 0.3]
    assert len(mid_l) > 5
    assert all(_ink_near(img, x.to_screen(*p)) for p in mid_r)
    assert not any(_ink_near(img, x.to_screen(*p)) for p in mid_l)


# ---------------------------------------------------------------------------
# Styles: the missed approach segment is dashed, vectors dotted.
# ---------------------------------------------------------------------------
def test_missed_segment_legs_are_styled_missed():
    route = _route_block(_writes())
    kinds = fp_layer.segment_kinds(route)
    paths = fp_legs.build_leg_paths(route.waypoints, -3.0)
    draws = fp_layer.build_leg_draws(route, _engine(), paths, kinds)
    by_slot = {}
    for _c, _w, style, (kind, k) in draws:
        if kind == "path":
            by_slot[paths[k].to_slot] = style
    for slot, style in by_slot.items():
        expect = "missed" if kinds[slot - 1] == "missed" else "solid"
        assert style == expect, (slot, route.waypoints[slot - 1].id)
    assert "missed" in by_slot.values() and "solid" in by_slot.values()


def test_vector_leg_is_styled_vector():
    route = _golden_route()
    route.waypoints[2].pt = "VM"
    route.waypoints[2].crs = 270.0
    paths = fp_legs.build_leg_paths(route.waypoints)
    draws = fp_layer.build_leg_draws(route, _engine(), paths)
    styles = {paths[k].to_slot: s for _c, _w, s, (kind, k) in draws if kind == "path"}
    assert styles[3] == "vector"


def test_active_leg_follows_its_path_unless_entered_direct():
    route = _route_block(_writes())
    paths = fp_legs.build_leg_paths(route.waypoints, -3.0)
    df = _kssf_paths()
    act = df.to_slot
    ca_end = df.points[0]
    on = fp_layer.build_leg_draws(route, _engine(FPLSTATE=1, FPLACTLEG=act, FPLFRLAT=ca_end[0],
                                                 FPLFRLON=ca_end[1]), paths)
    active = [ref for c, _w, _s, ref in on if c == fp_layer.ACTIVE]
    assert active and active[0][0] == "path"
    # A direct-to into GANLE from somewhere else: the engine flies the
    # straight line, and that is what is drawn.
    dto = fp_layer.build_leg_draws(route, _engine(FPLSTATE=1, FPLACTLEG=act, FPLFRLAT=29.0,
                                                  FPLFRLON=-98.0), paths)
    active = [ref for c, _w, _s, ref in dto if c == fp_layer.ACTIVE]
    assert active[0][0] == "line"


# ---------------------------------------------------------------------------
# Altitude constraints, in chart notation, on procedure fixes only.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("alt, lines", [
    ("+3100", [("3100", False, True)]),
    ("-5000", [("5000", True, False)]),
    ("@2600", [("2600", True, True)]),
    ("B2900,4000", [("4000", True, False), ("2900", False, True)]),
    ("", []), ("bogus", []),
])
def test_parse_alt_constraint(alt, lines):
    assert fp_layer.parse_alt_constraint(alt) == lines


def test_constraints_label_procedure_fixes_not_airway_meas():
    route = _route_block(_writes())
    labels = fp_layer.build_constraint_labels(route, _engine())
    ids = {(lat, lon): s.id for s in route.waypoints for lat, lon in [(s.lat, s.lon)]}
    assert {ids[(lat, lon)] for _c, lat, lon, _l in labels} >= {"GEARE", "BEFOR", "GANLE"}
    golden = _golden_route()
    for s in golden.waypoints:
        s.alt = "+7000"                # an airway leg's MEA
    assert fp_layer.build_constraint_labels(golden, _engine()) == []


def test_no_symbol_or_tap_target_on_a_ca_point():
    route = _route_block(_writes())
    syms = fp_layer.build_symbols(route, _engine())
    ca = next(s for s in route.waypoints if s.pt == "CA")
    assert (ca.lat, ca.lon) not in {(lat, lon) for _c, lat, lon, _t, _l, _r in syms}
    assert len(syms) == len(route.waypoints) - 1


# ---------------------------------------------------------------------------
# Off the paint path: geometry is built in collect(), once per commit.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("rot", [0.0, 37.0, -121.0])
def test_lonlat_transform_is_maptransform(rot):
    x = moving_map.MapTransform(29.3, -98.4, 12.0, rot, 640, 480, 0.3)
    t = fp_layer.lonlat_transform(x)
    for lat, lon in ((29.3, -98.4), (29.45, -98.1), (29.1, -98.7), (29.6, -98.25)):
        got = t.map(QPointF(lon, lat))
        want = x.to_screen(lat, lon)
        assert got.x() == pytest.approx(want.x(), abs=1e-6)
        assert got.y() == pytest.approx(want.y(), abs=1e-6)


def test_paint_never_tessellates(fix, qtbot, monkeypatch):
    _load(fix, seq=1, loaded_seq=1)
    layer = _layer(qtbot)
    snap = layer._snapshot
    assert snap is not None and snap.paths

    def boom(*_a, **_k):
        raise AssertionError("leg geometry built during paint")

    monkeypatch.setattr(fp_legs, "build_leg_paths", boom)
    img, _ = _render(layer)
    assert len(_inked(img)) > 500
    # Engine outputs changing (every update cycle) re-collect but reuse the
    # geometry: only a new commit, FPLLDSEQ or MAGVAR rebuilds it.
    fix.db.set_value("FPLACTLEG", 3)
    fix.db.set_value("FPLXTK", 0.2)
    layer.collect(None)
    assert layer._snapshot is snap


def test_procedure_paint_within_perf_budget(fix, qtbot):
    _load(fix, seq=1, loaded_seq=1)
    owner = _owner(qtbot)
    owner.perf = MapPerfStats()
    layer = fp_layer.FlightPlanLayer()
    layer.configure(owner)
    x = moving_map.MapTransform(*RW28, 10.0, 30.0, 650, 1040, 0.5)
    img = QImage(650, 1040, QImage.Format.Format_RGB32)
    p = QPainter(img)
    layer.paint(p, x)            # warm-up (first QFont)
    p.end()
    gc.collect()
    p = QPainter(img)
    layer.paint(p, x)
    p.end()
    assert owner.perf.layer("flight_plan").last_render_ms <= 25.0
