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
from PyQt6.QtWidgets import QApplication

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
