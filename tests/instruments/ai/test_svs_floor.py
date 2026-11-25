"""
SVSFLOOR1: the SVS camera never goes below the surface it draws.

Bill saw the SVS put the aircraft visibly under the runway on X-Plane, where
the sim's runway sits lower than NASR's published threshold, the height the
SVS draws the runway at. An aircraft cannot be under the ground, so the
renderer lifts the camera to the drawn surface (terrain, or the runway polygon
when that is higher) plus an eye height. Within a 30 ft band it does so
silently; past it, it still lifts and the AI shows an amber SVS HGT. The
height input is never written back to the bus, and a camera above the floor
is never moved.

The camera input is whatever feeds ``AI._svs_alt`` (ALT on dev, TALT after
SVSALT1); these tests set that attribute, so they pin the floor under either.
``draw`` is replaced because it needs a GL context; the floor runs before it,
in ``paint_svs_frame``, and the height ``draw`` receives is the camera height.
"""
from pathlib import Path
from unittest import mock

import numpy as np
import pytest
from PyQt6.QtGui import QImage, QPainter

from pyefis.instruments.ai import AI
from pyefis.instruments.ai.airport_db import AirportRecord, RunwayRecord
from pyefis.instruments.ai.svs import (
    SVS_EYE_HEIGHT_FT, SVS_FLOOR_BAND_FT, SVS_FLOOR_TAG_CLEAR_FT,
    SRTM3_SAMPLES, SVSRenderer, make_svs_item, tile_name)

FT_PER_M = 3.28084
FT_PER_DEG = 364491.0
LAT0, LON0 = 34.25, -118.75          # inside tile N34W119
TERRAIN_M = 30                       # flat tile, 98.4 ft
TERRAIN_FT = TERRAIN_M * FT_PER_M
RWY_LEN_FT = 6000.0
RWY_W_FT = 100.0
THR1_FT, THR2_FT = 150.0, 180.0      # sloped runway, above the terrain
_AMBER = (255, 176, 0)


def _tile_root(tmp_path, elevation_m=TERRAIN_M):
    name = tile_name(34, -119)
    d = tmp_path / "srtm3" / "N34"
    d.mkdir(parents=True, exist_ok=True)
    np.full((SRTM3_SAMPLES, SRTM3_SAMPLES), elevation_m,
            dtype=">i2").tofile(d / f"{name}.hgt")
    return tmp_path / "srtm3"


def _runway(thr1_ft=THR1_FT, thr2_ft=THR2_FT):
    """North-south runway: thr1 at the south end, thr2 at the north end."""
    return RunwayRecord(
        airport_id="TST", name="18/36",
        thr1_lat=LAT0, thr1_lon=LON0, thr1_elev_ft=thr1_ft,
        thr2_lat=LAT0 + RWY_LEN_FT / FT_PER_DEG, thr2_lon=LON0,
        thr2_elev_ft=thr2_ft,
        length_ft=RWY_LEN_FT, bearing_deg=0.0, width_ft=RWY_W_FT)


class _StubAirportDB:
    ready = True

    def __init__(self, runways):
        self._ap = AirportRecord(icao="KTST", name="Test", ref_lat=LAT0,
                                 ref_lon=LON0, elev_ft=THR1_FT,
                                 runways=runways)

    def airports_in_range(self, lat, lon, range_nm):
        return [self._ap]


def _renderer(tmp_path, runways=None, **cfg):
    r = SVSRenderer(dict({"enabled": True,
                          "tile_path": str(_tile_root(tmp_path))}, **cfg))
    if runways is not None:
        r.airport_db = _StubAirportDB(runways)
        # Bypass the async worker: hand the floor the airport list directly.
        airports = list(r._airports_in_range(LAT0, LON0))
        r._get_airports_cached = lambda lat, lon: airports
    r.draw = mock.Mock()
    return r


def _on_runway(f):
    """(lat, lon) on the runway centreline, fraction *f* from thr1."""
    return LAT0 + f * RWY_LEN_FT / FT_PER_DEG, LON0


def _rwy_ft(f):
    return THR1_FT + f * (THR2_FT - THR1_FT)


@pytest.fixture
def ai(fix, qtbot):
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
    return widget


def _paint(widget, renderer, lat, lon, alt_ft):
    """One SVS frame at (lat, lon, alt_ft); returns the camera height."""
    widget._svs_renderer = renderer
    widget._svs_lat, widget._svs_lon, widget._svs_alt = lat, lon, alt_ft
    renderer.draw.reset_mock()
    make_svs_item(renderer, widget).paint(mock.Mock(), None)
    assert renderer.draw.call_count == 1
    return renderer.draw.call_args.args[5]


def _amber_text(widget):
    img = QImage(widget.width(), widget.height(), QImage.Format.Format_RGB32)
    img.fill(0)
    p = QPainter(img)
    widget._paint_overlays(p)
    p.end()
    ptr = img.constBits()
    ptr.setsize(img.sizeInBytes())
    bgra = np.frombuffer(ptr, np.uint8).reshape(
        img.height(), img.bytesPerLine() // 4, 4)
    r, g, b = _AMBER
    return int(np.count_nonzero(
        (bgra[..., 2] == r) & (bgra[..., 1] == g) & (bgra[..., 0] == b)))


# -- The two definition-of-done cases ---------------------------------------

def test_height_40ft_under_the_runway_puts_the_camera_on_the_runway(
        ai, tmp_path):
    """AI-SVS-003, DoD 1: the input is 40 ft below the threshold elevation, on the
    runway at its threshold. The camera is the runway surface plus the eye
    height, not 40 ft under it."""
    r = _renderer(tmp_path, [_runway()])
    lat, lon = _on_runway(0.0)
    cam = _paint(ai, r, lat, lon, THR1_FT - 40.0)
    assert cam == pytest.approx(THR1_FT + SVS_EYE_HEIGHT_FT, abs=1e-6)


def test_height_past_the_band_under_terrain_clamps_and_annunciates(
        ai, tmp_path):
    """AI-SVS-003, DoD 2: off any runway, the input is past the band below the terrain.
    The camera is still lifted to the terrain, and SVS HGT shows."""
    r = _renderer(tmp_path, [_runway()])
    lat, lon = LAT0 + 0.02, LON0 + 0.02            # well clear of the runway
    alt = TERRAIN_FT - SVS_FLOOR_BAND_FT - 20.0
    cam = _paint(ai, r, lat, lon, alt)
    assert cam == pytest.approx(TERRAIN_FT + SVS_EYE_HEIGHT_FT, abs=1e-3)
    assert r.height_tag is True
    assert r.height_below_surface_ft == pytest.approx(
        SVS_FLOOR_BAND_FT + 20.0, abs=1e-3)
    assert _amber_text(ai) > 0


# -- The band ---------------------------------------------------------------

def test_inside_the_band_clamps_silently(ai, tmp_path):
    r = _renderer(tmp_path, [_runway()])
    lat, lon = _on_runway(0.5)
    cam = _paint(ai, r, lat, lon, _rwy_ft(0.5) - 20.0)
    assert cam == pytest.approx(_rwy_ft(0.5) + SVS_EYE_HEIGHT_FT, abs=1e-6)
    assert r.height_tag is False
    assert _amber_text(ai) == 0


def test_the_tag_clears_inside_the_band_not_at_its_edge(ai, tmp_path):
    """Past the band it sets; it clears only SVS_FLOOR_TAG_CLEAR_FT back
    inside, so a height hovering at 30 ft does not flicker it."""
    r = _renderer(tmp_path, [_runway()])
    lat, lon = _on_runway(0.0)
    edge = SVS_FLOOR_BAND_FT
    for below, tagged in ((edge, False), (edge + 1.0, True), (edge, True),
                          (edge - SVS_FLOOR_TAG_CLEAR_FT + 1.0, True),
                          (edge - SVS_FLOOR_TAG_CLEAR_FT, False),
                          (edge - 1.0, False)):
        _paint(ai, r, lat, lon, THR1_FT - below)
        assert r.height_tag is tagged, below


# -- Guardrails -------------------------------------------------------------

@pytest.mark.parametrize("above", [SVS_EYE_HEIGHT_FT, 6.0, 50.0, 5000.0])
def test_a_camera_above_the_floor_is_never_moved(ai, tmp_path, above):
    r = _renderer(tmp_path, [_runway()])
    lat, lon = _on_runway(0.25)
    alt = _rwy_ft(0.25) + above
    # Exactly on the floor the max() may pick the floor's own float.
    assert _paint(ai, r, lat, lon, alt) == pytest.approx(alt, abs=1e-9)
    assert r.height_tag is False


def test_the_floor_writes_no_fix_key(ai, tmp_path, fix):
    r = _renderer(tmp_path, [_runway()])
    before = {k: fix.db.get_item(k).value for k in ("ALT", "LAT", "LONG")}
    lat, lon = _on_runway(0.0)
    _paint(ai, r, lat, lon, THR1_FT - 200.0)
    assert {k: fix.db.get_item(k).value for k in before} == before
    assert ai._svs_alt == THR1_FT - 200.0      # the widget's input is kept


def test_a_dead_position_drops_the_tag_for_svs_unavail(ai, tmp_path, fix):
    r = _renderer(tmp_path, [_runway()])
    lat, lon = _on_runway(0.0)
    _paint(ai, r, lat, lon, THR1_FT - 200.0)
    assert r.height_tag is True
    fix.db.get_item("LAT").old = True
    make_svs_item(r, ai).paint(mock.Mock(), None)
    assert r.height_tag is False


# -- What the surface is ----------------------------------------------------

def test_the_runway_surface_follows_the_threshold_slope(tmp_path):
    r = _renderer(tmp_path, [_runway()])
    for f in (0.0, 0.3, 1.0):
        assert r.surface_elevation_ft(*_on_runway(f)) == pytest.approx(
            _rwy_ft(f), abs=1e-6)


def test_the_runway_edge_is_the_drawn_width(tmp_path):
    r = _renderer(tmp_path, [_runway()])
    lat, _ = _on_runway(0.5)
    import math
    dlon = (RWY_W_FT / 2.0) / FT_PER_DEG / math.cos(math.radians(lat))
    assert r.surface_elevation_ft(lat, LON0 + 0.98 * dlon) == pytest.approx(
        _rwy_ft(0.5), abs=1e-6)
    assert r.surface_elevation_ft(lat, LON0 + 1.02 * dlon) == pytest.approx(
        TERRAIN_FT, abs=1e-3)


def test_terrain_above_a_low_runway_wins(tmp_path):
    """GLO-30 is a surface model: trees and buildings can stand above the
    published runway. The floor is the higher of the two drawn surfaces."""
    r = _renderer(tmp_path, [_runway(thr1_ft=50.0, thr2_ft=50.0)])
    assert r.surface_elevation_ft(*_on_runway(0.5)) == pytest.approx(
        TERRAIN_FT, abs=1e-3)


def test_no_airport_data_floors_on_terrain(ai, tmp_path):
    r = _renderer(tmp_path)                       # no airport_db
    lat, lon = _on_runway(0.0)
    cam = _paint(ai, r, lat, lon, TERRAIN_FT - 10.0)
    assert cam == pytest.approx(TERRAIN_FT + SVS_EYE_HEIGHT_FT, abs=1e-3)


def test_no_terrain_data_leaves_the_height_alone(tmp_path):
    r = SVSRenderer({"enabled": True})
    assert r.surface_elevation_ft(LAT0, LON0) is None
    assert r.floor_camera_alt(-500.0, LAT0, LON0) == -500.0
    assert r.height_tag is False
