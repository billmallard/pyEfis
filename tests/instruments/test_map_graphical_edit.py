#  SPDX-License-Identifier: GPL-2.0-or-later
"""FP10: graphical flight plan editing on the moving map
(billmallard/pyEfis#186).

Headless DoD: the hit-test picks the right object at 12 px and none at 13;
stacked objects all reach the chooser; banner Direct To writes ``DTO*``
(``MAPWPT``/``map`` for a bare point) and issues ``DTO``; Insert lands in the
right leg; recenter is still reachable. Bus writes are asserted on what pyEfis
queued for the gateway, not on its local copy -- ``set_value`` alone never
leaves the display.
"""

import math

import numpy as np
import pytest
from PyQt6.QtCore import QPointF, Qt

from pyefis import hmi
from pyefis.flightplan import fixbridge
from pyefis.flightplan import model as fp_model
from pyefis.flightplan.waypoints import Waypoint
from pyefis.instruments import map as moving_map
from pyefis.instruments.flight_plan import FlightPlan
from pyefis.instruments.map.layers.terrain import TerrainLayer
from tests.instruments.test_map_flight_plan_layer import _define, _define_all_fp1_keys

LAT0, LON0 = 34.5, -120.0


class _ReadyDB:
    ready = True


def _map(qtbot, w=400, h=400):
    """North-up 10 NM map at (LAT0, LON0) with its layers built."""
    m = moving_map.MovingMap()
    qtbot.addWidget(m)
    m.resize(w, h)
    m.orientation = "north_up"
    m._lat, m._lon = LAT0, LON0
    m._build_layers()
    return m


def _layer(m, lid):
    return next(layer for layer in m._layers if layer.id == lid)


def _put_airports(m, airports):
    """Inject an airports snapshot: ``[(icao, lat, lon), ...]``."""
    lay = _layer(m, "airports")
    lay._db_all = _ReadyDB()
    lay._snap = ("k", [{"icao": i, "lat": la, "lon": lo, "longest": 5000.0,
                        "hard": True, "rwys": []} for i, la, lo in airports])


def _put_navaids(m, rows):
    lay = _layer(m, "navaids")
    lay._path = "unused.sqlite"
    lay._snap = ("k", rows)


def _world(m, dx, dy):
    """The (lat, lon) that projects dx/dy px from the ownship anchor."""
    x = m._transform()
    return x.to_world(x.cx + dx, x.cy + dy)


def _sent(fix):
    out = []
    for call in fix.db.clientthread.sendqueue.put.call_args_list:
        key, value, _flags = call.args[0].decode().rstrip("\n").split(";")
        out.append((key, value))
    return out


def _tap(m, x, y):
    class _Ev:
        def __init__(self, x, y):
            self._p = QPointF(x, y)

        def button(self):
            return Qt.MouseButton.LeftButton

        def position(self):
            return self._p

        def modifiers(self):
            return Qt.KeyboardModifier.NoModifier

        def accept(self):
            pass

    m.mousePressEvent(_Ev(x, y))
    m.mouseReleaseEvent(_Ev(x, y))


def _paint(m):
    from PyQt6.QtGui import QImage, QPainter
    img = QImage(m.width(), m.height(), QImage.Format.Format_ARGB32)
    m.render(img)
    return img


# ---------------------------------------------------------------------------
# transform inverse
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("rot", [0.0, 37.0, 270.0])
def test_to_world_inverts_to_screen(rot):
    x = moving_map.MapTransform(LAT0, LON0, 10.0, rot, 400, 400, 0.5)
    lat, lon = x.to_world(311.0, 97.0)
    c = x.to_screen(lat, lon)
    assert c.x() == pytest.approx(311.0, abs=1e-6)
    assert c.y() == pytest.approx(97.0, abs=1e-6)


# ---------------------------------------------------------------------------
# hit-test: 12 px in, 13 px out
# ---------------------------------------------------------------------------
def test_hit_test_inclusive_at_12px_none_at_13(fix, qtbot):
    m = _map(qtbot)
    _put_airports(m, [("KSBA", LAT0, LON0)])
    x = m._transform()
    assert [w.id for w in m.hit_test(x.cx + 12.0, x.cy)] == ["KSBA"]
    assert [w.id for w in m.hit_test(x.cx, x.cy - 12.0)] == ["KSBA"]
    assert m.hit_test(x.cx + 13.0, x.cy) == []
    assert m.hit_test(x.cx, x.cy + 13.0) == []
    assert moving_map.HIT_TOL_PX == 12.0


def test_hit_test_picks_the_right_object_and_type(fix, qtbot):
    m = _map(qtbot)
    a_lat, a_lon = _world(m, -60, 0)
    v_lat, v_lon = _world(m, 60, 0)
    n_lat, n_lon = _world(m, 0, 60)
    _put_airports(m, [("KSBA", a_lat, a_lon)])
    _put_navaids(m, [("RZS", "VORTAC", "114.90", v_lat, v_lon),
                     ("SBA", "NDB", "", n_lat, n_lon)])
    x = m._transform()
    (apt,) = m.hit_test(x.cx - 58, x.cy)
    (vor,) = m.hit_test(x.cx + 61, x.cy + 2)
    (ndb,) = m.hit_test(x.cx, x.cy + 55)
    assert (apt.id, apt.type) == ("KSBA", "airport")
    assert (vor.id, vor.type, vor.freq) == ("RZS", "vor", "114.90")
    assert (ndb.id, ndb.type) == ("SBA", "ndb")


def test_hit_test_ignores_disabled_layers_and_range_gates(fix, qtbot):
    m = _map(qtbot)
    _put_airports(m, [("KSBA", LAT0, LON0)])
    x = m._transform()
    m.set_layer("airports", False)
    assert m.hit_test(x.cx, x.cy) == []
    m.set_layer("airports", True)
    m.range_nm = 160.0          # above the airports symbol range: not painted
    x = m._transform()
    assert m.hit_test(x.cx, x.cy) == []


def test_fixes_hit_only_where_painted(fix, qtbot):
    m = _map(qtbot)
    m.set_layer("fixes", True)          # default off (dense)
    lay = _layer(m, "fixes")
    lay._path = "unused.sqlite"
    lay._snap = ("k", [("ELZUS", LAT0, LON0)])
    x = m._transform()
    assert [(w.id, w.type) for w in m.hit_test(x.cx, x.cy)] == [("ELZUS", "fix")]
    m.range_nm = 40.0           # fixes are range-gated at 20 NM
    x = m._transform()
    assert m.hit_test(x.cx, x.cy) == []


def test_plan_waypoints_are_hittable(fix, qtbot):
    _define_all_fp1_keys(fix)
    fixbridge.FixBridge(fix).publish(fp_model.FlightPlan(name="T", waypoints=[
        fp_model.Waypoint(id="HOME", type="user", lat=LAT0, lon=LON0)]))
    m = _map(qtbot)
    x = m._transform()
    assert [(w.id, w.type) for w in m.hit_test(x.cx + 5, x.cy)] == [("HOME", "user")]


# ---------------------------------------------------------------------------
# tap -> pointer / banner / stacked chooser
# ---------------------------------------------------------------------------
def test_tap_on_nothing_places_a_bare_map_point(fix, qtbot):
    m = _map(qtbot)
    x = m._transform()
    _tap(m, x.cx + 40, x.cy - 30)
    ptr = m.pointer
    assert ptr is not None and ptr["target"] is None and not ptr["choosing"]
    wp = m.pointer_waypoint()
    assert (wp.id, wp.type) == ("MAPWPT", "map")
    c = x.to_screen(wp.lat, wp.lon)
    assert (c.x(), c.y()) == pytest.approx((x.cx + 40, x.cy - 30), abs=1e-6)


def test_tap_on_one_object_opens_its_banner(fix, qtbot):
    m = _map(qtbot)
    _put_airports(m, [("KSBA", LAT0, LON0)])
    x = m._transform()
    _tap(m, x.cx + 3, x.cy + 3)
    assert m.pointer_waypoint().id == "KSBA"
    title, info = m.pointer_banner_text()
    assert title.startswith("KSBA") and "APT" in title
    assert "NM" in info


def test_stacked_objects_list_all_in_the_chooser(fix, qtbot):
    m = _map(qtbot)
    lat, lon = _world(m, 4, 0)
    _put_airports(m, [("KSBA", LAT0, LON0)])
    _put_navaids(m, [("SBA", "NDB", "", lat, lon),
                     ("RZS", "VORTAC", "114.90", *_world(m, -6, 5))])
    x = m._transform()
    _tap(m, x.cx + 1, x.cy)
    ptr = m.pointer
    assert ptr["choosing"] and m.pointer_waypoint() is None
    assert [w.id for w in ptr["objects"]] == ["KSBA", "SBA", "RZS"]   # nearest first
    _paint(m)   # chooser registers one row per object + CANCEL
    panel = m._ui_targets[0][0]
    rows = [r for r, _cb in m._ui_targets[1:]]
    assert all(panel.contains(r) for r in rows)
    assert len(rows) == 3 + 1
    # Tapping the second row picks SBA; the banner then acts on it.
    second = rows[1]
    _tap(m, second.center().x(), second.center().y())
    assert not m.pointer["choosing"]
    assert m.pointer_waypoint().id == "SBA"


def test_second_tap_away_clears_and_banner_tap_does_not(fix, qtbot):
    m = _map(qtbot)
    x = m._transform()
    _tap(m, x.cx + 40, x.cy - 30)
    _paint(m)
    panel = m._ui_targets[0][0]
    _tap(m, panel.left() + 3, panel.top() + 3)     # banner body: stays up
    assert m.pointer is not None
    _tap(m, x.cx - 80, x.cy - 80)                  # away: clears, no new pointer
    assert m.pointer is None


def test_drag_does_not_place_a_pointer(fix, qtbot):
    m = _map(qtbot)

    class _Ev:
        def __init__(self, x, y):
            self._p = QPointF(x, y)

        def button(self):
            return Qt.MouseButton.LeftButton

        def position(self):
            return self._p

        def modifiers(self):
            return Qt.KeyboardModifier.NoModifier

        def accept(self):
            pass

    m.mousePressEvent(_Ev(100, 100))
    m.mouseMoveEvent(_Ev(140, 100))
    m.mouseReleaseEvent(_Ev(140, 100))
    assert m.pointer is None and m.is_offset


# ---------------------------------------------------------------------------
# recenter stays reachable
# ---------------------------------------------------------------------------
def test_double_tap_recenters_and_drops_the_pointer(fix, qtbot):
    m = _map(qtbot)
    m.pan_by(50, 0)
    assert m.is_offset
    x = m._transform()
    _tap(m, x.cx, x.cy)            # first tap of the pair places a pointer

    class _Dbl:
        def accept(self):
            pass

    m.mouseDoubleClickEvent(_Dbl())
    assert not m.is_offset and m.pointer is None


def test_ctr_chip_is_a_recenter_soft_key(fix, qtbot):
    m = _map(qtbot)
    m.rotate_by(20.0)
    _paint(m)
    chip = [r for r, cb in m._ui_targets if cb == m.recenter]
    assert len(chip) == 1
    _tap(m, chip[0].center().x(), chip[0].center().y())
    assert not m.is_offset and m.pointer is None


def test_single_tap_no_longer_recenters(fix, qtbot):
    m = _map(qtbot)
    m.pan_by(50, 0)
    _tap(m, 30, 300)
    assert m.is_offset


# ---------------------------------------------------------------------------
# banner Direct To
# ---------------------------------------------------------------------------
def test_direct_to_bare_point_writes_mapwpt_and_issues_dto(fix, qtbot):
    _define_all_fp1_keys(fix)
    m = _map(qtbot)
    x = m._transform()
    _tap(m, x.cx + 40, x.cy - 30)
    lat, lon = m.pointer["lat"], m.pointer["lon"]
    fix.db.clientthread.sendqueue.reset_mock()
    m.banner_direct_to()
    sent = _sent(fix)
    d = dict(sent)
    assert d["DTOID"] == "MAPWPT"
    assert int(d["DTOTYPE"]) == fixbridge.TYPE_TO_FPLTYPE["map"] == 6
    assert float(d["DTOLAT"]) == pytest.approx(lat, abs=1e-6)
    assert float(d["DTOLON"]) == pytest.approx(lon, abs=1e-6)
    keys = [k for k, _v in sent]
    assert keys.index("FPLCMD") > max(keys.index(k) for k in
                                      ("DTOID", "DTOLAT", "DTOLON", "DTOTYPE"))
    assert d["FPLCMD"].split()[1:] == ["DTO"]
    assert m.pointer is None


def test_direct_to_toast_reports_the_engine_answer(fix, qtbot):
    """The banner says what the engine did: nothing until FPLCMDACK, then
    DIRECT TO on success or FPLMSG on rejection (bench: NO POSITION)."""
    _define_all_fp1_keys(fix)
    m = _map(qtbot)
    _put_navaids(m, [("RZS", "VORTAC", "114.90", LAT0, LON0)])
    x = m._transform()
    _tap(m, x.cx, x.cy)
    m.banner_direct_to()
    assert m._toast == ""
    seq = int(fix.db.get_item("FPLCMD").value.split()[0])
    fix.db.set_value("FPLMSG", "NO POSITION")
    fix.db.set_value("FPLCMDACK", -seq)
    assert m._toast == "REJECTED: NO POSITION"
    _tap(m, x.cx, x.cy)
    m.banner_direct_to()
    seq = int(fix.db.get_item("FPLCMD").value.split()[0])
    fix.db.set_value("FPLMSG", "")
    fix.db.set_value("FPLCMDACK", seq)
    assert m._toast == "DIRECT TO RZS"


def test_direct_to_object_stages_its_ident_and_type(fix, qtbot):
    _define_all_fp1_keys(fix)
    m = _map(qtbot)
    _put_navaids(m, [("RZS", "VORTAC", "114.90", LAT0, LON0)])
    x = m._transform()
    _tap(m, x.cx, x.cy)
    fix.db.clientthread.sendqueue.reset_mock()
    m.banner_direct_to()
    d = dict(_sent(fix))
    assert d["DTOID"] == "RZS"
    assert int(d["DTOTYPE"]) == fixbridge.TYPE_TO_FPLTYPE["vor"]
    assert d["FPLCMD"].split()[1:] == ["DTO"]


def test_direct_to_without_the_flight_plan_keys_is_a_message_not_a_crash(fix, qtbot):
    m = _map(qtbot)
    x = m._transform()
    _tap(m, x.cx + 40, x.cy)
    m.banner_direct_to()
    assert m._toast == "NO FLIGHT PLAN"
    assert m.pointer is not None
    _paint(m)
    # Direct To / Insert draw disabled: no tap target for them.
    labels = {cb.__name__ for _r, cb in m._ui_targets if hasattr(cb, "__name__")}
    assert "banner_direct_to" not in labels and "banner_insert" not in labels


# ---------------------------------------------------------------------------
# banner Insert
# ---------------------------------------------------------------------------
def _three_leg_plan():
    # A west-to-east line of four fixes 0.2 deg apart: legs 1, 2, 3.
    return fp_model.FlightPlan(name="T", waypoints=[
        fp_model.Waypoint(id=f"W{i}", type="fix", lat=LAT0, lon=LON0 + 0.2 * i)
        for i in range(4)])


@pytest.mark.parametrize("lon_off, lat_off, expect", [
    (0.1, 0.02, 1),      # beside leg W0-W1
    (0.3, -0.03, 2),     # beside leg W1-W2
    (0.5, 0.01, 3),      # beside leg W2-W3
    (-0.3, 0.0, 1),      # behind the departure: nearest is the first leg
    (0.9, 0.0, 3),       # past the destination: before the last waypoint
])
def test_insert_index_picks_the_nearest_leg(lon_off, lat_off, expect):
    wps = _three_leg_plan().waypoints
    assert moving_map.insert_index(wps, LAT0 + lat_off, LON0 + lon_off) == expect


def test_insert_index_appends_without_a_leg():
    one = fp_model.FlightPlan(waypoints=[fp_model.Waypoint(id="A", type="fix",
                                                           lat=LAT0, lon=LON0)])
    assert moving_map.insert_index([], LAT0, LON0) is None
    assert moving_map.insert_index(one.waypoints, LAT0, LON0 + 1) is None


def test_insert_lands_in_the_right_leg_on_the_bus(fix, qtbot):
    _define_all_fp1_keys(fix)
    fixbridge.FixBridge(fix).publish(_three_leg_plan())
    m = _map(qtbot)
    m.range_nm = 40.0
    lay = _layer(m, "navaids")
    lay._path = "unused.sqlite"
    lay._snap = ("k", [("RZS", "VORTAC", "114.90", LAT0 + 0.03, LON0 + 0.3)])
    x = m._transform()
    c = x.to_screen(LAT0 + 0.03, LON0 + 0.3)
    _tap(m, c.x(), c.y())
    assert m.pointer_waypoint().id == "RZS"
    seq0 = fix.db.get_item("FPLSEQ").value
    m.banner_insert()
    plan = fixbridge.FixBridge(fix).read_plan()
    assert [w.id for w in plan.waypoints] == ["W0", "W1", "RZS", "W2", "W3"]
    assert plan.waypoints[2].type == "vor"
    assert fix.db.get_item("FPLSEQ").value == seq0 + 1
    assert m.pointer is None and m._toast == "INSERTED RZS"


def test_insert_bare_point_into_empty_plan_appends_mapwpt(fix, qtbot):
    _define_all_fp1_keys(fix)
    m = _map(qtbot)
    x = m._transform()
    _tap(m, x.cx + 20, x.cy + 20)
    m.banner_insert()
    plan = fixbridge.FixBridge(fix).read_plan()
    assert [(w.id, w.type) for w in plan.waypoints] == [("MAPWPT", "map")]


def test_fpl_instrument_follows_a_map_insert(fix, qtbot):
    """The FPL page re-reads the bus on FPLSEQ: a map Insert shows there."""
    _define_all_fp1_keys(fix)
    fpl = FlightPlan(None)
    qtbot.addWidget(fpl)
    fpl._plan = _three_leg_plan()
    fpl._commit()
    m = _map(qtbot)
    x = m._transform()
    _tap(m, *(lambda c: (c.x(), c.y()))(x.to_screen(LAT0 + 0.02, LON0 + 0.5)))
    m.banner_insert()
    assert [w.id for w in fpl._plan.waypoints] == ["W0", "W1", "W2", "MAPWPT", "W3"]


# ---------------------------------------------------------------------------
# banner Create WPT / Info -> the flight_plan instrument
# ---------------------------------------------------------------------------
def test_create_wpt_opens_the_user_form_prefilled_at_the_pointer(fix, qtbot):
    _define_all_fp1_keys(fix)
    hmi.initialize({})
    fpl = FlightPlan(None)
    qtbot.addWidget(fpl)
    m = _map(qtbot)
    x = m._transform()
    _tap(m, x.cx + 40, x.cy - 30)
    lat, lon = m.pointer["lat"], m.pointer["lon"]
    m.banner_create_wpt()
    assert m.pointer is None
    assert fpl._page == "entry" and fpl._entry_tab == "User"
    assert fpl._modal["title"].startswith("IDENT")
    fpl._modal_enter()                    # ident blank = auto
    fpl._modal_enter()                    # comment blank
    assert fpl._modal["title"] == "LAT"
    assert fpl._parse_latlon_entry(fpl._modal["value"], True) == pytest.approx(lat, abs=1e-4)
    fpl._modal_enter()
    assert fpl._modal["title"] == "LON"
    assert fpl._parse_latlon_entry(fpl._modal["value"], False) == pytest.approx(lon, abs=1e-4)


def test_info_opens_wpt_info_on_the_flight_plan_instrument(fix, qtbot):
    _define_all_fp1_keys(fix)
    hmi.initialize({})
    fpl = FlightPlan(None)
    qtbot.addWidget(fpl)
    fpl._page = "catalog"
    m = _map(qtbot)
    _put_navaids(m, [("RZS", "VORTAC", "114.90", LAT0, LON0)])
    x = m._transform()
    _tap(m, x.cx, x.cy)
    m.banner_info()
    assert fpl._page == "fpl"
    assert fpl._wpt_info is not None and fpl._wpt_info.id == "RZS"


def test_reveal_switches_the_tab_holding_the_widget(qtbot):
    from PyQt6.QtWidgets import QStackedWidget, QTabBar, QWidget
    from pyefis.instruments import tab_section

    ts = tab_section.TabSection.__new__(tab_section.TabSection)
    QWidget.__init__(ts)
    qtbot.addWidget(ts)
    ts.tab_bar = QTabBar(ts)
    ts.stack = QStackedWidget(ts)
    pages = [QWidget(), QWidget()]
    ts._pages = pages
    for i, pg in enumerate(pages):
        ts.tab_bar.addTab(str(i))
        ts.stack.addWidget(pg)
    target = QWidget(pages[1])
    ts._show_tab(0)
    tab_section.reveal(target)
    assert ts.stack.currentIndex() == 1 and ts.tab_bar.currentIndex() == 1
    tab_section.reveal(QWidget())          # not in any section: no-op, no raise


# ---------------------------------------------------------------------------
# banner info line + terrain elevation
# ---------------------------------------------------------------------------
class _FlatCache:
    def get(self, la, lo):
        return np.full((1201, 1201), 300.0, dtype=np.float32)


def test_terrain_elevation_at_the_pointer():
    lay = TerrainLayer()
    assert lay.elevation_ft(LAT0, LON0) is None          # no tiles configured
    lay._cache = _FlatCache()
    assert lay.elevation_ft(LAT0, LON0) == pytest.approx(300.0 * 3.28084, rel=1e-4)


def test_banner_text_bearing_distance_and_elevation(fix, qtbot):
    m = _map(qtbot)
    _layer(m, "terrain")._cache = _FlatCache()
    lat, lon = LAT0, LON0 + 10.0 / (60.0 * math.cos(math.radians(LAT0)))
    m._pointer = {"lat": lat, "lon": lon, "objects": [], "target": None,
                  "choosing": False, "elev_ft": 984.0}
    title, info = m.pointer_banner_text()
    assert title.startswith("MAP POINT  34 30.00N 119 ")
    # Due east, ~10 NM; no MAGVAR key in the fixture -> labelled true.
    assert info.startswith("090°T  10.0 NM") or info.startswith("090°T  9.9 NM")
    assert "ELEV 984 FT" in info


def test_banner_paints_with_and_without_the_bus(fix, qtbot):
    m = _map(qtbot)
    x = m._transform()
    _tap(m, x.cx + 40, x.cy)
    _paint(m)
    _define_all_fp1_keys(fix)
    m._fp_bridge = None
    _paint(m)
    names = {getattr(cb, "__name__", "") for _r, cb in m._ui_targets}
    assert {"banner_direct_to", "banner_insert", "banner_create_wpt",
            "banner_info", "clear_pointer"} <= names
