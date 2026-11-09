"""pyEfis #304 / #318: the terrain must roll about the AI's raised horizon
point, pinned through the whole call chain (AER-5123).

#318 rolls the terrain about ``roll_pivot_px`` -- the AI widget's
``_horizon_offset_px()`` -- so that at a ``horizon_position`` other than 50
the terrain horizon and the pitch ladder turn about the same point.
``roll_pivot_px`` defaults to 0.0 at every hop (``make_svs_item`` ->
``SVSRenderer.draw`` -> ``SVSGLRenderer.draw`` -> ``_update_camera`` ->
``view_projection``), so dropping it at any one of them silently puts back
the 90/180-degree-bank failure. test_camera.py passes the pivot to
``view_projection`` by hand and cannot see that.

This test drives the real chain from the graphics item the AI widget paints
down to the camera matrix. Only the GL calls are stubbed (no GL context in
CI): the matrix it reads is the one ``_update_camera`` built for the frame.

The horizon tested is the camera's zero-pitch line (far points at eye
height); earth curvature is applied in the shader, not in the matrix. The
camera is depressed by ``_horizon_offset_deg()`` and projects that through a
tangent, while the ladder offset is linear, so at roll 0 the terrain horizon
sits a pixel or so from the pivot. Rolling about the pivot preserves that
distance; rolling about any other point moves it by ~offset * (1 - cos bank),
which is 100+ px at the banks below.
"""
import math
from unittest import mock

import numpy as np
import pytest
from PyQt6.QtWidgets import QApplication

from pyefis.instruments import ai
from pyefis.instruments.ai import svs_gl
from pyefis.instruments.ai.camera import project
from pyefis.instruments.ai.svs import SVSRenderer, make_svs_item
from pyefis.instruments.ai.svs_gl import SVSGLRenderer

_LAT, _LON, _ALT = 34.4275, -119.8546, 3000.0
_HEAD = 87.0


@pytest.fixture
def app(qtbot):
    test_app = QApplication.instance()
    if test_app is None:
        test_app = QApplication([])
    return test_app


def _reset_items(fix):
    for key in ("PITCH", "ROLL", "ALAT", "TAS", "LAT", "LONG"):
        item = fix.db.get_item(key)
        item.old = item.bad = item.fail = False


def _gl_renderer(parent):
    """A real SVSGLRenderer with the GL work stubbed out, so draw() and
    _update_camera() run as written."""
    r = object.__new__(SVSGLRenderer)
    r._parent = parent
    r._patch_origin = (_LAT - 1.0, _LON - 1.0)
    r._logged_samples = True
    r._save_gl_state = lambda: None
    r._ensure_program = lambda: None
    r._ensure_mesh = lambda: None
    r._ensure_heightmap = lambda lat, lon: None
    r._render_frame = lambda *a, **k: None
    return r


def _frame_vp(fix, qtbot, monkeypatch, tmp_path, horizon_position, bank,
              width=1024, height=768):
    """Paint one frame through the AI's SVS item; return (vp, widget)."""
    _reset_items(fix)
    widget = ai.AI()
    qtbot.addWidget(widget)
    widget.resize(width, height)
    widget.show()
    qtbot.waitExposed(widget)
    widget.horizon_position = horizon_position

    # An empty tile root: no terrain data is needed to build the camera.
    svs = SVSRenderer({"enabled": True, "tile_path": str(tmp_path)})
    gl_r = _gl_renderer(svs)
    svs._gl_renderer = gl_r
    monkeypatch.setattr(SVSRenderer, "ready", property(lambda s: True))
    monkeypatch.setattr(svs_gl.QOpenGLContext, "currentContext",
                        staticmethod(lambda: object()))
    monkeypatch.setattr(svs_gl.gl, "glViewport", lambda *a: None)

    widget._svs_lat, widget._svs_lon, widget._svs_alt = _LAT, _LON, _ALT
    widget._fpm_head = _HEAD
    widget._pitchAngle = 0.0
    widget._rollAngle = bank

    make_svs_item(svs, widget).paint(mock.Mock(), None)
    assert svs.drew_terrain, "the frame never reached the GL renderer"
    m = gl_r._frame_vp
    vp = np.array(m.data(), dtype=float).reshape(4, 4).T  # column-major
    return vp, gl_r, widget


def _horizon_screen_points(vp, gl_r, w, h):
    """Two far points at eye height, +/-10 deg either side of the nose,
    in widget pixels (x right, y down)."""
    pts = []
    for d in (-10.0, 10.0):
        brg = math.radians(_HEAD + d)
        dist = 50_000.0
        e = gl_r._frame_ac_e + dist * math.sin(brg)
        n = gl_r._frame_ac_n + dist * math.cos(brg)
        u = _ALT * svs_gl.M_PER_FT
        x, y, wc = project(vp, e, n, u)
        assert wc > 0
        pts.append((w / 2.0 + x / wc * w / 2.0, h / 2.0 - y / wc * h / 2.0))
    return pts


def _distance_to_line(p, a, b):
    (px, py), (ax, ay), (bx, by) = p, a, b
    return (abs((bx - ax) * (ay - py) - (ax - px) * (by - ay))
            / math.hypot(bx - ax, by - ay))


def _pivot_to_horizon_px(fix, qtbot, monkeypatch, tmp_path,
                        horizon_position, bank):
    vp, gl_r, widget = _frame_vp(fix, qtbot, monkeypatch, tmp_path,
                                 horizon_position, bank)
    w, h = widget.viewport().width(), widget.viewport().height()
    # The point the AI rolls its ladder about (ai_widget.redraw / paint).
    pivot = (w / 2.0, h / 2.0 - widget._horizon_offset_px())
    a, b = _horizon_screen_points(vp, gl_r, w, h)
    # Screen y runs down, so a right bank turns the line clockwise.
    slope = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 180.0
    return _distance_to_line(pivot, a, b), slope, widget


@pytest.mark.parametrize("horizon_position", [25.0, 68.0])
@pytest.mark.parametrize("bank", [45.0, 90.0, 180.0])
def test_terrain_horizon_passes_through_the_raised_pivot(
        fix, qtbot, monkeypatch, tmp_path, horizon_position, bank):
    level, _, widget = _pivot_to_horizon_px(
        fix, qtbot, monkeypatch, tmp_path, horizon_position, 0.0)
    assert abs(widget._horizon_offset_px()) > 100.0  # the case #318 fixed
    # Wings level: the terrain horizon is on the raised pivot, give or take
    # the tangent-vs-linear residual (3.1 px at 25, 1.0 px at 68).
    assert level < 4.0

    rolled, slope, _ = _pivot_to_horizon_px(
        fix, qtbot, monkeypatch, tmp_path, horizon_position, bank)
    assert slope == pytest.approx((-bank) % 180.0, abs=0.5)
    # Rolled about the pivot, the horizon keeps its distance from it.
    # About any other point it moves by ~offset * (1 - cos bank): 40+ px.
    assert rolled == pytest.approx(level, abs=0.5)
