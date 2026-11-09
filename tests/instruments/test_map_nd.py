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
    # Landscape: the arc reaches up to just under the TRK box at the top.
    assert g["apex"] == pytest.approx(4.0 + g["box_h"] + g["fs"] * 0.5)
    assert g["half"] == nd.ARC_HALF_DEG
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


@pytest.mark.parametrize("w,h", [(650, 1000), (600, 600), (480, 800)])
def test_tall_panel_keeps_the_sector_and_clears_the_scale(w, h):
    """A radius sized from the height would leave a sliver of arc running
    through the top corner blocks on a portrait panel: the radius shrinks
    instead, the sector stays >= ARC_MIN_HALF_DEG, and the arc's ends stay
    clear of the deviation scale and inside the panel."""
    g = nd.expanded_geometry(w, h)
    v = nd.vdev_geometry(w, h)
    assert nd.ARC_MIN_HALF_DEG - 1e-9 <= g["half"] <= nd.ARC_HALF_DEG
    end_x = w / 2.0 + g["r"] * math.sin(math.radians(g["half"]))
    assert end_x <= min(0.96 * w, v["x"] - g["fs"]) + 1e-6
    assert g["apex"] >= 4.0 + g["box_h"] + g["fs"] * 0.5 - 1e-6


def _arc_top_at(g, dx):
    """Screen y of the compass arc at |x - cx| = dx, or None past its ends."""
    if dx > g["r"] * math.sin(math.radians(g["half"])) + 1e-9:
        return None
    return g["own_y"] - math.sqrt(g["r"] ** 2 - dx ** 2)


@pytest.mark.parametrize("family", [None, "DejaVu Sans"])
@pytest.mark.parametrize("w,h", [(800, 480), (1024, 600), (650, 1000),
                                 (600, 600), (480, 800)])
def test_arc_stays_out_of_the_top_corner_blocks(w, h, family, qtbot):
    """G11c: wherever the arc runs under a top corner block's worst-case
    extent (its widest possible line, backing panel and clearance), it is
    below the block's bottom. G11a's first portrait cut ran the arc through
    both blocks; a height-sized radius with no block bound does it again."""
    g = nd.expanded_geometry(w, h, family)
    fs = g["fs"]
    tl_w, tr_w = nd.block_widths(family, fs)
    bottom = nd.corner_block_bottom(w, h)
    for bw in (tl_w, tr_w):
        inner = 6.0 + bw + nd.panel_pad(fs)
        y = _arc_top_at(g, w / 2.0 - inner)
        assert y is None or y >= bottom - 1e-6, (w, h, bw, y, bottom)


@pytest.mark.parametrize("w,h", [(650, 1000), (480, 800)])
def test_portrait_arc_uses_the_height(w, h):
    """G11c: on the bench's 650x1000 panel G11a ended the arc 40% down, with
    map beyond the selected range above it. The radius now grows with the
    height until the blocks bind: the arc's top is in the top sixth."""
    g = nd.expanded_geometry(w, h)
    assert g["apex"] <= h / 6.0
    # It grew past G11a's 40-degree radius, and the sector narrowed to pay.
    assert g["r"] > nd.arc_reach(w, h) / math.sin(math.radians(40.0))
    assert nd.ARC_MIN_HALF_DEG <= g["half"] < 40.0


def test_landscape_geometry_is_g11a_unchanged():
    """The 7-inch landscape panel keeps G11a's arc exactly: the TRK box at
    the top edge binds first, and the sector is the full +/-60."""
    g = nd.expanded_geometry(W, H, "DejaVu Sans")
    assert g["r"] == pytest.approx(H * 0.82 - (4.0 + g["box_h"]
                                               + g["fs"] * 0.5))
    assert g["half"] == nd.ARC_HALF_DEG


def _ring_layer(m):
    return next(lay for lay in m._layers if lay.id == "range_rings")


@pytest.mark.parametrize("w,h", [(W, H), (650, 1000)])
def test_trk_box_keeps_the_range_ring_label_out(fix, qtbot, w, h):
    """G11c: the full-range ring's top label lands on the lubber, just under
    the TRK box. In EXPANDED it is kept out; the half-range one is drawn."""
    m = _map(qtbot, nd_mode="expanded")
    m.resize(w, h)
    m._build_layers()
    m._track = 72.0
    x = m._transform()
    rings = _ring_layer(m)
    assert rings.label_angle == 0.0          # the default
    radii = dict(zip(rings.fractions, rings.ring_radii_px(x)))
    assert rings.label_kept_out(x, rings.label_rect(x, radii[1.0]))
    assert not rings.label_kept_out(x, rings.label_rect(x, radii[0.5]))
    # The keep-out is the TRK box the paint draws, down through the lubber.
    g = nd.expanded_geometry(float(w), float(h), x.font_family)
    box, _r, _s = nd.trk_box(x.font_family, g["fs"], g["box_h"], 72.0,
                             x.cx, x.cy - g["r"])
    (k,) = x.label_keep_out
    assert (k.left(), k.top(), k.width()) == pytest.approx(
        (box.left(), box.top(), box.width()))
    assert k.bottom() > x.cy - g["r"]
    # And paint honours it: a recording painter sees "5", never "10".
    from unittest.mock import MagicMock
    p = MagicMock()
    rings.paint(p, x)
    drawn = [c.args[-1] for c in p.drawText.call_args_list]
    assert drawn == ["5"]
    # Moved off the top by the option, it is drawn again.
    rings.label_angle = 300.0
    assert not rings.label_kept_out(x, rings.label_rect(x, radii[1.0]))
    p = MagicMock()
    rings.paint(p, x)
    assert [c.args[-1] for c in p.drawText.call_args_list] == ["5", "10"]


def test_no_keep_out_with_the_nd_off(fix, qtbot):
    m = _map(qtbot)
    m._build_layers()
    assert m._transform().label_keep_out == ()


def _render_nd(fix, qtbot, monkeypatch, panel=None):
    for key, value in (("GS", 112.0), ("TAS", 118.0), ("WINDDIR", 300.0),
                       ("WINDSPD", 14.0), ("FPLSTATE", 1),
                       ("FPLPHASE", "TERM"), ("WPNAME", "KSBA"),
                       ("WPDIS", 8.4), ("WPETE", 270)):
        _define(fix, key, value)
    if panel is not None:
        monkeypatch.setattr(nd, "PANEL", panel)
        monkeypatch.setattr(nd, "TRK_FILL", panel)
    m = _map(qtbot, nd_mode="expanded", layer_terrain=False,
             layer_roads=False, layer_rivers=False, layer_range_rings=False)
    m._build_layers()
    m._lat, m._lon, m._track = 34.38, -120.0, 72.0
    img = QImage(W, H, QImage.Format.Format_ARGB32)
    img.fill(0)
    m.render(img)
    return m, img


def test_blocks_and_trk_box_sit_on_backing(fix, qtbot, monkeypatch):
    """G11c: each corner block has a dark panel under it and the TRK box is
    filled, so a map label under them cannot overprint them. Sampled in the
    panels' padding (no text there) against the same frame with the fills
    made transparent, which shows the bare map background."""
    from PyQt6.QtGui import QColor
    m, img = _render_nd(fix, qtbot, monkeypatch)
    _m, bare = _render_nd(fix, qtbot, monkeypatch, panel=QColor(0, 0, 0, 0))
    g = nd.expanded_geometry(W, H, m.font_family)
    fs = g["fs"]
    lh = fs * 1.3
    top = 4.0 + nd.status_chip_height(W) + 2.0
    x = m._transform()
    box, _r, _s = nd.trk_box(m.font_family, fs, g["box_h"], 72.0, x.cx,
                             x.cy - g["r"])
    probes = {
        "top-left": (2, top + lh * 0.5),
        # right of the wind arrow, below the wind line: only the lines'
        # rect covers it (the chip's rect ends above ``top``)
        "top-left lines": (6.0 + fs * 2.0 + 2, top + lh * 2 + fs * 1.5),
        "top-right": (W - 3, top + lh * 0.5),
        "bottom-left": (2, H - 6.0 - lh * 1.5),
        "TRK box": (box.left() + 4, box.top() + 4),
    }
    for name, (px, py) in probes.items():
        c = img.pixelColor(int(px), int(py))
        b = bare.pixelColor(int(px), int(py))
        assert b.lightness() > 0, name           # the probe sees the map
        assert c.lightness() < b.lightness(), name
    tb = img.pixelColor(int(box.left() + 4), int(box.top() + 4))
    assert (tb.red(), tb.green(), tb.blue()) == (0, 0, 0)


def _window_entry(x, cover_h):
    from pyefis.instruments.map.layers.terrain import TerrainLayer
    n, mpp, _c, _la, _lo = TerrainLayer()._window(
        (None, x.lat0, x.lon0, x.range_nm, x.w, cover_h, x.range_px))
    return (QImage(n, n, QImage.Format.Format_ARGB32), None,
            (x.lat0, x.lon0, mpp))


@pytest.mark.parametrize("track", [0.0, 45.0, 72.0, 135.0])
def test_terrain_window_covers_the_panel_with_ownship_low(fix, qtbot, track):
    """With ownship at 82% down, the far top corners are farther from the
    window centre than half the panel diagonal: the terrain/roads window is
    sized from cover_h so it still reaches them. Sized from h (as before),
    it leaves a corner bare on the bench's portrait panel."""
    from pyefis.instruments.map.layers import window_covers_viewport
    m = _map(qtbot, nd_mode="expanded")
    m.resize(650, 1000)
    m._track = track
    x = m._transform()
    assert x.cover_h == pytest.approx(2 * 0.82 * 1000)
    assert window_covers_viewport(x, _window_entry(x, x.cover_h))
    if track == 45.0:
        assert not window_covers_viewport(x, _window_entry(x, x.h))


def test_cover_h_is_h_at_the_default_anchor(fix, qtbot):
    x = _map(qtbot)._transform()
    assert x.cover_h == pytest.approx(H)


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
    # Build the layers up front: a first paint otherwise schedules the
    # live-binding init on a timer that can outlive the widget.
    m._build_layers()
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
    # _frame_tick no-ops while hidden; fake visibility and stub update()
    # rather than show() it, so no real paint runs (test_map_frame_clock).
    m.isVisible = lambda: True
    m.update = lambda: None
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
    # Count calls, never keep the args: holding paintEvent's QPainter past
    # render() lets it be destroyed after its device, at monkeypatch undo --
    # a segfault in teardown (CI run 42459264291).
    calls = []
    monkeypatch.setattr(nd, "paint", lambda *a, **k: calls.append(None))
    m = _map(qtbot, layer_terrain=False, layer_roads=False,
             layer_rivers=False)
    m._build_layers()
    img = QImage(W, H, QImage.Format.Format_ARGB32)
    m.render(img)
    assert calls == []
    m.nd_mode = "expanded"
    m.render(img)
    assert len(calls) == 1
