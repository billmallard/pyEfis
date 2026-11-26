#  SPDX-License-Identifier: GPL-2.0-or-later
"""INS5 (AER-6588): the moving map honours bad and fail as well as old on its
position, track and altitude inputs, and the quality of TRACK.

On dev the map subscribed to old alone for LAT, LONG, TRACKM and ALT (and
read nothing of ALT's), and to the value alone of TRACK, which it turns by.
So a bad or failed position drew a live ownship, a failed track a live TRK
box, and a stale altitude live caution bands. The rules under test, from the
spec's "standard fail/old/bad handling: stale position greys the ownship and
annunciates" (moving_map_spec.md section 2):

- `LAT`/`LONG` old, bad or fail: grey ownship and `NO POS` in the chip.
- `TRACKM`, or `TRACK` where the gateway has it, old, bad or fail: grey TRK
  box (ND) and grey ownship (it points along the track); no `NO POS`.
- `ALT` old, bad or fail in caution mode: the terrain draws relief, no bands,
  and the chip says `NO ALT`.

Flags are driven through the FIX item, so the subscription is under test too.
"""
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from pyefis.instruments import map as moving_map
from pyefis.instruments.map import nd

W, H = 800, 480
GRAY = QColor(Qt.GlobalColor.gray).name()


def _define(fix, key, value):
    fix.db.define_item(key, key, "float", -1e6, 1e6, "", 0, "")
    fix.db.set_value(key, value)
    item = fix.db.get_item(key)
    item.old = item.bad = item.fail = False
    return item


def _clean(fix):
    _define(fix, "TRACKM", 90.0)
    for key, value in (("LAT", 34.4), ("LONG", -119.8), ("TRACK", 78.0),
                       ("ALT", 3000.0)):
        fix.db.set_value(key, value)
        item = fix.db.get_item(key)
        item.old = item.bad = item.fail = False


class _Recorder(moving_map.QPainter):
    """The map module's QPainter, recording each polygon's brush colour, each
    rect's pen colour and each string drawn."""
    polys, rects, texts = [], [], []

    def drawPolygon(self, *a):
        _Recorder.polys.append(self.brush().color().name())
        return super().drawPolygon(*a)

    def drawRect(self, *a):
        _Recorder.rects.append(self.pen().color().name())
        return super().drawRect(*a)

    def drawText(self, *a):
        _Recorder.texts.append(a[-1])
        return super().drawText(*a)


def _paint(m, monkeypatch):
    _Recorder.polys, _Recorder.rects, _Recorder.texts = [], [], []
    monkeypatch.setattr(moving_map, "QPainter", _Recorder)
    m.grab()
    monkeypatch.undo()
    chip = [t for t in _Recorder.texts if " NM  " in t]
    return list(_Recorder.polys), list(_Recorder.rects), chip


def _map(fix, qtbot, **opts):
    _clean(fix)
    m = moving_map.MovingMap(None)
    qtbot.addWidget(m)
    m.resize(W, H)
    for k, v in opts.items():
        setattr(m, k, v)
    return m


def test_control_all_valid(fix, qtbot, monkeypatch):
    m = _map(fix, qtbot, nd_mode="expanded")
    polys, rects, chip = _paint(m, monkeypatch)
    assert QColor(m.symbol_color).name() in polys and GRAY not in polys
    assert nd.GREY.name() not in rects
    assert chip and "NO POS" not in chip[0] and "NO ALT" not in chip[0]


@pytest.mark.parametrize("key", ["LAT", "LONG"])
@pytest.mark.parametrize("flag", ["old", "bad", "fail"])
def test_degraded_position_greys_ownship_and_says_no_pos(fix, qtbot,
                                                         monkeypatch, key,
                                                         flag):
    m = _map(fix, qtbot)
    setattr(fix.db.get_item(key), flag, True)
    polys, _rects, chip = _paint(m, monkeypatch)
    assert GRAY in polys and QColor(m.symbol_color).name() not in polys
    assert "NO POS" in chip[0]

    setattr(fix.db.get_item(key), flag, False)
    polys, _rects, chip = _paint(m, monkeypatch)
    assert GRAY not in polys and "NO POS" not in chip[0]


@pytest.mark.parametrize("key", ["TRACKM", "TRACK"])
@pytest.mark.parametrize("flag", ["old", "bad", "fail"])
def test_degraded_track_greys_trk_box_and_ownship(fix, qtbot, monkeypatch,
                                                  key, flag):
    m = _map(fix, qtbot, nd_mode="expanded")
    setattr(fix.db.get_item(key), flag, True)
    polys, rects, chip = _paint(m, monkeypatch)
    assert nd.GREY.name() in rects                 # the TRK box
    assert GRAY in polys                           # the ownship arrow
    assert "NO POS" not in chip[0]                 # the position is fine

    setattr(fix.db.get_item(key), flag, False)
    polys, rects, _chip = _paint(m, monkeypatch)
    assert nd.GREY.name() not in rects and GRAY not in polys


def test_gateway_without_track_follows_trackm_alone(fix, qtbot, monkeypatch):
    """TRACK is optional (the map then turns by TRACKM): its absence is not
    a stale track."""
    _clean(fix)
    real = fix.db.get_item

    def no_track(key):
        if key == "TRACK":
            raise KeyError(key)
        return real(key)
    monkeypatch.setattr(fix.db, "get_item", no_track)
    m = moving_map.MovingMap(None)
    qtbot.addWidget(m)
    monkeypatch.undo()
    assert m._track_true is None
    assert m._track_stale() is False


# --- ALT and the caution bands ----------------------------------------------

@pytest.mark.parametrize("flag", ["old", "bad", "fail"])
def test_degraded_alt_says_no_alt_in_caution_mode(fix, qtbot, monkeypatch,
                                                  flag):
    m = _map(fix, qtbot, terrain_mode="caution")
    _paint(m, monkeypatch)                         # builds the layers
    assert m._terrain_caution_live()
    setattr(fix.db.get_item("ALT"), flag, True)
    assert "NO ALT" in _paint(m, monkeypatch)[2][0]
    setattr(fix.db.get_item("ALT"), flag, False)
    assert "NO ALT" not in _paint(m, monkeypatch)[2][0]


def test_degraded_alt_in_relief_mode_says_nothing(fix, qtbot, monkeypatch):
    m = _map(fix, qtbot, terrain_mode="relief")
    _paint(m, monkeypatch)
    fix.db.get_item("ALT").old = True
    assert "NO ALT" not in _paint(m, monkeypatch)[2][0]


def _caution_px(alt_stale):
    """The terrain layer's centre pixel 300 ft above flat terrain, in caution
    mode: the warning band when ALT is good, relief when it is not."""
    from tests.instruments.ai import test_terrain_shading as tts
    from pyefis.instruments.map.layers.terrain import TerrainLayer
    lay = TerrainLayer()
    lay._cache = tts._FlatCache(tts.ELEV_M)
    lay._mode = "caution"

    class Owner:
        _alt_ft = tts.ELEV_FT + 300.0
        _lat, _lon = 37.95, -107.91

        @staticmethod
        def _stale(key):
            return alt_stale and key == "ALT"
    lay._owner = Owner
    lay._apt_db = None
    x = moving_map.MapTransform(37.95, -107.91, 10.0, 0.0, 200, 200, 0.5)
    lay._alt_ft = Owner._alt_ft
    lay._alt_valid = not Owner._stale("ALT")
    key = lay._key(x)
    img, _meta = lay._render((key, x.lat0, x.lon0, x.range_nm, x.w, x.h,
                              x.cy))
    c = img.pixelColor(img.width() // 2, img.height() // 2)
    return (c.red(), c.green(), c.blue()), key


def test_degraded_alt_drops_the_caution_bands_to_relief():
    import numpy as np
    from pyefis.instruments.ai import terrain_shading as ts
    from tests.instruments.ai import test_terrain_shading as tts
    good, good_key = _caution_px(False)
    assert good == tts._lit(ts.PALETTES["clearance"][2])     # warning band
    stale, stale_key = _caution_px(True)
    r, g, b = ts.hypso_rgb(np.array([tts.ELEV_FT]))
    assert stale == tts._lit((r[0], g[0], b[0]))             # relief
    assert stale_key != good_key           # a new image, not the cached bands


def test_terrain_layer_reads_alt_quality_from_the_map(fix, qtbot, monkeypatch):
    """paint() takes the ALT verdict from the owning map each frame."""
    m = _map(fix, qtbot, terrain_mode="caution")
    _paint(m, monkeypatch)
    lay = next(l for l in m._layers if l.id == "terrain")
    fix.db.get_item("ALT").bad = True
    _paint(m, monkeypatch)
    assert lay._alt_valid is False
    fix.db.get_item("ALT").bad = False
    _paint(m, monkeypatch)
    assert lay._alt_valid is True
