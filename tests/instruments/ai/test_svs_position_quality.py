"""
AER-4243: the SVS removes the terrain when the position goes old, bad or failed.

Before this, the SVS read only LAT/LONG values, so a dead GPS left the terrain
drawn at the last position with no annunciation, while the moving map beside it
said NO POS. Now a LAT or LONG that is old, bad or failed removes the terrain,
returns the brown attitude ground and annunciates SVS UNAVAIL -- the same state
as a GL failure.

SVSALT1 (AER-6458): the camera height is TALT, the GPS/EKF MSL height, and
TALT is gated like LAT/LONG. ALT is indicated altitude and follows the baro
setting, so it never reaches the SVS pose, and there is no ALT fallback.

Every flag here is driven through the real pyavtools fix item (``item.old =
True`` emits ``oldChanged``, exactly as the client does when the gateway flags
the key), never by poking the widget's own state.
"""
from unittest import mock

import numpy as np
import pytest
from PyQt6.QtGui import QImage, QPainter

from pyefis.instruments.ai import AI
from pyefis.instruments.ai.svs import make_svs_item

# The SVS UNAVAIL pen colour (ai_widget._paint_overlays).
_AMBER = (255, 176, 0)


def _ai_with_svs(fix, qtbot):
    for key in ("PITCH", "ROLL", "ALAT", "TAS", "LAT", "LONG", "TALT"):
        item = fix.db.get_item(key)
        item.old = False
        item.bad = False
        item.fail = False
    widget = AI()
    qtbot.addWidget(widget)
    widget.resize(400, 300)
    widget.show()
    qtbot.waitExposed(widget)
    # A stand-in renderer: ready, GL fine, drew terrain last frame. No GL in
    # this environment, so the real renderer would only ever be gl_failed.
    renderer = mock.Mock()
    renderer.enabled = True
    renderer.ready = True
    renderer.gl_failed = False
    renderer.drew_terrain = True
    widget._svs_renderer = renderer
    return widget, renderer


def _amber_pixels(widget):
    img = QImage(widget.width(), widget.height(), QImage.Format.Format_RGB32)
    img.fill(0)
    p = QPainter(img)
    widget._paint_overlays(p)
    p.end()
    ptr = img.constBits()
    ptr.setsize(img.sizeInBytes())
    bgra = np.frombuffer(ptr, np.uint8).reshape(img.height(), img.bytesPerLine() // 4, 4)
    r, g, b = _AMBER
    return int(np.count_nonzero((bgra[..., 2] == r) & (bgra[..., 1] == g) & (bgra[..., 0] == b)))


@pytest.mark.parametrize("key", ["LAT", "LONG", "TALT"])
@pytest.mark.parametrize("flag", ["old", "bad", "fail"])
def test_dead_position_removes_terrain_and_annunciates(fix, qtbot, key, flag):
    widget, renderer = _ai_with_svs(fix, qtbot)
    item = make_svs_item(renderer, widget)

    # Valid position: terrain draws, the land is sky, no annunciation.
    item.paint(mock.Mock(), None)
    assert renderer.draw.call_count == 1
    widget._update_land_brush()
    assert widget._land_brush_cur is widget.gblue_brush
    assert _amber_pixels(widget) == 0

    # The gateway flags the key: through the real fix item.
    setattr(fix.db.get_item(key), flag, True)

    item.paint(mock.Mock(), None)
    assert renderer.draw.call_count == 1          # no terrain at a dead position
    assert renderer.drew_terrain is False
    # The flag handler itself restored the brown ground (no frame tick needed).
    assert widget._land_brush_cur is widget.gbrown_brush
    assert _amber_pixels(widget) > 0              # SVS UNAVAIL

    # Position recovers: terrain and sky ground come back, annunciation clears.
    setattr(fix.db.get_item(key), flag, False)
    item.paint(mock.Mock(), None)
    assert renderer.draw.call_count == 2
    renderer.drew_terrain = True
    widget._update_land_brush()
    assert widget._land_brush_cur is widget.gblue_brush
    assert _amber_pixels(widget) == 0


def test_widget_built_while_position_old_starts_unavailable(fix, qtbot):
    """The flags are read at construction too: a screen built while the GPS is
    already dead must not show terrain before the first flag change arrives."""
    for key in ("PITCH", "ROLL", "ALAT", "TAS", "LAT", "LONG", "TALT"):
        fix.db.get_item(key).old = False
    fix.db.get_item("LAT").old = True
    widget = AI()
    qtbot.addWidget(widget)
    renderer = mock.Mock(enabled=True, ready=True, gl_failed=False)
    widget._svs_renderer = renderer
    make_svs_item(renderer, widget).paint(mock.Mock(), None)
    assert not renderer.draw.called


def test_dead_position_with_svs_disabled_has_no_annunciation(fix, qtbot):
    """No SVS configured -> a dead GPS is the map's business, not the AI's."""
    widget, renderer = _ai_with_svs(fix, qtbot)
    renderer.enabled = False
    fix.db.get_item("LAT").old = True
    assert _amber_pixels(widget) == 0


def test_svs_camera_height_is_talt_not_alt(fix, qtbot):
    """TALT and ALT 900 ft apart (a baro setting about 1 inHg off): the SVS
    camera sits at TALT. A baro change moves ALT and must not move the
    terrain; a TALT change must."""
    fix.db.set_value("TALT", 5000.0)
    fix.db.set_value("ALT", 4100.0)
    widget, renderer = _ai_with_svs(fix, qtbot)
    pose = mock.Mock()
    renderer.make_pose_source.return_value = pose
    widget._attach_pose_source(renderer)

    assert widget.frame_pose().alt_ft == 5000.0
    pose.set_altitude.assert_called_once_with(5000.0)

    # The pilot turns the baro knob: ALT moves 900 ft, the camera does not.
    pose.reset_mock()
    fix.db.set_value("ALT", 5000.0)
    assert widget.frame_pose().alt_ft == 5000.0
    pose.set_altitude.assert_not_called()

    # The GPS height changes: the camera follows it.
    fix.db.set_value("TALT", 5200.0)
    assert widget.frame_pose().alt_ft == 5200.0
    pose.set_altitude.assert_called_once_with(5200.0)


def test_no_talt_key_shows_svs_unavail(fix, qtbot):
    """An install with no TALT writer gets SVS UNAVAIL, not terrain at the
    baro-corrected ALT (Bill's ruling: no silent fallback)."""
    for key in ("PITCH", "ROLL", "ALAT", "TAS", "LAT", "LONG", "TALT"):
        fix.db.get_item(key).old = False
    real_get_item = fix.db.get_item

    def get_item(key, *a, **kw):
        if key == "TALT":
            raise KeyError(key)
        return real_get_item(key, *a, **kw)

    with mock.patch.object(fix.db, "get_item", side_effect=get_item):
        widget = AI()
    qtbot.addWidget(widget)
    widget.resize(400, 300)
    widget.show()
    qtbot.waitExposed(widget)
    renderer = mock.Mock(enabled=True, ready=True, gl_failed=False)
    widget._svs_renderer = renderer
    make_svs_item(renderer, widget).paint(mock.Mock(), None)
    assert not renderer.draw.called
    assert _amber_pixels(widget) > 0
