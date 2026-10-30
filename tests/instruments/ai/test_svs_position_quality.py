"""
AER-4243: the SVS removes the terrain when the position goes old, bad or failed.

Before this, the SVS read only LAT/LONG values, so a dead GPS left the terrain
drawn at the last position with no annunciation, while the moving map beside it
said NO POS. Now a LAT or LONG that is old, bad or failed removes the terrain,
returns the brown attitude ground and annunciates SVS UNAVAIL -- the same state
as a GL failure.

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
    for key in ("PITCH", "ROLL", "ALAT", "TAS", "LAT", "LONG"):
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


@pytest.mark.parametrize("key", ["LAT", "LONG"])
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
    for key in ("PITCH", "ROLL", "ALAT", "TAS", "LAT", "LONG"):
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
