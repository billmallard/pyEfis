"""AER-5122: the SVS terrain horizon must sit on the attitude zero-pitch line.

AC 20-167A 4.3.2.5.3: terrain at the aircraft's altitude lies on the
zero-pitch reference line. horizon_position raises that line by a fixed
number of pixels. svs.py used to raise the terrain to match by depressing
the camera by the same offset expressed as an angle. That angle then went
through the camera's tangent along with the pitch, while the ladder places
zero pitch linearly. At pitchDegreesShown 50, horizon_position 75 and pitch
-10 the terrain horizon sat 1.23 deg (19 px at 768) above the line.

The test reads both sides from what the code builds: the ladder from the
widget's own scene transform, the terrain from the matrix the GL renderer
builds out of the arguments the SVS item actually passes to draw().
"""
from types import SimpleNamespace
from unittest import mock

import numpy as np
import pytest
from PyQt6.QtCore import QPointF
from PyQt6.QtWidgets import QApplication, QGraphicsLineItem

from pyefis.instruments import ai
from pyefis.instruments.ai.camera import M_PER_FT, project
from pyefis.instruments.ai.svs import make_svs_item
from pyefis.instruments.ai.svs_gl import SVSGLRenderer

# 5 mrad, the tolerance the AER-5122 testcase states.
TOL_DEG = 0.29


@pytest.fixture
def app(qtbot):
    test_app = QApplication.instance()
    if test_app is None:
        test_app = QApplication([])
    return test_app


def _reset_ai_items(fix):
    for key in ["PITCH", "ROLL", "ALAT", "TAS"]:
        item = fix.db.get_item(key)
        item.old = item.bad = item.fail = False


def _widget(qtbot, horizon_position, pitch_degrees_shown, pitch,
            width=1024, height=768):
    widget = ai.AI()
    widget.pitchDegreesShown = pitch_degrees_shown
    widget.horizon_position = horizon_position
    qtbot.addWidget(widget)
    widget.resize(width, height)
    widget.show()
    qtbot.waitExposed(widget)
    # resizeEvent rebuilds the scene and pixelsPerDeg from the live
    # pitchDegreesShown; force the pose and re-run redraw for it.
    widget._pitchAngle = pitch
    widget._rollAngle = 0.0
    widget.redraw()
    return widget


def _ladder_zero_up_px(widget):
    """Pixels ABOVE the viewport centre at which the widget draws its
    zero-pitch line, read from the scene transform redraw() applied."""
    line = widget._horizon_line.line()
    mid = QPointF((line.x1() + line.x2()) / 2.0, line.y1())
    vy = widget.mapFromScene(mid).y()
    return widget.viewport().height() / 2.0 - vy


def _terrain_zero_up_px(widget, lat=24.30, lon=-81.80, alt_ft=100.0):
    """Pixels above the viewport centre at which the SVS camera puts a
    point at the aircraft's own altitude, far ahead: the zero-elevation
    locus, before the shader's curvature drop (the physical dip)."""
    widget._svs_lat, widget._svs_lon, widget._svs_alt = lat, lon, alt_ft
    widget._fpm_head = 180.0
    widget._magvar = 0.0
    renderer = mock.Mock()
    renderer.ready = True
    with mock.patch.object(widget, "_svs_position_valid", return_value=True):
        make_svs_item(renderer, widget).paint(mock.Mock(), None)
    assert renderer.draw.called
    args, kwargs = renderer.draw.call_args
    # SVSRenderer.draw(painter, w, h, lat, lon, alt, pitch, roll, head,
    # ppd, dpr, **camera kwargs) -> SVSGLRenderer._update_camera(w, h,
    # lat, lon, alt, pitch, roll, head, ppd, **camera kwargs).
    w, h = args[1], args[2]
    cam = SimpleNamespace(_patch_origin=(lat, lon),
                          _parent=SimpleNamespace(earth_curvature=False))
    SVSGLRenderer._update_camera(cam, *args[1:10], **kwargs)
    vp = np.array(cam._frame_vp.data(), dtype=float).reshape(4, 4).T
    # 50 km due south (heading 180) at the aircraft's altitude.
    _, y, cw = project(vp, 0.0, -50e3, alt_ft * M_PER_FT)
    assert cw > 0
    return (y / cw) * h / 2.0


@pytest.mark.parametrize("horizon_position, pds, pitch", [
    (75, 50.0, -10.0),    # the AER-5122 testcase geometry
    (68, 40.0, -10.0),    # Beelink live
    (68, 25.0, -10.0),    # Pi live
    (75, 50.0, 0.0),
    (75, 50.0, 10.0),
    (50, 50.0, -10.0),    # centred: the pre-existing behaviour
])
def test_terrain_horizon_on_ladder_zero_pitch(fix, qtbot, horizon_position,
                                              pds, pitch):
    _reset_ai_items(fix)
    widget = _widget(qtbot, horizon_position, pds, pitch)
    ppd = widget.viewport().height() / pds
    ladder = _ladder_zero_up_px(widget)
    # Sanity: the ladder places zero pitch linearly, as described.
    assert ladder == pytest.approx(
        widget._horizon_offset_px() - pitch * ppd, abs=1.0)
    terrain = _terrain_zero_up_px(widget)
    assert abs(terrain - ladder) / ppd < TOL_DEG, (
        "terrain zero-elevation locus %.1f px vs ladder zero-pitch %.1f px "
        "(%.2f deg)" % (terrain, ladder, (terrain - ladder) / ppd))


@pytest.mark.parametrize("horizon_position, pds", [(75, 50.0), (68, 25.0)])
@pytest.mark.parametrize("pitch", [-20.0, -15.0, 15.0])
def test_horizon_position_adds_no_error(fix, qtbot, horizon_position, pds,
                                        pitch):
    """Past about 14 deg the pinhole's tan(pitch) leaves the linear ladder
    by more than 5 mrad even on a centred screen; that residual is not
    horizon_position's. Raising the reference must not add to it."""
    _reset_ai_items(fix)
    errs = []
    for hp in (50, horizon_position):
        widget = _widget(qtbot, hp, pds, pitch)
        errs.append(_terrain_zero_up_px(widget) - _ladder_zero_up_px(widget))
    assert errs[1] == pytest.approx(errs[0], abs=1.0)


# --- AER-5125: the ladder follows the terrain's tangent at steep pitch -------
#
# AC 23-26 3.c / AC 20-167B 4.3.2.5.3: terrain above the aircraft's
# altitude must appear above the zero-pitch line and terrain below it
# below; a flight path marker over terrain must mean the airplane clears
# it. A pinhole camera puts a direction e degrees above the boresight at
# tan(e), so with SVS live the ladder, the zero-pitch line and the FPM
# have to use the same tangent, or they leave the terrain past about 14
# deg of pitch (0.85 deg at -20 on a linear ladder).

def _svs_widget(qtbot, horizon_position, pds, pitch):
    widget = _widget(qtbot, horizon_position, pds, pitch)
    # Configured and enabled; the scale choice must not depend on whether
    # the last frame happened to paint terrain.
    widget._svs_renderer = SimpleNamespace(
        enabled=True, ready=False, gl_failed=False, drew_terrain=False,
        consume_async_dirty=lambda: False)
    widget.redraw()
    return widget


def _terrain_up_px(widget, elev_deg, lat=24.30, lon=-81.80, alt_ft=100.0):
    """Pixels above the viewport centre at which the SVS camera puts a
    point 50 km dead ahead, *elev_deg* above the aircraft's local level."""
    widget._svs_lat, widget._svs_lon, widget._svs_alt = lat, lon, alt_ft
    widget._fpm_head = 180.0
    widget._magvar = 0.0
    renderer = mock.Mock()
    renderer.ready = True
    with mock.patch.object(widget, "_svs_position_valid", return_value=True):
        make_svs_item(renderer, widget).paint(mock.Mock(), None)
    args, kwargs = renderer.draw.call_args
    h = args[2]
    cam = SimpleNamespace(_patch_origin=(lat, lon),
                          _parent=SimpleNamespace(earth_curvature=False))
    SVSGLRenderer._update_camera(cam, *args[1:10], **kwargs)
    vp = np.array(cam._frame_vp.data(), dtype=float).reshape(4, 4).T
    d = 50e3
    up = alt_ft * M_PER_FT + d * np.tan(np.radians(elev_deg))
    _, y, cw = project(vp, 0.0, -d, up)
    assert cw > 0
    return (y / cw) * h / 2.0


GEOMETRIES = [(50, 50.0), (75, 50.0), (68, 40.0), (68, 25.0)]


@pytest.mark.parametrize("horizon_position, pds", GEOMETRIES)
@pytest.mark.parametrize("pitch", [-20.0, -15.0, 15.0, 20.0])
def test_steep_pitch_horizon_on_zero_pitch_line(fix, qtbot, horizon_position,
                                                pds, pitch):
    _reset_ai_items(fix)
    widget = _svs_widget(qtbot, horizon_position, pds, pitch)
    ppd = widget.viewport().height() / pds
    ladder = _ladder_zero_up_px(widget)
    terrain = _terrain_up_px(widget, 0.0)
    assert abs(terrain - ladder) / ppd < TOL_DEG, (
        "terrain horizon %.1f px vs zero-pitch line %.1f px (%.2f deg)"
        % (terrain, ladder, (terrain - ladder) / ppd))


@pytest.mark.parametrize("horizon_position, pds", [(50, 50.0), (75, 50.0)])
@pytest.mark.parametrize("pitch", [-20.0, 20.0])
def test_every_visible_rung_on_its_terrain_elevation(fix, qtbot,
                                                     horizon_position, pds,
                                                     pitch):
    """Rung i sits where the terrain draws a point i deg above level, for
    every rung the widget shows -- not only the zero line."""
    _reset_ai_items(fix)
    widget = _svs_widget(qtbot, horizon_position, pds, pitch)
    ppd = widget.viewport().height() / pds
    half = widget.viewport().height() / 2.0
    checked = 0
    for i, item in widget.pitchItems:
        if not isinstance(item, QGraphicsLineItem) or item.opacity() == 0:
            continue
        up = half - widget.mapFromScene(
            item.sceneBoundingRect().center()).y()
        if abs(up) > half:
            continue   # off the glass
        terrain = _terrain_up_px(widget, float(i))
        assert abs(terrain - up) / ppd < TOL_DEG, (
            "rung %+d at %.1f px vs terrain %.1f px (%.2f deg)"
            % (i, up, terrain, (terrain - up) / ppd))
        checked += 1
    assert checked >= 10


@pytest.mark.parametrize("pitch, fpa", [(-20.0, -23.0), (20.0, 12.0),
                                        (15.0, 0.0)])
def test_fpm_on_its_terrain_elevation(fix, qtbot, pitch, fpa):
    """AC 23-26 3.c: the FPM over terrain means the airplane clears it, so
    the FPM sits where the terrain draws a point fpa deg above level."""
    _reset_ai_items(fix)
    widget = _svs_widget(qtbot, 50, 50.0, pitch)
    for k in ('VS', 'GS', 'TRACK', 'HEAD', 'VPATH'):
        widget._fpm_fail[k] = False
        widget._fpm_bad[k] = False
    widget._fpm_vpath = fpa
    widget._fpm_track = widget._fpm_head = 180.0
    widget._fpm_gs = 120.0
    widget._drawFPM(mock.MagicMock(), widget.width(), widget.height())
    ppd = widget.viewport().height() / 50.0
    # _fpm_y_px is down from the raised reference, in the rolled frame.
    fpm_up = widget._horizon_offset_px() - widget._fpm_y_px
    terrain = _terrain_up_px(widget, fpa)
    assert abs(terrain - fpm_up) / ppd < TOL_DEG, (
        "FPM %.1f px vs terrain at fpa %.1f px" % (fpm_up, terrain))


@pytest.mark.parametrize("pitch", [-20.0, 20.0])
def test_horizon_heading_ticks_on_zero_pitch_line(fix, qtbot, pitch):
    """The heading ticks are drawn on the zero-pitch line, so they move with
    it onto the tangent."""
    _reset_ai_items(fix)
    widget = _svs_widget(qtbot, 75, 50.0, pitch)
    widget.horizon_heading_marks = True
    widget._fpm_fail["HEAD"] = widget._fpm_bad["HEAD"] = False
    widget._fpm_head = 180.0
    painter = mock.MagicMock()
    widget._draw_horizon_heading(painter, widget.width(), widget.height())
    assert painter.drawLine.called
    tick_y = painter.drawLine.call_args_list[0].args[0].y()
    # tick_y is down from the raised reference, in the rolled frame.
    assert widget._horizon_offset_px() - tick_y == pytest.approx(
        _ladder_zero_up_px(widget), abs=1.0)


@pytest.mark.parametrize("svs, pitch, off", [
    (True, 24.0, True),     # tangent: horizon leaves the glass at 23.6
    (False, 24.0, False),   # linear: at 25
    (False, 25.0, True),
])
def test_horizon_off_glass_follows_the_tangent(fix, qtbot, svs, pitch, off):
    _reset_ai_items(fix)
    if svs:
        widget = _svs_widget(qtbot, 50, 50.0, pitch)
    else:
        widget = _widget(qtbot, 50, 50.0, pitch)
    assert widget._horizon_off_glass() is off


@pytest.mark.parametrize("pitch", [-20.0, 20.0])
def test_ladder_stays_linear_without_svs(fix, qtbot, pitch):
    """No terrain, nothing to register with: the long-standing linear
    ladder stays, as _horizontal_px does (pyEfis #304)."""
    _reset_ai_items(fix)
    widget = _widget(qtbot, 50, 50.0, pitch)
    ppd = widget.viewport().height() / 50.0
    assert _ladder_zero_up_px(widget) == pytest.approx(-pitch * ppd, abs=1.0)
