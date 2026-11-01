#  SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for the moving-map `flight_plan` layer (FP6, billmallard/pyEfis#184).

Two tiers: pure geometry/color logic (``build_legs``/``build_symbols``/
``build_direct_to``/``build_dto_symbol``/``build_extension``) needs no Qt at
all and is tested directly against ``fixbridge`` dataclasses; the
QPainter-facing behaviour (paint-never-raises, the perf budget, the
``layer_flight_plan`` Prop, declutter, and the leg colors landing on the
right pixels) uses the repo's ``fix``/``qtbot`` fixtures, the same pattern
``tests/instruments/flight_plan/test_flight_plan.py`` uses for FP1 keys.
"""

import gc

import pytest
from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtWidgets import QWidget

from pyefis.flightplan import fixbridge
from pyefis.flightplan import model as fp_model
from pyefis.instruments import map as moving_map
from pyefis.instruments.map.layers import flight_plan as fp_layer
from pyefis.instruments.map.perf import MapPerfStats

# ---------------------------------------------------------------------------
# pure logic: build_legs / build_symbols / build_direct_to / build_dto_symbol
# / build_extension -- no Qt required.
# ---------------------------------------------------------------------------
def _route(n, roles=None):
    wps = [fixbridge.RouteSlot(id=f"WP{i}", lat=float(i), lon=float(i),
                                type="fix", role="none") for i in range(n)]
    for idx, role in (roles or {}).items():
        wps[idx].role = role
    return fixbridge.RouteBlock(name="TEST", seq=1, waypoints=wps)


def _engine(**overrides):
    base = {"FPLSTATE": 0, "FPLACTLEG": 0, "FPLAPR": 0,
            "FPLFRLAT": 0.0, "FPLFRLON": 0.0, "WPLAT": 0.0, "WPLON": 0.0,
            "FPLCRS": 0.0}
    base.update(overrides)
    return {k: fixbridge.ItemValue(value=v, old=False, bad=False, fail=False)
            for k, v in base.items()}


def test_build_legs_past_active_future_by_slot():
    # FPLACTLEG is the TO waypoint's 1-based slot number: leg i (0-based,
    # slots[i]->slots[i+1]) has TO-waypoint slot number i+2. act_leg=3 ->
    # leg 1 (slots[1]->slots[2]) is active.
    route = _route(4)
    engine = _engine(FPLSTATE=1, FPLACTLEG=3, FPLFRLAT=1.0, FPLFRLON=1.0,
                      WPLAT=2.0, WPLON=2.0)
    legs = fp_layer.build_legs(route, engine)
    assert legs[0][0] == fp_layer.PAST      # leg 0->1, to_idx=2 < act_leg
    assert legs[1][0] == fp_layer.ACTIVE    # leg 1->2, to_idx=3 == act_leg
    assert legs[2][0] == fp_layer.FUTURE    # leg 2->3, to_idx=4 > act_leg


def test_active_leg_from_point_is_fplfrlat_not_previous_slot():
    """A direct-to activation point differs from the previous route slot --
    the active leg must start there, not at slots[i]. act_leg=2 -> leg 0
    (slots[0]->slots[1], to_idx=2) is active."""
    route = _route(3)  # slot coords (0,0), (1,1), (2,2)
    engine = _engine(FPLSTATE=2, FPLACTLEG=2, FPLFRLAT=9.0, FPLFRLON=9.0,
                      WPLAT=2.0, WPLON=2.0)
    legs = fp_layer.build_legs(route, engine)
    color, frm, to = legs[0]
    assert color == fp_layer.ACTIVE
    assert frm == (9.0, 9.0)
    assert to == (2.0, 2.0)
    assert legs[1][0] == fp_layer.FUTURE    # leg 1->2, to_idx=3 > act_leg


def test_act_leg_one_is_a_synthetic_segment_from_aircraft_position():
    """FPLACTLEG=1 (a freshly activated plan, or ACT 1) has no previous
    route slot at all -- FPLFRLAT/LON is the aircraft's live position, not
    slots[-1] -- so every real route leg is still ahead."""
    route = _route(3)
    engine = _engine(FPLSTATE=1, FPLACTLEG=1, FPLFRLAT=5.0, FPLFRLON=5.0,
                      WPLAT=0.0, WPLON=0.0)
    legs = fp_layer.build_legs(route, engine)
    assert legs[0] == (fp_layer.ACTIVE, (5.0, 5.0), (0.0, 0.0))
    assert legs[1][0] == fp_layer.FUTURE    # slots[0]->slots[1]
    assert legs[2][0] == fp_layer.FUTURE    # slots[1]->slots[2]
    assert len(legs) == 3


def test_off_route_direct_to_plan_gray_plus_separate_magenta_line():
    route = _route(3)
    engine = _engine(FPLSTATE=2, FPLACTLEG=0, FPLFRLAT=5.0, FPLFRLON=5.0)
    legs = fp_layer.build_legs(route, engine)
    assert all(color == fp_layer.PAST for color, _, _ in legs)
    dto = fixbridge.DirectTo(id="RZS", lat=10.0, lon=10.0, type="vor")
    direct = fp_layer.build_direct_to(route, engine, dto)
    assert direct == (fp_layer.ACTIVE, (5.0, 5.0), (10.0, 10.0))


def test_build_direct_to_none_when_on_route():
    route = _route(3)
    engine = _engine(FPLSTATE=1, FPLACTLEG=1)
    dto = fixbridge.DirectTo(id="X", lat=1.0, lon=1.0, type="fix")
    assert fp_layer.build_direct_to(route, engine, dto) is None


def test_build_direct_to_none_without_dto():
    route = _route(3)
    engine = _engine(FPLSTATE=2, FPLACTLEG=0)
    assert fp_layer.build_direct_to(route, engine, None) is None


def test_build_symbols_role_suffix():
    route = _route(3, roles={2: "faf"})
    syms = fp_layer.build_symbols(route, _engine())
    assert syms[0][4] == "WP0"
    assert syms[2][4] == "WP2 FAF"


def test_build_symbols_to_waypoint_ringed():
    route = _route(3)
    engine = _engine(FPLSTATE=1, FPLACTLEG=2)
    syms = fp_layer.build_symbols(route, engine)
    assert [s[5] for s in syms] == [False, True, False]
    assert [s[0] for s in syms] == [fp_layer.PAST, fp_layer.ACTIVE, fp_layer.FUTURE]


def test_build_dto_symbol_only_when_off_route():
    route = _route(2)
    dto = fixbridge.DirectTo(id="RZS", lat=1.0, lon=2.0, type="vor")
    assert fp_layer.build_dto_symbol(route, _engine(FPLSTATE=1, FPLACTLEG=1), dto) is None
    sym = fp_layer.build_dto_symbol(route, _engine(FPLSTATE=2, FPLACTLEG=0), dto)
    assert sym == (fp_layer.ACTIVE, 1.0, 2.0, "vor", "RZS", True)


def test_build_extension_only_when_suspended_at_map_with_lnav():
    route = _route(3, roles={2: "map"})
    assert fp_layer.build_extension(route, _engine(FPLSTATE=1, FPLAPR=2)) is None
    assert fp_layer.build_extension(route, _engine(FPLSTATE=3, FPLAPR=1)) is None
    ext = fp_layer.build_extension(route, _engine(FPLSTATE=3, FPLAPR=2, FPLCRS=90.0))
    assert ext is not None
    (la1, lo1), (la2, lo2) = ext
    assert (la1, lo1) == (route.waypoints[2].lat, route.waypoints[2].lon)
    assert lo2 > lo1                      # projected east (bearing 90)
    assert la2 == pytest.approx(la1, abs=0.05)


def test_build_extension_none_without_map_role():
    route = _route(3)
    engine = _engine(FPLSTATE=3, FPLAPR=2, FPLCRS=90.0)
    assert fp_layer.build_extension(route, engine) is None


def test_declutter_range_constants():
    assert fp_layer._IDENT_RANGE == 80.0
    assert fp_layer._SYMBOL_RANGE == 160.0


# ---------------------------------------------------------------------------
# Qt-facing: paint-never-raises, perf budget, the Prop, declutter, colors.
# ---------------------------------------------------------------------------
_WIDE_BOUNDS = {"float": (-1e9, 1e9), "int": (-1_000_000, 1_000_000),
                "bool": (None, None), "str": (None, None)}
_ENGINE_DTYPES = {
    "FPLSTATE": "int", "FPLACTLEG": "int", "FPLPHASE": "str", "FPLAPR": "int",
    "FPLINTEG": "bool", "CDISCALE": "float", "FPLCRS": "float", "FPLXTK": "float",
    "FPLCDI": "float", "FPLTF": "int", "FPLFRLAT": "float", "FPLFRLON": "float",
    "WPNAME": "str", "WPLAT": "float", "WPLON": "float", "WPFROM": "str",
    "WPNEXT": "str", "WPDIS": "float", "WPETE": "int", "FPLREMDIS": "float",
    "FPLREMETE": "int", "FPLALERT": "bool", "GPSSRC": "int",
    "FPLACTSEG": "int", "FPLSEGREM": "float",
}
_ENGINE_DEFAULTS = {"int": 0, "float": 0.0, "bool": False, "str": ""}


def _define(fix, key, dtype, value):
    mn, mx = _WIDE_BOUNDS[dtype]
    fix.db.define_item(key, key, dtype, mn, mx, "", 0, "")
    fix.db.set_value(key, value)
    fix.db.get_item(key).bad = False
    fix.db.get_item(key).fail = False


def _define_all_fp1_keys(fix):
    for key, dtype, blank in fixbridge.route_key_specs():
        _define(fix, key, dtype, blank)
    for key, dtype in _ENGINE_DTYPES.items():
        _define(fix, key, dtype, _ENGINE_DEFAULTS[dtype])


def _publish_plan(fix, n, roles=None):
    _define_all_fp1_keys(fix)
    bridge = fixbridge.FixBridge(fix)
    wps = [fp_model.Waypoint(id=f"WP{i:02d}", type="fix",
                              lat=34.0 + i * 0.1, lon=-119.0 - i * 0.1)
           for i in range(n)]
    for idx, role in (roles or {}).items():
        wps[idx].role = role
    bridge.publish(fp_model.FlightPlan(name="TEST", waypoints=wps))
    return bridge


class _Owner(QWidget):
    """A minimal QWidget stand-in for MovingMap: _BridgeRelay needs a real
    QObject (it parents itself to ``owner`` and connects to ``owner.update``,
    both of which a plain Python object can't provide)."""

    perf = None


def _owner(qtbot):
    w = _Owner()
    qtbot.addWidget(w)
    return w


def test_construct_and_paint_with_no_gateway_keys(fix, qtbot):
    owner = _Owner()
    qtbot.addWidget(owner)
    layer = fp_layer.FlightPlanLayer()
    layer.configure(owner)
    assert layer._bridge.available is False
    x = moving_map.MapTransform(34.0, -119.0, 10.0, 0.0, 200, 200, 0.5)
    img = QImage(200, 200, QImage.Format.Format_RGB32)
    img.fill(0)
    p = QPainter(img)
    layer.paint(p, x)   # must not raise
    p.end()
    assert img.pixelColor(100, 100) == QColor(0, 0, 0)   # nothing drawn


def test_paint_50_waypoints_within_perf_budget(fix, qtbot):
    _publish_plan(fix, 50)
    fix.db.set_value("FPLSTATE", 1)
    fix.db.set_value("FPLACTLEG", 25)

    owner = _Owner()
    qtbot.addWidget(owner)
    owner.perf = MapPerfStats()
    layer = fp_layer.FlightPlanLayer()
    layer.configure(owner)
    assert layer._bridge.available is True

    x = moving_map.MapTransform(34.0, -119.0, 40.0, 0.0, 650, 1040, 0.5)
    img = QImage(650, 1040, QImage.Format.Format_RGB32)

    # One untimed warm-up paint: the first QFont a process ever requests
    # can pay a one-time font-cache/fallback-scan cost (sandboxes with a
    # broken fontconfig make this dramatic) that steady-state repaints
    # never pay again -- exactly the kind of cold start the DoD's
    # "generous CI ceiling" is there to absorb, not a per-frame budget.
    p = QPainter(img)
    layer.paint(p, x)
    p.end()

    # Collect right before the timed paint, not during it (AER-2158): the
    # generational GC's collection point is driven by a process-global
    # allocation count, not a per-test one, so whatever ran earlier in this
    # process -- entirely unrelated tests -- can leave the count close enough
    # to threshold that this layer's own paint()-time allocations tip it over
    # and land a stop-the-world sweep inside the timed window, inflating
    # last_render_ms with a pause this layer didn't cause and can't control.
    # Starting the timed section from a clean count is what makes the
    # measurement about this layer's render cost again.
    gc.collect()

    p = QPainter(img)
    layer.paint(p, x)
    p.end()

    # DoD: perf.layer("flight_plan") <= 1 ms at 50 waypoints, generous CI ceiling.
    assert owner.perf.layer("flight_plan").last_render_ms <= 25.0


def test_layer_flight_plan_default_enabled(fix, qtbot):
    w = moving_map.MovingMap(None)
    qtbot.addWidget(w)
    w.resize(300, 300)
    w._build_layers()
    layer = next(l for l in w._layers if l.id == "flight_plan")
    assert layer.enabled is True


def test_layer_flight_plan_prop_false_disables_layer(fix, qtbot):
    w = moving_map.MovingMap(None)
    qtbot.addWidget(w)
    w.layer_flight_plan = False
    w.resize(300, 300)
    w._build_layers()
    layer = next(l for l in w._layers if l.id == "flight_plan")
    assert layer.enabled is False


def test_active_leg_pixel_is_magenta_past_leg_is_gray(fix, qtbot):
    # 4-slot plan: WP00=(34.0,-119.0) .. WP03=(34.3,-119.3). FPLACTLEG=3 ->
    # leg 1 (WP01->WP02, to_idx=3) is active, leg 0 (WP00->WP01) is past.
    _publish_plan(fix, 4)
    fix.db.set_value("FPLSTATE", 1)
    fix.db.set_value("FPLACTLEG", 3)
    fix.db.set_value("FPLFRLAT", 34.1)
    fix.db.set_value("FPLFRLON", -119.1)
    fix.db.set_value("WPLAT", 34.2)
    fix.db.set_value("WPLON", -119.2)

    layer = fp_layer.FlightPlanLayer()
    layer.configure(_owner(qtbot))
    x = moving_map.MapTransform(34.0, -119.0, 20.0, 0.0, 400, 400, 0.5)
    img = QImage(400, 400, QImage.Format.Format_RGB32)
    img.fill(0)
    p = QPainter(img)
    layer.paint(p, x)
    p.end()

    def sample(lat, lon):
        c = x.to_screen(lat, lon)
        return img.pixelColor(int(round(c.x())), int(round(c.y())))

    active_mid = sample(34.15, -119.15)   # midpoint of the active leg (WP01->WP02)
    past_mid = sample(34.05, -119.05)     # midpoint of the past leg (WP00->WP01)
    assert active_mid.red() > 200 and active_mid.blue() > 200 and active_mid.green() < 80
    assert abs(past_mid.red() - past_mid.green()) < 20 and past_mid.red() > 80


def test_labels_off_above_ident_range_symbols_stay(fix, qtbot):
    _publish_plan(fix, 2)
    layer = fp_layer.FlightPlanLayer()
    layer.configure(_owner(qtbot))

    def render(range_nm):
        x = moving_map.MapTransform(34.0, -119.0, range_nm, 0.0, 400, 400, 0.5)
        img = QImage(400, 400, QImage.Format.Format_RGB32)
        img.fill(0)
        p = QPainter(img)
        layer.paint(p, x)
        p.end()
        return img, x

    img_close, x_close = render(50.0)     # <= 80 NM: labels on
    img_far, x_far = render(100.0)        # > 80 NM: labels off, symbols stay

    def label_region_has_ink(img, x):
        c = x.to_screen(34.0, -119.0)
        r = max(5.0, min(12.0, x.w * 0.016))
        y0 = int(c.y() + r + 1)
        for dx in range(-40, 41):
            for dy in range(0, 14):
                px = img.pixelColor(int(c.x()) + dx, y0 + dy)
                if px != QColor(0, 0, 0):
                    return True
        return False

    def symbol_is_drawn(img, x):
        c = x.to_screen(34.0, -119.0)
        return img.pixelColor(int(c.x()), int(c.y())) != QColor(0, 0, 0) \
            or img.pixelColor(int(c.x()) + 6, int(c.y())) != QColor(0, 0, 0)

    assert label_region_has_ink(img_close, x_close)
    assert not label_region_has_ink(img_far, x_far)
    assert symbol_is_drawn(img_far, x_far)


def test_nothing_but_legs_above_symbol_range(fix, qtbot):
    _publish_plan(fix, 2)
    layer = fp_layer.FlightPlanLayer()
    layer.configure(_owner(qtbot))

    x = moving_map.MapTransform(34.0, -119.0, 200.0, 0.0, 400, 400, 0.5)
    img = QImage(400, 400, QImage.Format.Format_RGB32)
    img.fill(0)
    p = QPainter(img)
    layer.paint(p, x)
    p.end()

    c = x.to_screen(34.0, -119.0)
    # The waypoint symbol itself must not draw above _SYMBOL_RANGE; a small
    # patch around the (would-be) symbol centre, away from the leg line,
    # must stay background.
    off_leg = img.pixelColor(int(c.x()) + 20, int(c.y()) - 20)
    assert off_leg == QColor(0, 0, 0)


# ---------------------------------------------------------------------------
# RS4 (pyEfis #307): airway ident labels and active-segment emphasis, read
# from the segment table. The golden route "KSBA RZS GVO V27 AVOLS KSMX" as
# the fix-gateway contract doc lays it out: V27 is segment 3, slots 3..7.
# ---------------------------------------------------------------------------
_GOLDEN_IDS = ["KSBA", "RZS", "GVO", "FIX1", "FIX2", "FIX3", "AVOLS", "KSMX"]
_GOLDEN_SGI = [1, 2, 3, 3, 3, 3, 3, 4]


def _golden_route(lat=34.0):
    # Along one parallel, so every leg is horizontal on a north-up map.
    slots = [fixbridge.RouteSlot(id=ident, lat=lat, lon=-120.0 + 0.1 * i, type="fix",
                                  role="none", sgi=sgi)
             for i, (ident, sgi) in enumerate(zip(_GOLDEN_IDS, _GOLDEN_SGI))]
    segments = [
        fixbridge.RouteSegment("waypoint", "", "KSBA", "KSBA", 1, 1),
        fixbridge.RouteSegment("waypoint", "", "RZS", "RZS", 2, 2),
        fixbridge.RouteSegment("airway", "V27", "GVO", "AVOLS", 3, 7),
        fixbridge.RouteSegment("waypoint", "", "KSMX", "KSMX", 8, 8),
    ]
    return fixbridge.RouteBlock(name="GOLDEN", seq=1, waypoints=slots, segments=segments)


def test_airway_label_sits_on_the_first_leg_along_the_airway():
    route = _golden_route()
    labels = fp_layer.build_airway_labels(route, _engine())
    # One label, V27, on GVO -> FIX1: not on RZS -> GVO, the direct leg
    # into the entry fix, even though the bus counts it in segment 3.
    assert labels == [(fp_layer.FUTURE, "V27", (34.0, -119.8), (34.0, -119.7))]


def test_airway_label_takes_the_colour_of_its_leg():
    route = _golden_route()
    # FPLACTLEG is the TO slot: 4 = flying GVO -> FIX1, the labelled leg.
    assert fp_layer.build_airway_labels(
        route, _engine(FPLSTATE=1, FPLACTLEG=4))[0][0] == fp_layer.ACTIVE
    assert fp_layer.build_airway_labels(
        route, _engine(FPLSTATE=1, FPLACTLEG=6))[0][0] == fp_layer.PAST
    assert fp_layer.build_airway_labels(
        route, _engine(FPLSTATE=2, FPLACTLEG=0))[0][0] == fp_layer.PAST


def test_no_airway_label_without_an_airway_or_a_valid_table():
    # A plan of plain waypoints (no table, or all direct rows) labels nothing.
    assert fp_layer.build_airway_labels(_route(4), _engine()) == []
    # A torn read whose row disagrees with the slots' FPLfSGI labels nothing
    # rather than guessing where the airway is.
    route = _golden_route()
    route.waypoints[4].sgi = 4
    assert fp_layer.build_airway_labels(route, _engine()) == []
    route = _golden_route()
    route.segments[2].last = 9   # past the end of the slots
    assert fp_layer.build_airway_labels(route, _engine()) == []


def test_segment_emphasis_is_the_rest_of_the_active_segment():
    route = _golden_route()
    # Flying GVO -> FIX1 (TO slot 4) inside V27 (segment 3): the legs still
    # ahead in V27 are FIX1->FIX2, FIX2->FIX3, FIX3->AVOLS. AVOLS -> KSMX is
    # segment 4 and is not emphasized.
    legs = fp_layer.build_segment_emphasis(route, _engine(FPLSTATE=1, FPLACTLEG=4,
                                                            FPLACTSEG=3))
    lons = [round(b[1], 1) for _, b in legs]
    assert lons == [-119.6, -119.5, -119.4]
    # Flying RZS -> GVO: the engine already reports V27 (the entry leg is
    # in the airway segment), so the whole airway ahead is emphasized.
    legs = fp_layer.build_segment_emphasis(route, _engine(FPLSTATE=1, FPLACTLEG=3,
                                                            FPLACTSEG=3))
    assert len(legs) == 4
    # On the last leg of the airway nothing is left ahead in it.
    assert fp_layer.build_segment_emphasis(
        route, _engine(FPLSTATE=1, FPLACTLEG=7, FPLACTSEG=3)) == []


def test_segment_emphasis_follows_fplactseg_not_the_active_leg():
    """The segment comes off the bus. With FPLACTSEG 0 (no plan active, an
    off-route direct-to, or a gateway that predates RS1 and never writes it)
    nothing is emphasized, even with the active leg inside the airway."""
    route = _golden_route()
    assert fp_layer.build_segment_emphasis(
        route, _engine(FPLSTATE=1, FPLACTLEG=4, FPLACTSEG=0)) == []
    assert fp_layer.build_segment_emphasis(
        route, _engine(FPLSTATE=1, FPLACTLEG=4)) == []
    assert fp_layer.build_segment_emphasis(
        route, _engine(FPLSTATE=2, FPLACTLEG=0, FPLACTSEG=3)) == []
    # An index past the table, or a row that disagrees with the slots.
    assert fp_layer.build_segment_emphasis(
        route, _engine(FPLSTATE=1, FPLACTLEG=4, FPLACTSEG=9)) == []


def _publish_golden(fix, lat=34.0, airway=True, step=0.1):
    """The golden route on the bus; *airway* False publishes the same fixes
    as plain waypoints, the before-RS4 picture to diff against."""
    _define_all_fp1_keys(fix)
    bridge = fixbridge.FixBridge(fix)
    wps = [fp_model.Waypoint(id=ident, type="fix", lat=lat, lon=-120.0 + step * i)
           for i, ident in enumerate(_GOLDEN_IDS)]
    if not airway:
        bridge.publish(fp_model.FlightPlan(waypoints=wps))
        return bridge
    plan = fp_model.FlightPlan(segments=[
        fp_model.waypoint_segment(wps[0]), fp_model.waypoint_segment(wps[1]),
        fp_model.Segment(kind="airway", ident="V27", legs=wps[2:7]),
        fp_model.waypoint_segment(wps[7])])
    bridge.publish(plan)
    # The bus carries the table the brief describes.
    route = bridge.read_route()
    assert [(s.kind, s.ident, s.first, s.last) for s in route.segments] == [
        ("waypoint", "", 1, 1), ("waypoint", "", 2, 2), ("airway", "V27", 3, 7),
        ("waypoint", "", 8, 8)]
    return bridge


def _render(layer, range_nm=20.0, lat=34.0, lon=-119.75, size=400):
    x = moving_map.MapTransform(lat, lon, range_nm, 0.0, size, size, 0.5)
    img = QImage(size, size, QImage.Format.Format_RGB32)
    img.fill(0)
    p = QPainter(img)
    layer.paint(p, x)
    p.end()
    return img, x


def _ink(img, x0, x1, y0, y1):
    return sum(1 for px in range(x0, x1) for py in range(y0, y1)
               if img.pixelColor(px, py) != QColor(0, 0, 0))


def test_airway_label_paints_above_its_first_leg(fix, qtbot):
    _publish_golden(fix)
    layer = fp_layer.FlightPlanLayer()
    layer.configure(_owner(qtbot))
    img, x = _render(layer)

    def band(lon):
        c = x.to_screen(34.0, lon)
        cx, cy = int(c.x()), int(c.y())
        # A band just above the line, clear of the line and the symbols.
        return _ink(img, cx - 8, cx + 8, cy - 16, cy - 3)

    # Ink above the middle of GVO -> FIX1, none above the middle of the
    # direct legs either side (RZS -> GVO, FIX1 -> FIX2).
    assert band(-119.75) > 10
    assert band(-119.85) == 0
    assert band(-119.65) == 0


def _render_both(fix, qtbot, step=0.1, **kw):
    """(with the airway, as plain waypoints) at the same view."""
    _publish_golden(fix, step=step)
    layer = fp_layer.FlightPlanLayer()
    layer.configure(_owner(qtbot))
    with_awy, _ = _render(layer, **kw)
    _publish_golden(fix, airway=False, step=step)
    plain, _ = _render(layer, **kw)
    return with_awy, plain


def test_airway_label_is_the_only_difference_inside_ident_range(fix, qtbot):
    """The same fixes, legs and symbols as before RS4: the label is all the
    airway adds."""
    with_awy, plain = _render_both(fix, qtbot)
    changed = [(px, py) for px in range(with_awy.width()) for py in range(with_awy.height())
               if with_awy.pixelColor(px, py) != plain.pixelColor(px, py)]
    assert changed
    # Every changed pixel is in the label's box above GVO -> FIX1.
    x = moving_map.MapTransform(34.0, -119.75, 20.0, 0.0, 400, 400, 0.5)
    gvo, fix1 = x.to_screen(34.0, -119.8), x.to_screen(34.0, -119.7)
    assert all(gvo.x() < px < fix1.x() and gvo.y() - 30 < py < gvo.y() for px, py in changed)


def test_airway_label_off_above_ident_range(fix, qtbot):
    # 1 degree legs (about 50 NM), long enough on screen to hold the label
    # at either range, so only the range decides.
    view = {"step": 1.0, "lon": -117.5}
    with_awy, plain = _render_both(fix, qtbot, range_nm=80.0, **view)
    assert with_awy != plain
    with_awy, plain = _render_both(fix, qtbot, range_nm=100.0, **view)
    assert with_awy == plain


def test_airway_label_skipped_when_the_leg_is_too_short_to_hold_it(fix, qtbot):
    # At 80 NM on a 200 px map the 5 NM leg is about 6 px long.
    with_awy, plain = _render_both(fix, qtbot, range_nm=80.0, size=200)
    assert with_awy == plain


def _line_thickness(img, x, lon):
    c = x.to_screen(34.0, lon)
    cx, cy = int(round(c.x())), int(round(c.y()))
    return sum(1 for dy in range(-6, 7) if img.pixelColor(cx, cy + dy) != QColor(0, 0, 0))


def test_active_segment_legs_paint_wider(fix, qtbot):
    _publish_golden(fix)
    fix.db.set_value("FPLSTATE", 1)
    fix.db.set_value("FPLACTLEG", 4)
    fix.db.set_value("FPLFRLAT", 34.0)
    fix.db.set_value("FPLFRLON", -119.8)
    fix.db.set_value("WPLAT", 34.0)
    fix.db.set_value("WPLON", -119.7)
    layer = fp_layer.FlightPlanLayer()
    layer.configure(_owner(qtbot))

    fix.db.set_value("FPLACTSEG", 0)
    img_off, x = _render(layer, lon=-119.55)
    fix.db.set_value("FPLACTSEG", 3)
    img_on, _ = _render(layer, lon=-119.55)

    inside = -119.55    # FIX2 -> FIX3: ahead, in V27
    outside = -119.35   # AVOLS -> KSMX: ahead, segment 4
    assert _line_thickness(img_on, x, inside) > _line_thickness(img_off, x, inside)
    assert _line_thickness(img_on, x, outside) == _line_thickness(img_off, x, outside)
    # Width only: the emphasized leg keeps its own (white) colour.
    c = x.to_screen(34.0, inside)
    px = img_on.pixelColor(int(round(c.x())), int(round(c.y())))
    assert px.red() > 200 and px.green() > 200 and px.blue() > 200
