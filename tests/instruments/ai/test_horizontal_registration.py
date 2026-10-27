"""pyEfis #304: horizontal symbology on an SVS screen must sit over the
terrain at the same bearing.

Before the fix, the heading ticks and the FPM's drift offset were placed at
``deg * pixelsPerDeg`` -- the AI's VERTICAL scale (h / pitchDegreesShown),
and linear -- while the terrain projects bearings at h / 30 through a
tangent. At pitchDegreesShown 50 and h 600 a tick 10 deg off the nose was
drawn at 120 px over terrain that sits at ~202 px.

Without SVS there is no terrain to register with, and the linear scale is
kept unchanged.
"""
from types import SimpleNamespace

import pytest
from PyQt6.QtGui import QPaintEvent
from PyQt6.QtWidgets import QApplication

from pyefis.instruments import ai
from pyefis.instruments.ai.camera import terrain_horizontal_px


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


def _widget(qtbot, svs, width=400, height=600):
    widget = ai.AI()
    for k in ('VS', 'GS', 'TRACK', 'HEAD'):
        widget._fpm_fail[k] = False
    if svs:
        # Configured and enabled, but not drawing: the scale choice must
        # not depend on whether the last frame happened to paint terrain.
        widget._svs_renderer = SimpleNamespace(
            enabled=True, ready=False, gl_failed=False, drew_terrain=False)
    qtbot.addWidget(widget)
    widget.resize(width, height)
    widget.show()
    qtbot.waitExposed(widget)
    return widget, QPaintEvent(widget.viewport().rect())


@pytest.mark.parametrize("deg", [-20.0, 10.0, 30.0])
def test_horizontal_px_uses_terrain_projection_with_svs(fix, qtbot, deg):
    _reset_ai_items(fix)
    widget, _ = _widget(qtbot, svs=True)
    ppd = widget.pixelsPerDeg
    assert widget._horizontal_px(deg, ppd) == pytest.approx(
        terrain_horizontal_px(deg, widget.height()))
    # And that is not the old vertical-scale linear placement.
    assert widget._horizontal_px(deg, ppd) != pytest.approx(deg * ppd)


@pytest.mark.parametrize("deg", [-20.0, 10.0, 30.0])
def test_horizontal_px_unchanged_without_svs(fix, qtbot, deg):
    _reset_ai_items(fix)
    widget, _ = _widget(qtbot, svs=False)
    ppd = widget.pixelsPerDeg
    assert widget._horizontal_px(deg, ppd) == pytest.approx(deg * ppd)


def test_fpm_drift_is_placed_on_the_terrain_scale(fix, qtbot):
    _reset_ai_items(fix)
    widget, event = _widget(qtbot, svs=True)
    widget._fpm_gs = 120.0
    fix.db.set_value("HEAD", 87.0)
    widget._fpm_track = 92.0          # 5 deg of drift, no MAGVAR
    widget.paintEvent(event)
    assert widget._fpm_x_px == pytest.approx(
        terrain_horizontal_px(5.0, widget.height()))


def test_heading_ticks_go_through_the_horizontal_mapping(fix, qtbot):
    _reset_ai_items(fix)
    widget, event = _widget(qtbot, svs=True)
    widget.horizon_heading_marks = True
    seen = []
    real = widget._horizontal_px

    def spy(deg, ppd):
        seen.append(deg)
        return real(deg, ppd)

    widget._horizontal_px = spy
    fix.db.set_value("HEAD", 87.0)
    widget.paintEvent(event)
    # Ticks every 10 deg: 90 sits 3 deg right of a heading of 87.
    assert any(d == pytest.approx(3.0) for d in seen)
