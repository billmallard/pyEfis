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
}
_ENGINE_DEFAULTS = {"int": 0, "float": 0.0, "bool": False, "str": ""}


def _define(fix, key, dtype, value):
    mn, mx = _WIDE_BOUNDS[dtype]
    fix.db.define_item(key, key, dtype, mn, mx, "", 0, "")
    fix.db.set_value(key, value)
    fix.db.get_item(key).bad = False
    fix.db.get_item(key).fail = False


def _define_all_fp1_keys(fix):
    for n in range(1, fixbridge.MAX_SLOTS + 1):
        id_key, lat_key, lon_key, type_key, role_key = fixbridge._slot_keys(n)
        _define(fix, id_key, "str", "")
        _define(fix, lat_key, "float", 0.0)
        _define(fix, lon_key, "float", 0.0)
        _define(fix, type_key, "int", 0)
        _define(fix, role_key, "int", 0)
    _define(fix, "FPLCOUNT", "int", 0)
    _define(fix, "FPLNAME", "str", "")
    _define(fix, "FPLSEQ", "int", 0)
    _define(fix, "DTOID", "str", "")
    _define(fix, "DTOLAT", "float", 0.0)
    _define(fix, "DTOLON", "float", 0.0)
    _define(fix, "DTOTYPE", "int", 0)
    _define(fix, "FPLCMD", "str", "")
    _define(fix, "FPLCMDACK", "int", 0)
    _define(fix, "FPLMSG", "str", "")
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
