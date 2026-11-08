#  SPDX-License-Identifier: GPL-2.0-or-later
"""ND mode, EXPANDED MAP (G11a, billmallard/pyEfis#134).

Geometry is pinned closed-form against the spec: ownship at ``h * 0.82``
(the HSI arc's ``own_y``), the selected range reaching the compass arc,
track-up whatever ``orientation`` says, and the vertical deviation pointer
at ``y0 - GSI * half`` (the HSI's sign). The data blocks are asserted through
the model functions, which ``paint`` draws verbatim."""

import calendar
import math

import pytest
from PyQt6.QtGui import QImage

import pyefis.hmi.functions as functions
from pyefis.instruments import map as moving_map
from pyefis.instruments.map import nd
from pyefis.screens import screenbuilder_factory as factory

W, H = 800, 480

_DTYPES = {"GS": "float", "TAS": "float", "WINDDIR": "float",
           "WINDSPD": "float", "FPLSTATE": "int", "FPLPHASE": "str",
           "WPNAME": "str", "WPDIS": "float", "WPETE": "int",
           "GSI": "float", "GSV": "float", "MAPNDMODE": "int",
           "TRACKM": "float", "LAT": "float", "LONG": "float"}


def _define(fix, key, value, **flags):
    dtype = _DTYPES[key]
    bounds = (None, None) if dtype == "str" else (-1e6, 1e6)
    fix.db.define_item(key, key, dtype, bounds[0], bounds[1], "", 0, "")
    fix.db.set_value(key, value)
    item = fix.db.get_item(key)
    item.old = item.bad = item.fail = False
    for k, v in flags.items():
        setattr(item, k, v)
    return item


def _reader(fix):
    """A fresh Reader: it caches lookups, and the fix fixture redefines keys."""
    return nd.Reader()


def _texts(lines):
    return [[t for t, _ in line] for line in lines]


def _map(qtbot, **opts):
    m = moving_map.MovingMap(None)
    qtbot.addWidget(m)
    m.resize(W, H)
    for k, v in opts.items():
        setattr(m, k, v)
    return m


# --- mode switch -----------------------------------------------------------

def test_default_is_off_and_registered(fix, qtbot):
    m = _map(qtbot)
    assert m.nd_mode == "off" and not m.nd_active()
    spec = factory.REGISTRY["moving_map"]
    props = {p.name: p for p in spec.properties}
    assert props["nd_mode"].default == "off"
    assert list(props["nd_mode"].enum) == list(nd.ND_MODES)
    assert props["nd_mode"].bindable.key_option == "nd_mode_key"
    assert props["nd_mode_key"].kind == "fixkey"


def test_unknown_mode_reads_as_off(fix, qtbot):
    m = _map(qtbot, nd_mode="plan")
    assert not m.nd_active()
    assert m.view_orientation() == m.orientation


def test_mode_follows_key(fix, qtbot):
    """The orientation_key precedent: the config default seeds the key, then
    the key drives the mode -- 1 = expanded, 0 = off, out of range clamps."""
    _define(fix, "MAPNDMODE", 0)
    m = _map(qtbot, nd_mode="expanded", nd_mode_key="MAPNDMODE")
    m.init_live_bindings(m._live_binding_specs())
    assert fix.db.get_item("MAPNDMODE").value == 1     # seeded from config
    fix.db.set_value("MAPNDMODE", 0)
    assert m.nd_mode == "off" and not m.nd_active()
    fix.db.set_value("MAPNDMODE", 1)
    assert m.nd_mode == "expanded" and m.nd_active()
    fix.db.set_value("MAPNDMODE", 9)
    assert m.nd_mode == nd.ND_MODES[-1]


def test_button_wrap_cycles_modes(fix, qtbot):
    """A button's 'change value wrap' on the key steps off -> expanded -> off
    (key max = the mode count, the MAPORIENT convention)."""
    fix.db.define_item("MAPNDMODE", "MAPNDMODE", "int", 0, len(nd.ND_MODES),
                       "", 0, "")
    fix.db.set_value("MAPNDMODE", 0)
    item = fix.db.get_item("MAPNDMODE")
    item.bad = item.fail = False
    m = _map(qtbot, nd_mode_key="MAPNDMODE")
    m.init_live_bindings(m._live_binding_specs())
    seen = []
    for _ in range(3):
        seen.append(m.nd_mode)
        functions.changeValueWrap("MAPNDMODE,1")
    assert seen == ["off", "expanded", "off"]


# --- geometry --------------------------------------------------------------

def test_off_transform_is_unchanged(qtbot):
    """Off: ownship_position anchors ownship and range reaches the top edge,
    exactly as before the ND existed."""
    m = _map(qtbot, ownship_position=30, orientation="north_up")
    m._track = 72.0
    x = m._transform()
    assert x.cy == pytest.approx(H * 0.7)
    assert x.range_px == pytest.approx(x.cy)
    assert x.nm_to_px(m.range_nm) == pytest.approx(x.cy)
    assert x.rot == 0.0


def test_expanded_anchor_range_and_track_up(qtbot):
    m = _map(qtbot, nd_mode="expanded", ownship_position=30,
             orientation="north_up")
    m._track = 72.0
    x = m._transform()
    g = nd.expanded_geometry(W, H)
    assert x.cy == pytest.approx(H * 0.82)               # HSI arc own_y
    assert g["own_y"] == pytest.approx(H * 0.82)
    # The selected range ends on the compass arc, below the TRK box.
    assert x.nm_to_px(m.range_nm) == pytest.approx(g["r"])
    assert x.cy - g["r"] == pytest.approx(g["apex"])
    assert g["apex"] > 4.0 + g["box_h"]
    # Track-up although orientation says north_up; the setting is kept.
    assert x.rot == pytest.approx(math.radians(72.0))
    assert m.orientation == "north_up"
    m.nd_mode = "off"
    assert m._transform().rot == 0.0


def test_expanded_pan_uses_the_nd_scale(qtbot):
    """pan_by converts px to metres with the same scale the transform uses,
    so a drag moves the map with the finger in ND mode too."""
    m = _map(qtbot, nd_mode="expanded")
    m._track = 0.0
    m.pan_by(0.0, 100.0)
    x = m._transform()
    expect_m = 100.0 * (m.range_nm * moving_map.NM_M) / x.range_px
    assert m._pan_n == pytest.approx(expect_m)


def test_layer_jobs_carry_the_scale(qtbot):
    """Terrain/roads rebuild their px/m from the job: it must be range_px,
    which is cy when the ND is off (byte-identical jobs to before)."""
    x = moving_map.MapTransform(34.0, -119.0, 10.0, 0.0, W, H, 0.18,
                                range_px=300.0)
    assert x._px_per_m == pytest.approx(300.0 / (10.0 * moving_map.NM_M))
    plain = moving_map.MapTransform(34.0, -119.0, 10.0, 0.0, W, H, 0.5)
    assert plain.range_px == plain.cy


def test_arc_half_angle_narrows_on_a_narrow_panel():
    assert nd.arc_half_deg(800, 350) == nd.ARC_HALF_DEG
    half = nd.arc_half_deg(300, 350)
    assert half < nd.ARC_HALF_DEG
    # Both ends inside 96% of the half-width.
    assert 350 * math.sin(math.radians(half)) \
        == pytest.approx(0.96 * 150)


# --- vertical deviation scale ---------------------------------------------

def _absent(_key):
    """A gateway that defines none of the keys."""
    return None


def test_vdev_absent_without_gsi():
    assert nd.vdev(_absent) is None


def test_vdev_pointer_sign_and_peg(fix):
    _define(fix, "GSI", 0.42)
    _define(fix, "GSV", 1.0)
    g = nd.vdev_geometry(W, H)
    st = nd.vdev(_reader(fix))
    assert st == {"pointer": pytest.approx(0.42), "flag": False}
    # Up for positive GSI, the HSI's gy = gy0 - GSI * range.
    assert nd.vdev_pointer_y(g, st["pointer"]) == pytest.approx(
        H * 0.5 - 0.42 * H * 0.18)
    assert g["x"] > W * 0.9                 # screen-fixed, right edge
    fix.db.set_value("GSI", -3.0)
    assert nd.vdev(_reader(fix))["pointer"] == -1.0     # pegged


def test_vdev_hidden_when_gsv_says_no_glidepath(fix):
    _define(fix, "GSI", 0.2)
    _define(fix, "GSV", 0.0)
    assert nd.vdev(_reader(fix)) is None


def test_vdev_without_gsv_key_follows_gsi_quality(fix):
    """An older gateway publishes no GSV: the scale shows on GSI's own
    quality, as the HSI does, and never raises the GS flag."""
    _define(fix, "GSI", 0.2)
    assert nd.vdev(_reader(fix)) == {"pointer": pytest.approx(0.2),
                                     "flag": False}
    fix.db.get_item("GSI").bad = True
    assert nd.vdev(_reader(fix)) == {"pointer": None, "flag": False}


@pytest.mark.parametrize("flag,pointer,raised", [
    ("old", None, False), ("bad", None, True), ("fail", None, True)])
def test_vdev_quality(fix, flag, pointer, raised):
    _define(fix, "GSI", 0.2, **{flag: True})
    _define(fix, "GSV", 1.0)
    assert nd.vdev(_reader(fix)) == {"pointer": pointer, "flag": raised}


def test_vdev_paints_the_pointer_where_the_model_says(fix, qtbot):
    """Paint a frame and find the magenta diamond on the scale's line."""
    _define(fix, "GSI", 0.5)
    _define(fix, "GSV", 1.0)
    m = _map(qtbot, nd_mode="expanded", layer_terrain=False,
             layer_roads=False, layer_rivers=False, layer_range_rings=False,
             layer_airports=False, layer_navaids=False)
    img = QImage(W, H, QImage.Format.Format_ARGB32)
    img.fill(0)
    m.render(img)
    g = nd.vdev_geometry(W, H)
    x0 = int(round(g["x"]))
    rows = [y for y in range(H)
            if (lambda c: c.red() > 200 and c.blue() > 200
                and c.green() < 80)(img.pixelColor(x0, y))]
    assert rows, "no magenta pointer on the scale"
    centre = (min(rows) + max(rows)) / 2.0
    assert centre == pytest.approx(nd.vdev_pointer_y(g, 0.5), abs=1.5)


# --- data blocks -----------------------------------------------------------

def test_top_left_speeds_and_wind(fix):
    _define(fix, "GS", 132.4)
    _define(fix, "TAS", 128.0)
    _define(fix, "WINDDIR", 0.2)
    _define(fix, "WINDSPD", 14.0)
    lines, arrow = nd.top_left(_reader(fix))
    assert _texts(lines) == [["GS", "132", "TAS", "128"], ["360°/14"]]
    assert lines[0][1][1] == nd.WHITE
    assert arrow == pytest.approx(0.2)


def test_top_left_wind_quality(fix):
    _define(fix, "WINDDIR", 300.0, old=True)
    _define(fix, "WINDSPD", 14.0)
    lines, arrow = nd.top_left(_reader(fix))
    assert lines[-1] == [("300°/14", nd.GREY)] and arrow is None
    fix.db.get_item("WINDSPD").fail = True
    lines, arrow = nd.top_left(_reader(fix))
    assert lines[-1] == [(nd.FAIL_TEXT, nd.RED)] and arrow is None


def test_top_left_empty_on_a_gateway_without_the_keys():
    assert nd.top_left(_absent) == ([], None)
    assert nd.top_right(_absent) == []


def _plan(fix, **extra):
    vals = dict(FPLSTATE=1, FPLPHASE="TERM", WPNAME="RZS", WPDIS=23.46,
                WPETE=640)
    vals.update(extra)
    for k, v in vals.items():
        _define(fix, k, v)


NOW = calendar.timegm((2026, 11, 8, 7, 10, 30, 0, 0, 0))


def test_top_right_active_waypoint(fix):
    _plan(fix)
    lines = nd.top_right(_reader(fix), now=NOW)
    # 07:10:30 + 640 s = 07:21:10 -> 0721.1z
    assert _texts(lines) == [["RZS"], ["0721.1z"], ["23.5", "NM"]]
    assert lines[0][0][1] == nd.MAGENTA
    assert lines[1][0][1] == nd.WHITE and lines[2][0][1] == nd.WHITE


def test_top_right_hidden_with_no_plan(fix):
    _plan(fix, FPLSTATE=0, WPNAME="", WPDIS=0.0, WPETE=0)
    assert nd.top_right(_reader(fix), now=NOW) == []


def test_top_right_vectors_blanks_distance_and_eta(fix):
    _plan(fix, FPLPHASE="VECTORS", WPDIS=0.0, WPETE=0)
    assert _texts(nd.top_right(_reader(fix), now=NOW)) == [["RZS"]]


def test_top_right_position_lost(fix):
    """Engine lost LAT/LONG: blank ident (no flag) + failed distance/time."""
    _plan(fix, WPNAME="")
    fix.db.get_item("WPDIS").fail = True
    fix.db.get_item("WPETE").fail = True
    lines = nd.top_right(_reader(fix), now=NOW)
    assert _texts(lines) == [[""], [nd.FAIL_TEXT], [nd.FAIL_TEXT]]
    assert lines[1][0][1] == nd.RED


def test_top_right_slow_and_integrity(fix):
    _plan(fix)
    fix.db.get_item("WPETE").bad = True       # GS < 30 kt
    fix.db.get_item("WPDIS").bad = True       # integrity gate not met
    lines = nd.top_right(_reader(fix), now=NOW)
    assert lines[1] == [(nd.BAD_TIME, nd.GREY)]
    assert lines[2] == [("23.5", nd.GREY), ("NM", nd.GREY)]


def test_top_right_stale_engine_greys_the_block(fix):
    _plan(fix)
    fix.db.get_item("FPLSTATE").old = True
    lines = nd.top_right(_reader(fix), now=NOW)
    assert all(c == nd.GREY for line in lines for _, c in line)


def test_bottom_left_lists_enabled_options(qtbot):
    assert _texts(nd.bottom_left({"airports", "navaids", "terrain"})) == \
        [["ARPT"], ["STA"]]
    assert all(c == nd.CYAN for line in nd.bottom_left({"fixes"})
               for _, c in line)


# --- frame clock and paint -------------------------------------------------

def test_frame_clock_repaints_on_nd_data_only_while_on(fix, qtbot):
    _define(fix, "GSI", 0.1)
    _define(fix, "GSV", 1.0)
    m = _map(qtbot, nd_mode="expanded")
    m.show()
    m._frame_tick()
    pose = m._frame_last_pose
    fix.db.set_value("GSI", 0.6)
    m._frame_tick()
    assert m._frame_last_pose != pose
    m.nd_mode = "off"
    m._frame_tick()
    pose = m._frame_last_pose
    fix.db.set_value("GSI", -0.6)
    m._frame_tick()
    assert m._frame_last_pose == pose


def test_paint_off_draws_no_nd(fix, qtbot, monkeypatch):
    calls = []
    monkeypatch.setattr(nd, "paint", lambda *a, **k: calls.append(a))
    m = _map(qtbot, layer_terrain=False, layer_roads=False,
             layer_rivers=False)
    img = QImage(W, H, QImage.Format.Format_ARGB32)
    m.render(img)
    assert calls == []
    m.nd_mode = "expanded"
    m.render(img)
    assert len(calls) == 1
