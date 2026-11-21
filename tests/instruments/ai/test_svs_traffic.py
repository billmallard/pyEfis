#  SPDX-License-Identifier: GPL-2.0-or-later
"""ADS-B traffic in the synthetic vision scene (SVSTFC1, CAP-409).

The bus side is the real pyavtools ``fix`` database with the ``TFC`` block
defined and written exactly as the moving-map tests do it (fields, then
``TFCkTGT`` last). Placement is pinned in closed form and against
``camera.view_projection`` -- the matrix the terrain is drawn with -- so a
target is checked to land where the real aircraft would be seen. The GL
draw itself needs a context and is covered by the bench captures; its
ordering and depth state are pinned here with a recording stub.
"""

import math

import numpy as np
import pytest

from pyefis.instruments.ai import camera, svs_gl, svs_traffic
from pyefis.instruments.ai.svs import SVSRenderer
from pyefis.instruments import traffic as tfc
from pyefis.screens import screenbuilder_factory
from tests.instruments.test_map_traffic import (
    OWN_LAT, OWN_LON, _define_block, _evict, _write)

NM_FT = 6076.12
W, H = 800, 480
PPD_V = H / 50.0                       # pitchDegreesShown 50
PPD_H = H / camera.TERRAIN_HFOV_PITCH_DEG
OWN_ALT = 5300.0                       # indicated (ALT), the camera height
PALT = 5000.0                          # pressure altitude: 300 ft apart
UVS = {"t" + ch: (0.0, 0.0, 0.05, 0.1) for ch in "0123456789+-"}


def _cam(heading=0.0, pitch=0.0, alt=OWN_ALT):
    return svs_traffic.Camera(OWN_LAT, OWN_LON, alt, heading, pitch,
                              PPD_V, PPD_H, H)


def _vp(heading=0.0, pitch=0.0, alt=OWN_ALT):
    """The terrain's view-projection in an ENU frame whose origin is the
    ownship's ground point (the GL path uses a patch corner; only
    differences matter)."""
    return camera.view_projection(0.0, 0.0, alt * camera.M_PER_FT, heading,
                                  pitch, 0.0, PPD_V, W, H,
                                  pixels_per_deg_h=PPD_H)


def _screen(vp, lat, lon, elev_ft):
    """Pixels from the viewport centre (x right, y up) of a world point."""
    lat_cos = math.cos(math.radians(OWN_LAT))
    e = (lon - OWN_LON) * camera.M_PER_DEG_LAT * lat_cos
    n = (lat - OWN_LAT) * camera.M_PER_DEG_LAT
    x, y, w = camera.project(vp, e, n, elev_ft * camera.M_PER_FT)
    assert w > 0
    return x / w * W / 2.0, y / w * H / 2.0


def _north(nm):
    return OWN_LAT + nm * NM_FT / 364491.0


def _east(nm):
    return OWN_LON + nm * NM_FT / (364491.0 * math.cos(math.radians(OWN_LAT)))


def _target(**kw):
    base = dict(ident=0x1A2B3C, lat=_north(3.0), lon=OWN_LON, alt_ft=5500.0,
                vs_fpm=0.0, trk_deg=0.0, ttyp=1, nic=10, nacp=9,
                alert=False, callsign="", stale=False, t_write=100.0)
    base.update(kw)
    return tfc.Target(**base)


def _build(targets, now=100.0, palt=PALT, magvar=None, **cam):
    return svs_traffic.build(targets, _cam(**cam), palt, magvar, now, UVS)


def _drawn(geo):
    return {d[0]: d for d in geo.drawn}


@pytest.fixture
def bus(fix):
    _define_block(fix, n=3, palt=PALT)
    return fix


@pytest.fixture
def renderer(bus):
    r = SVSRenderer({"enabled": True})
    r.attach_traffic(bus.db)
    assert r.traffic is not None
    return r


# ---------------------------------------------------------------------------
# DoD 1a: a target ahead and above projects to the expected screen region
# ---------------------------------------------------------------------------
def test_target_ahead_and_above_lands_where_the_aircraft_is_seen():
    geo = _build([_target()])
    (ident, lat, lon, elev, rgba, tag), = geo.drawn
    assert tag == "+05"
    assert rgba == svs_traffic.NORMAL_RGBA
    # Placed at ownship ALT + (TFCkALT - PALT): 500 ft above the eye,
    # not at the pressure altitude 5500 (200 ft above the eye).
    assert elev == pytest.approx(OWN_ALT + 500.0, abs=0.5)
    x, y = _screen(_vp(), lat, lon, elev)
    # Closed form: dead ahead, atan(500 ft / 3 NM) above the boresight.
    expect_y = PPD_V * math.degrees(math.atan2(500.0, 3.0 * NM_FT))
    assert x == pytest.approx(0.0, abs=0.5)
    assert y == pytest.approx(expect_y, abs=0.5)
    assert 10.0 < y < 40.0      # above the horizon, in the upper half


def test_target_right_of_the_nose_lands_right_by_the_terrain_scale():
    geo = _build([_target(lat=_north(3.0), lon=_east(1.0))])
    (_i, lat, lon, elev, _c, _t), = geo.drawn
    x, y = _screen(_vp(), lat, lon, elev)
    bearing = math.degrees(math.atan2(1.0, 3.0))
    assert x == pytest.approx(
        camera.terrain_horizontal_px(bearing, H), rel=0.01)


def test_billboard_keeps_its_pixel_size_at_any_range():
    """The symbol is laid out in pixels and mapped into the world at the
    target's depth: projected, its half-height is the minimum size at
    3 NM and at 9 NM alike, and it grows inside GROW_NM."""
    s0 = svs_traffic.symbol_px(H)
    for nm, scale in ((3.0, 1.0), (9.0, 1.0), (1.0, 2.0)):
        t = _target(lat=_north(nm), alt_ft=PALT, trk_deg=0.0)
        geo = _build([t])
        fill = dict(geo.tris)[svs_traffic.NORMAL_RGBA]
        vp = _vp()
        ys = [_screen(vp, *row)[1] for row in fill]
        cy = _screen(vp, *geo.drawn[0][1:4])[1]
        # nose-up arrowhead: tip at +s, wings at -0.75 s
        assert max(ys) - cy == pytest.approx(s0 * scale, rel=0.02)
        assert cy - min(ys) == pytest.approx(0.75 * s0 * scale, rel=0.02)


def test_arrowhead_points_along_track_relative_to_heading():
    """Heading 000, target tracking 090: the tip points right."""
    geo = _build([_target(trk_deg=90.0)])
    fill = dict(geo.tris)[svs_traffic.NORMAL_RGBA]
    vp = _vp()
    cx = _screen(vp, *geo.drawn[0][1:4])[0]
    xs = [_screen(vp, *row)[0] for row in fill]
    assert max(xs) - cx == pytest.approx(svs_traffic.symbol_px(H), rel=0.02)


def test_target_on_our_track_points_up_whatever_our_heading():
    """Heading 090, target ahead (east) also tracking 090: tip up."""
    t = _target(lat=OWN_LAT, lon=_east(3.0), trk_deg=90.0)
    geo = _build([t], heading=90.0)
    fill = dict(geo.tris)[svs_traffic.NORMAL_RGBA]
    vp = _vp(heading=90.0)
    cx, cy = _screen(vp, *geo.drawn[0][1:4])
    pts = [_screen(vp, *row) for row in fill]
    assert cx == pytest.approx(0.0, abs=0.5)
    assert max(y for _x, y in pts) - cy == pytest.approx(
        svs_traffic.symbol_px(H), rel=0.02)
    assert max(abs(x - cx) for x, _y in pts) == pytest.approx(
        0.75 * svs_traffic.symbol_px(H), rel=0.02)


def test_target_behind_is_not_drawn():
    assert not _build([_target(lat=_north(-3.0))])


def test_target_beyond_range_is_left_to_the_map():
    assert not _build([_target(lat=_north(11.0))])
    assert _build([_target(lat=_north(9.0))])


# ---------------------------------------------------------------------------
# DoD 1b: a stale target is not drawn as live
# ---------------------------------------------------------------------------
def test_stale_target_draws_grey_and_dashed_then_is_hidden(bus, renderer):
    _write(bus, 1, 0x111111, lat=_north(3.0), alt=5500.0)
    bus.db.get_item("TFC1TGT").old = True        # no report for 3 s
    (t,) = renderer.traffic.targets()
    assert t.stale
    geo = svs_traffic.build([t], _cam(), PALT, None, t.t_write + 1.0, UVS)
    assert _drawn(geo)[0x111111][4] == svs_traffic.STALE_RGBA
    colors = [c for c, _ in geo.tris]
    assert svs_traffic.NORMAL_RGBA not in colors
    assert svs_traffic.ALERT_RGBA not in colors
    # writer dead, never evicted: hidden after the cap
    late = t.t_write + tfc.STALE_HIDE_S + 0.1
    assert not svs_traffic.build([t], _cam(), PALT, None, late, UVS)


def test_failed_or_evicted_or_positionless_target_is_not_drawn(bus, renderer):
    _write(bus, 1, 0x111111, lat=_north(3.0))
    _write(bus, 2, 0x222222, lat=_north(4.0))
    _write(bus, 3, 0x333333, lat=_north(5.0), bad=("LAT",))
    assert {t.ident for t in renderer.traffic.targets()} == {
        0x111111, 0x222222}
    bus.db.get_item("TFC1TGT").fail = True
    _evict(bus, 2)
    assert renderer.traffic.targets() == []


# ---------------------------------------------------------------------------
# DoD 1c: a target behind a ridge is still drawn
# ---------------------------------------------------------------------------
def test_target_behind_a_ridge_is_drawn_full_strength(bus, renderer,
                                                     monkeypatch):
    """Terrain everywhere at 20,000 ft -- every line of sight is blocked.
    Traffic has no line-of-sight test (airport flags dim; traffic must
    not), so the target is drawn, in its own colour, not dimmed."""
    monkeypatch.setattr(renderer, "_sample_elevations",
                        lambda lats, lons: np.full(np.shape(lats), 20000.0),
                        raising=False)
    _write(bus, 1, 0x111111, lat=_north(3.0), alt=5500.0)
    geo = renderer.traffic.geometry(_cam(), UVS, now=None)
    assert _drawn(geo)[0x111111][4] == svs_traffic.NORMAL_RGBA


class _GL:
    """Records the GL calls _render_overlays makes."""
    GL_TRIANGLES, GL_TEXTURE0, GL_TEXTURE_2D, GL_DEPTH_TEST = 4, 0, 1, 2929

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        if name.startswith("GL_"):
            return 0
        return lambda *a: self.calls.append((name, a))


class _Prog:
    def bind(self):
        pass

    def release(self):
        pass

    def setUniformValue(self, *a):
        pass


def test_traffic_is_the_last_overlay_drawn_with_no_depth_test(
        bus, renderer, monkeypatch):
    """Painter's order with the depth test off is what keeps terrain from
    hiding a target: traffic must draw after every other overlay, and the
    overlay pass must never turn depth testing on."""
    _write(bus, 1, 0x111111, lat=_north(3.0), alt=5500.0)
    rec = _GL()
    monkeypatch.setattr(svs_gl, "gl", rec)
    g = svs_gl.SVSGLRenderer(renderer)
    g._overlay_program = _Prog()
    g._overlay_u = {k: 0 for k in ("u_vp", "u_ac_e", "u_ac_n",
                                   "u_earth_curv", "u_haze_inv")}
    g._frame_vp = g._frame_ac_e = g._frame_ac_n = 0.0
    g._frame_curv = g._frame_haze_inv = 0.0
    g._text_atlas_uvs = UVS
    monkeypatch.setattr(g, "_ensure_overlay_program", lambda: None)
    monkeypatch.setattr(g, "_ensure_text_program", lambda: None)
    order = []
    monkeypatch.setattr(
        g, "_draw_overlay_primitive",
        lambda v, c, m, fog_strength=0.0: order.append(("tris", c,
                                                        fog_strength)))
    monkeypatch.setattr(g, "_render_text_list",
                        lambda items: order.append(("text", len(items))))
    monkeypatch.setattr(
        g, "_draw_overlay_cached",
        lambda slot, v, c, m, fog_strength=0.0: order.append(("flag", slot)))
    # Airport flags, the overlay drawn last before traffic existed.
    renderer.airport_db = type("_DB", (), {"ready": True})()
    renderer.papi_enabled = False
    for name in ("_collect_runway_polygons", "_collect_runway_markings",
                 "_collect_runway_designator_quads"):
        monkeypatch.setattr(renderer, name, lambda *a, **k: None)
    monkeypatch.setattr(renderer, "_collect_airport_flags",
                        lambda *a, **k: {"flags": np.ones((3, 3))})
    g._render_overlays(W, H, OWN_LAT, OWN_LON, OWN_ALT, 0.0, 0.0, 0.0,
                       PPD_V, range_nm=10.0)
    assert ("glEnable", (rec.GL_DEPTH_TEST,)) not in rec.calls
    kinds = [o[0] for o in order]
    assert kinds == ["flag", "tris", "tris", "text"]
    assert order[1][1] == svs_traffic.OUTLINE_RGBA       # halo first
    assert all(o[2] == 0.0 for o in order if o[0] == "tris")   # no haze


# ---------------------------------------------------------------------------
# DoD 1d: ownship (filtered by identity) is never drawn
# ---------------------------------------------------------------------------
def test_ownship_never_drawn_and_no_geometry_filter(bus, renderer):
    """The writer removes ownship by identity (spec 4.8, P3e), so ownship
    never reaches the bus; the SVS draws exactly the identities on the bus
    and filters nothing by geometry. A target at ownship's altitude 0.2 NM
    ahead -- what a geometry filter would remove -- is drawn, and an
    identity the writer evicts (an ownship report it dropped late) is
    gone at once."""
    OWNSHIP = 0xA4B7C2
    _write(bus, 1, 0x111111, lat=_north(3.0))
    _write(bus, 2, 0x222222, lat=_north(0.2), alt=PALT)   # co-located
    _write(bus, 3, OWNSHIP, lat=OWN_LAT + 1e-6, alt=PALT)
    _evict(bus, 3)
    geo = renderer.traffic.geometry(_cam(), UVS)
    assert set(_drawn(geo)) == {0x111111, 0x222222}
    assert OWNSHIP not in _drawn(geo)


def test_alerted_target_and_its_tag_draw_over_every_other_target():
    """The map's draw order, per class: stale, normal, then alerted, each
    symbol then tag -- so no other target's tag covers an alert."""
    geo = _build([_target(ident=1, alert=True),
                  _target(ident=2, lat=_north(3.1)),
                  _target(ident=3, lat=_north(3.2), stale=True)], now=0.1)
    inks = [tris[1][0] for tris, _text in geo.layers]
    assert inks == [svs_traffic.STALE_RGBA, svs_traffic.NORMAL_RGBA,
                    svs_traffic.ALERT_RGBA]
    for tris, text in geo.layers:
        assert tris[0][0] == text[0][0] == svs_traffic.OUTLINE_RGBA
        assert text[1][0] == tris[1][0]


# ---------------------------------------------------------------------------
# altitude reference and symbol states
# ---------------------------------------------------------------------------
def test_no_palt_dashes_the_tag_and_places_the_target_at_ownship_level():
    geo = _build([_target()], palt=None)
    (_i, lat, lon, elev, _c, tag), = geo.drawn
    assert tag == "--"
    assert elev == pytest.approx(OWN_ALT, abs=0.5)


def test_altitude_invalid_target_is_dashed_at_ownship_level():
    geo = _build([_target(alt_ft=None)])
    assert geo.drawn[0][5] == "--"
    assert geo.drawn[0][3] == pytest.approx(OWN_ALT, abs=0.5)


def test_traffic_below_tags_below_the_symbol():
    above = _build([_target(alt_ft=PALT + 800.0)])
    below = _build([_target(alt_ft=PALT - 800.0)])
    vp = _vp()

    def tag_offset(geo):
        cy = _screen(vp, *geo.drawn[0][1:4])[1]
        ink = geo.text[-1][1]
        return np.mean([_screen(vp, *row[:3])[1] for row in ink]) - cy

    assert tag_offset(above) > 0 > tag_offset(below)


def test_alerted_target_flashes_between_filled_and_open():
    t = _target(alert=True)
    on = _build([t], now=0.1)          # flash phase on: filled (2 tris)
    off = _build([t], now=tfc.FLASH_S + 0.1)
    n_on = len(dict(on.tris)[svs_traffic.ALERT_RGBA])
    n_off = len(dict(off.tris)[svs_traffic.ALERT_RGBA])
    assert n_on == 6 and n_off > 6     # outline = a quad per edge


def test_degraded_target_is_an_open_outline():
    geo = _build([_target(nic=3)])
    assert len(dict(geo.tris)[svs_traffic.NORMAL_RGBA]) == 4 * 6


def test_trend_arrow_drawn_past_500_fpm():
    level = _build([_target(vs_fpm=0.0)])
    climb = _build([_target(vs_fpm=1000.0)])
    n = lambda g: len(dict(g.tris)[svs_traffic.NORMAL_RGBA])
    assert n(climb) == n(level) + 3 * 6


def test_trend_arrow_stays_upright_whatever_the_track():
    """Only the symbol turns with track; the climb arrow points up."""
    s = svs_traffic.symbol_px(H)
    vp = _vp()
    for trk in (0.0, 90.0, 225.0):
        geo = _build([_target(vs_fpm=1000.0, trk_deg=trk)])
        ink = dict(geo.tris)[svs_traffic.NORMAL_RGBA]
        cx, cy = _screen(vp, *geo.drawn[0][1:4])
        arrow = [_screen(vp, *row) for row in ink[6:]]   # after the fill
        xs = [x - cx for x, _y in arrow]
        ys = [y - cy for _x, y in arrow]
        assert min(xs) > 0.7 * s and max(xs) < 1.8 * s, trk
        # tip 0.8 s up, plus the 2 px stroke's square cap
        assert 0.8 * s < max(ys) < 0.8 * s + 2.0, trk


def test_magnetic_heading_without_magvar_is_non_directional():
    t = _target(ttyp=2, trk_deg=90.0)
    vp = _vp()
    geo = _build([t], magvar=None)
    fill = dict(geo.tris)[svs_traffic.NORMAL_RGBA]
    cx, cy = _screen(vp, *geo.drawn[0][1:4])
    xs = [_screen(vp, *row)[0] - cx for row in fill]
    # diamond: +/- 0.8 s across
    assert max(xs) == pytest.approx(0.8 * svs_traffic.symbol_px(H), rel=0.02)


# ---------------------------------------------------------------------------
# wiring
# ---------------------------------------------------------------------------
def test_bus_write_wakes_the_frame_clock(bus, renderer):
    renderer.consume_async_dirty()
    assert not renderer.consume_async_dirty()
    _write(bus, 1, 0x111111, lat=_north(3.0))
    assert renderer.consume_async_dirty()
    assert not renderer.consume_async_dirty()


def test_alert_flash_wakes_the_frame_clock(bus, renderer):
    _write(bus, 1, 0x111111, lat=_north(3.0), alrt=1)
    renderer.consume_async_dirty()
    tr = renderer.traffic
    tr.needs_repaint(now=0.1)          # sync at a known flash phase
    assert not tr.needs_repaint(now=0.2)
    assert tr.needs_repaint(now=tfc.FLASH_S + 0.1)
    assert not tr.needs_repaint(now=tfc.FLASH_S + 0.2)


def test_no_tfc_block_leaves_traffic_inert(fix):
    r = SVSRenderer({"enabled": True})
    r.attach_traffic(fix.db)
    assert r.traffic is None
    assert not r.consume_async_dirty()


def test_svs_traffic_option_reaches_the_renderer(bus):
    cfg = screenbuilder_factory._build_svs_cfg(
        {"svs_enabled": True, "svs_traffic": False,
         "svs_traffic_range_nm": 5})
    r = SVSRenderer(cfg)
    assert r.traffic_range_nm == 5.0
    r.attach_traffic(bus.db)
    assert r.traffic is None
    r = SVSRenderer(screenbuilder_factory._build_svs_cfg(
        {"svs_enabled": True, "svs_traffic_range_nm": 5}))
    r.attach_traffic(bus.db)
    assert r.traffic.range_nm == 5.0


def test_atlas_carries_the_tag_glyphs(qapp):
    atlas, uvs = svs_gl.build_text_atlas()
    assert "OBST" in uvs and "OBST_HIGH" in uvs
    size = atlas.shape[0]
    boxes = {ch: uvs["t" + ch] for ch in "0123456789+-"}
    # one baseline and cap height for every tag glyph, so a sign sits
    # beside the digits; the runway "1" stays the FAA stroke
    assert len({(round(b[3] - b[1], 6)) for b in boxes.values()}) == 1
    assert uvs["t1"] != uvs["1"]
    for ch, (u0, v0, u1, v1) in boxes.items():
        cell = atlas[int(v0 * size):int(round(v1 * size)),
                     int(u0 * size):int(round(u1 * size))]
        assert cell.max() > 200, ch          # the glyph is in its box
    # the minus is a bar at mid-height, not a full-height block
    u0, v0, u1, v1 = boxes["-"]
    cell = atlas[int(v0 * size):int(round(v1 * size)),
                 int(u0 * size):int(round(u1 * size))]
    rows = np.nonzero(cell.max(axis=1) > 128)[0]
    assert 0.3 < rows.mean() / cell.shape[0] < 0.7
    assert len(rows) < 0.3 * cell.shape[0]
