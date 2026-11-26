"""MAPALT1 (AER-6591): the moving map's terrain caution mode measures
clearance from TALT, the GPS/EKF MSL height, never from indicated ALT.

Bill's ruling (packet AER-6493, matching SVSALT1, AER-6409): TALT only. With
no usable TALT the caution bands are not drawn -- the plain elevation tint
stays -- and the status chip says TERR UNAVAIL. There is no ALT fallback.
"""
from unittest import mock

import numpy as np
import pytest
from PyQt6.QtGui import QPaintEvent

from pyefis.instruments import map as moving_map
from pyefis.instruments.ai import terrain_shading as ts

LAT0, LON0 = 37.95, -107.91
ELEV_M = 1000.0
ELEV_FT = ELEV_M * 3.28084
FLAT_SHADE = 0.875      # the map hillshade on flat ground


class _FlatCache:
    def get(self, la, lo):
        return np.full((1201, 1201), ELEV_M, np.float32)


def _lit(rgb):
    return tuple(int(np.float32(v) * FLAT_SHADE) for v in rgb)


RELIEF = _lit(tuple(c[0] for c in ts.hypso_rgb(np.array([ELEV_FT]))))
RED = _lit(ts.PALETTES["clearance"][2])          # under 500 ft clearance


def _map(fix, qtbot):
    w = moving_map.MovingMap()
    w.terrain_mode = "caution"
    qtbot.addWidget(w)
    w.resize(300, 300)
    w.show()
    qtbot.waitExposed(w)
    w.paintEvent(QPaintEvent(w.rect()))       # builds the layers
    lay = next(l for l in w._layers if l.id == "terrain")
    lay._cache = _FlatCache()
    return w, lay


def _centre_px(w, lay):
    """Run the terrain layer's paint-time inputs from the widget, then
    render the window it would request and read the centre pixel."""
    x = moving_map.MapTransform(LAT0, LON0, 10.0, 0.0, 200, 200, 0.5)
    x.defer_render = True
    lay.paint(mock.Mock(), x)
    key = lay._key(x)
    img, _ = lay._render((key, x.lat0, x.lon0, x.range_nm, x.w, x.h, x.cy))
    c = img.pixelColor(img.width() // 2, img.height() // 2)
    return (c.red(), c.green(), c.blue()), key


def _set_alts(fix, talt, alt):
    fix.db.set_value("TALT", talt)
    fix.db.set_value("ALT", alt)


@pytest.fixture(autouse=True)
def _position(fix):
    for key in ("LAT", "LONG", "TALT", "ALT"):
        fix.db.get_item(key).old = False
    fix.db.set_value("LAT", LAT0)
    fix.db.set_value("LONG", LON0)


def test_caution_band_follows_talt_not_alt(fix, qtbot):
    """TALT 300 ft above the terrain (red), ALT 900 ft higher (clear): the
    band is TALT's. Moving ALT 900 ft each way, as a 1 inHg baro change
    does, changes nothing; moving TALT does."""
    w, lay = _map(fix, qtbot)
    _set_alts(fix, ELEV_FT + 300.0, ELEV_FT + 1200.0)
    assert w._alt_ft == pytest.approx(ELEV_FT + 300.0, abs=1.0)
    assert w.terrain_caution_available()
    px, key = _centre_px(w, lay)
    assert key[6] == "caution"
    assert px == RED
    for alt in (ELEV_FT + 300.0, ELEV_FT - 600.0):
        fix.db.set_value("ALT", alt)
        assert _centre_px(w, lay) == (px, key)
    fix.db.set_value("TALT", ELEV_FT + 1500.0)
    assert _centre_px(w, lay)[0] == RELIEF


@pytest.mark.parametrize("flag", ["old", "bad", "fail"])
def test_unusable_talt_drops_the_bands_and_annunciates(fix, qtbot, flag):
    w, lay = _map(fix, qtbot)
    _set_alts(fix, ELEV_FT + 300.0, ELEV_FT + 300.0)
    assert _centre_px(w, lay)[0] == RED
    assert "TERR UNAVAIL" not in w._status_chip_text(False)

    setattr(fix.db.get_item("TALT"), flag, True)
    assert not w.terrain_caution_available()
    px, key = _centre_px(w, lay)
    assert key[6] == "relief" and key[7] == 0 and key[-1] is None
    assert px == RELIEF
    assert "TERR UNAVAIL" in w._status_chip_text(False)

    setattr(fix.db.get_item("TALT"), flag, False)
    assert w.terrain_caution_available()
    assert _centre_px(w, lay)[0] == RED
    assert "TERR UNAVAIL" not in w._status_chip_text(False)


def test_no_talt_key_drops_the_bands_and_annunciates(fix, qtbot):
    """An install with no TALT writer gets plain relief and TERR UNAVAIL,
    not bands measured from the baro-corrected ALT."""
    real_get_item = fix.db.get_item

    def get_item(key, *a, **kw):
        if key == "TALT":
            raise KeyError(key)
        return real_get_item(key, *a, **kw)

    _set_alts(fix, ELEV_FT + 300.0, ELEV_FT + 300.0)
    w0, _ = _map(fix, qtbot)          # TALT defined: bands drawn
    assert w0.terrain_caution_available()
    with mock.patch.object(fix.db, "get_item", side_effect=get_item):
        w, lay = _map(fix, qtbot)
    assert not w.terrain_caution_available()
    px, key = _centre_px(w, lay)
    assert key[6] == "relief"
    assert px == RELIEF
    assert "TERR UNAVAIL" in w._status_chip_text(False)


def test_relief_mode_never_annunciates(fix, qtbot):
    """TERR UNAVAIL is about caution mode only: relief mode never draws
    bands, so it loses nothing without TALT. Nor does a terrain layer the
    pilot switched off."""
    w, lay = _map(fix, qtbot)
    fix.db.get_item("TALT").fail = True
    assert "TERR UNAVAIL" in w._status_chip_text(False)
    w.set_layer("terrain", False)
    assert "TERR UNAVAIL" not in w._status_chip_text(False)
    w.set_layer("terrain", True)
    w.terrain_mode = "relief"
    assert "TERR UNAVAIL" not in w._status_chip_text(False)


def test_layer_without_an_owner_answer_draws_no_bands():
    """Fail safe: a terrain layer whose owner cannot say TALT is usable
    does not draw bands."""
    from pyefis.instruments.map.layers.terrain import TerrainLayer
    lay = TerrainLayer()
    lay._mode = "caution"

    class Owner:
        _alt_ft = ELEV_FT
    lay._owner = Owner
    assert lay._caution() is False
