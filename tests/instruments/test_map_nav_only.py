"""G12 (billmallard/pyEfis#135): ``map_style: nav_only`` -- terrain relief
off, water on its own switch, nav layers repainted for a black background.

Pins three things the parent issue closes on: (a) the layer set the preset
produces, (b) the nav-only palette values, as tables and as painted pixels,
and (c) that a screen with no ``map_style`` gets exactly the pre-G12 values.
"""
import numpy as np
import pytest
from PyQt6.QtCore import QPointF
from PyQt6.QtGui import QColor, QImage, QPainter

from pyefis.instruments import map as moving_map
from pyefis.instruments.map import layers as map_layers
from pyefis.instruments.map.layers.navaids import NavaidsLayer
from pyefis.instruments.map.layers.rivers import RiversLayer
from pyefis.instruments.map.layers.roads import RoadsLayer
from pyefis.instruments.map.layers.terrain import TerrainLayer


LAT0, LON0 = 34.5, -120.5

# The pre-G12 literals, copied from dev @ eed5e72 (map/__init__.py fillRect,
# layers/__init__.py RangeRingsLayer, airports.MAGENTA, navaids.BLUE /
# DARKBLUE / the airway pen, flight_plan.PAST, terrain.py's water fill,
# the road and river Prop defaults). Standard must keep every one.
PRE_G12 = {
    "background": (16, 24, 32, 255),
    "water": (60, 110, 160, 255),
    "range_ring": (255, 255, 255, 140),
    "range_ring_label": (255, 255, 255, 140),
    "airport": (197, 36, 125, 255),
    "navaid": (70, 110, 200, 255),
    "fix": (40, 60, 130, 255),
    "fix_width": 1.2,
    "airway": (90, 130, 210, 170),
    "route_past": (128, 128, 128, 255),
    "road_default": "#c0c0c0",
    "river_default": "#4a6d8c",
}

NAV_ONLY = {
    "background": (0, 0, 0, 255),
    "water": (24, 56, 104, 255),
    "range_ring": (120, 120, 120, 255),
    "range_ring_label": (170, 170, 170, 255),
    "airport": (255, 100, 190, 255),
    "navaid": (130, 175, 255, 255),
    "fix": (120, 160, 230, 255),
    "fix_width": 1.5,
    "airway": (100, 140, 220, 255),
    "route_past": (144, 144, 144, 255),
    "road_default": "#808080",
    "river_default": "#4088a8",
}


# --- helpers ---------------------------------------------------------------

class _CoastCache:
    """Fake TileCache: 500 m land north of *shore_lat*, sea level south."""

    def __init__(self, shore_lat):
        self.shore_lat = shore_lat

    def get(self, la, lo):
        n = 1201
        lats = la + 1.0 - np.arange(n, dtype=np.float32) / (n - 1)
        tile = np.where(lats > self.shore_lat, 500.0, 0.0)
        return np.repeat(tile[:, None], n, axis=1).astype(np.float32)


class _LakeDB:
    """Stub WaterDB: one square lake east of the window centre."""

    ready = True

    def __init__(self, lat0=LAT0, lon0=LON0):
        d, clon = 0.01, lon0 + 0.05
        self._poly = type("P", (), {})()
        self._poly.vertices = [(lat0 - d, clon - d), (lat0 - d, clon + d),
                               (lat0 + d, clon + d), (lat0 + d, clon - d)]
        self._poly.kind = "lake"

    def polygons_in_range(self, lat, lon, range_nm,
                          min_bbox_diag_deg=None, drop_ocean=False):
        yield self._poly


class _Owner:
    def __init__(self, **kw):
        self._alt_ft = 3000.0
        self.terrain_mode = "relief"
        for k, v in kw.items():
            setattr(self, k, v)

    def update(self):
        pass


def _terrain(style, cache=None, water=None, **kw):
    lay = TerrainLayer()
    owner = _Owner(map_style=style, **kw)
    lay.configure(owner)
    lay._cache = cache
    lay._water = water
    return lay


def _render(lay, range_nm=10.0):
    x = moving_map.MapTransform(LAT0, LON0, range_nm, 0.0, 400, 400, 0.5)
    key = lay._key(x)
    img, meta = lay._render((key, x.lat0, x.lon0, x.range_nm,
                             x.w, x.h, x.cy))
    return img, meta


def _rgba(img):
    img = img.convertToFormat(QImage.Format.Format_RGBA8888)
    buf = img.constBits()
    buf.setsize(img.sizeInBytes())
    return np.frombuffer(buf, np.uint8).reshape(
        img.height(), img.bytesPerLine() // 4, 4)[:, :img.width(), :].copy()


def _built_map(fix, qtbot, **opts):
    w = moving_map.MovingMap()
    qtbot.addWidget(w)
    for k, v in opts.items():
        setattr(w, k, v)
    w._build_layers()
    return w, {layer.id: layer for layer in w._layers}


def _canvas(colour=(0, 0, 0)):
    img = QImage(400, 400, QImage.Format.Format_RGB32)
    img.fill(QColor(*colour))
    return img


# --- (b)/(c) the palette tables ---------------------------------------------

def test_standard_palette_is_the_pre_g12_constants():
    assert map_layers.STANDARD_PALETTE == PRE_G12


def test_nav_only_palette_values():
    assert map_layers.NAV_ONLY_PALETTE == NAV_ONLY


def test_palette_tables_have_the_same_keys():
    """The hook for later layers (airspace, CAP-204): a key added to one
    table and not the other would KeyError under the other style."""
    assert set(map_layers.STANDARD_PALETTE) == set(map_layers.NAV_ONLY_PALETTE)


@pytest.mark.parametrize("style, want", [
    (None, "standard"), ("standard", "standard"), ("nav_only", "nav_only"),
    (" NAV_ONLY ", "nav_only"), ("navonly", "standard"), ("", "standard")])
def test_map_style_normalises_unknown_to_standard(style, want):
    owner = _Owner() if style is None else _Owner(map_style=style)
    assert map_layers.map_style(owner) == want


def test_widget_defaults_are_standard(fix, qtbot):
    w = moving_map.MovingMap()
    qtbot.addWidget(w)
    assert w.map_style == "standard"
    assert w.layer_water is True
    assert map_layers.palette(w) is map_layers.STANDARD_PALETTE
    assert w._transform().palette is map_layers.STANDARD_PALETTE


# --- (a) the layer set -------------------------------------------------------

def test_standard_layer_set_follows_layer_keys(fix, qtbot):
    _w, lay = _built_map(fix, qtbot)
    assert lay["terrain"].enabled and not lay["terrain"]._flat
    _w, lay = _built_map(fix, qtbot, layer_terrain=False, layer_water=True)
    assert not lay["terrain"].enabled          # layer_water unused here


def test_nav_only_layer_set(fix, qtbot):
    """Relief off even with layer_terrain True; the terrain layer becomes
    the flat water renderer; every nav layer on at its default."""
    _w, lay = _built_map(fix, qtbot, map_style="nav_only", layer_terrain=True)
    assert lay["terrain"]._flat
    assert lay["terrain"].enabled               # layer_water default on
    for lid in ("airports", "navaids", "flight_plan", "range_rings",
                "rivers", "roads"):
        assert lay[lid].enabled, lid
    assert not lay["fixes"].enabled and not lay["airways"].enabled  # own defaults


def test_nav_only_water_follows_its_own_key(fix, qtbot):
    _w, lay = _built_map(fix, qtbot, map_style="nav_only", layer_water=False)
    assert not lay["terrain"].enabled
    _w, lay = _built_map(fix, qtbot, map_style="nav_only", layer_water=True,
                         layer_terrain=False)
    assert lay["terrain"].enabled               # layer_terrain does not gate it


def test_nav_only_keeps_every_other_layer_key(fix, qtbot):
    _w, lay = _built_map(fix, qtbot, map_style="nav_only", layer_rivers=False,
                         layer_navaids=False, layer_fixes=True,
                         layer_airways=True)
    assert not lay["rivers"].enabled and not lay["navaids"].enabled
    assert lay["fixes"].enabled and lay["airways"].enabled


# --- terrain: flat water render ----------------------------------------------

def test_nav_only_render_has_no_relief():
    """Land is fully transparent, water is the flat nav fill -- no
    hypsometric colour, no hillshade."""
    img, _ = _render(_terrain("nav_only", cache=_CoastCache(LAT0)))
    px = _rgba(img)
    n = px.shape[0]
    land = px[: n // 2 - 4]
    sea = px[n // 2 + 4:]
    assert (land[..., 3] == 0).all()
    assert (sea == np.array(NAV_ONLY["water"], np.uint8)).all()


def test_nav_only_caution_mode_paints_no_tint():
    """terrain_mode is a relief option; under nav_only it changes nothing
    (ownship at 0 ft over 500 m land would be solid red in caution)."""
    a, _ = _render(_terrain("nav_only", cache=_CoastCache(LAT0)))
    lay = _terrain("nav_only", cache=_CoastCache(LAT0), terrain_mode="caution")
    lay._alt_ft = 0.0
    b, _ = _render(lay)
    assert (_rgba(a) == _rgba(b)).all()


def test_nav_only_coastline_matches_relief_coastline():
    """Same water sources as the relief render: the set of water pixels
    is identical, only the colours differ."""
    cache, lake = _CoastCache(LAT0), _LakeDB()
    std, _ = _render(_terrain("standard", cache=cache, water=lake))
    nav, _ = _render(_terrain("nav_only", cache=cache, water=lake))
    s, v = _rgba(std), _rgba(nav)
    std_water = (s[..., :3] == np.array(PRE_G12["water"][:3], np.uint8)).all(-1)
    nav_water = v[..., 3] == 255
    assert std_water.any()
    assert (std_water == nav_water).all()


def test_nav_only_draws_water_pack_with_no_terrain_pack():
    """Coastline without relief must not need a terrain pack."""
    lay = _terrain("nav_only", cache=None, water=_LakeDB())
    x = moving_map.MapTransform(LAT0, LON0, 10.0, 0.0, 400, 400, 0.5)
    assert lay._has_source()
    img, meta = _render(lay)
    px = _rgba(img)
    assert (px[..., 3] == 255).sum() > 100       # the lake
    assert (px[px[..., 3] == 255][:, :3] == NAV_ONLY["water"][:3]).all()
    # Standard with no tiles draws nothing at all, as before G12.
    std = _terrain("standard", cache=None, water=_LakeDB())
    assert not std._has_source() and std.is_settled(x)


def test_nav_only_with_no_sources_is_inert():
    lay = _terrain("nav_only", cache=None, water=None)
    assert not lay._has_source()


# --- painted pixels ------------------------------------------------------------

def _ring_pixel(pal):
    """Paint the range rings on black; return the pixel on the full-range
    ring due south of ownship (no label there)."""
    x = moving_map.MapTransform(LAT0, LON0, 10.0, 0.0, 400, 400, 0.5,
                                palette=pal)
    img = _canvas()
    p = QPainter(img)
    map_layers.RangeRingsLayer().paint(p, x)
    p.end()
    r = int(round(x.nm_to_px(x.range_nm * 0.5)))
    c = img.pixelColor(int(x.cx), int(x.cy) + r)
    return (c.red(), c.green(), c.blue())


def test_range_ring_colour_standard_and_nav_only(qapp):
    assert _ring_pixel(map_layers.STANDARD_PALETTE) == (140, 140, 140)
    assert _ring_pixel(map_layers.NAV_ONLY_PALETTE) == (120, 120, 120)


def _navaid_pixel(pal):
    """Paint one VOR on black and return its centre-dot colour."""
    lay = NavaidsLayer()
    x = moving_map.MapTransform(LAT0, LON0, 10.0, 0.0, 400, 400, 0.5,
                                palette=pal)
    lay._snapshot = lambda xform, max_range: [("SBA", "VORTAC", "114.9",
                                               LAT0, LON0)]
    img = _canvas()
    p = QPainter(img)
    lay.paint(p, x)
    p.end()
    c = img.pixelColor(int(x.cx), int(x.cy))
    return (c.red(), c.green(), c.blue())


def test_navaid_colour_standard_and_nav_only(qapp):
    assert _navaid_pixel(map_layers.STANDARD_PALETTE) == (70, 110, 200)
    assert _navaid_pixel(map_layers.NAV_ONLY_PALETTE) == (130, 175, 255)


def test_widget_background(fix, qtbot):
    for style, want in (("standard", (16, 24, 32)), ("nav_only", (0, 0, 0))):
        w = moving_map.MovingMap()
        qtbot.addWidget(w)
        w.resize(200, 200)
        w.map_style = style
        w.layer_range_rings = False
        img = w.grab().toImage()
        c = img.pixelColor(5, 190)
        assert (c.red(), c.green(), c.blue()) == want, style


@pytest.mark.parametrize("cls, opt, std, nav", [
    (RoadsLayer, "road_color", "#c0c0c0", "#808080"),
    (RiversLayer, "river_color", "#4a6d8c", "#4088a8")])
def test_line_layer_default_colour_swaps_but_explicit_wins(cls, opt, std, nav):
    for style, col, want in (("standard", std, std), ("nav_only", std, nav),
                             ("nav_only", "#ff0000", "#ff0000"),
                             ("standard", "#ff0000", "#ff0000")):
        lay = cls()
        lay.configure(_Owner(map_style=style, **{opt: col}))
        assert lay._color == want, (style, col)


def test_schema_exports_map_style_and_layer_water():
    """Lockstep with the configurator twin (makerplane-data schema.json)."""
    from pyefis.editor import schema as sch
    opts = sch.build_schema()["instruments"]["moving_map"]["options"]
    assert opts["map_style"]["default"] == "standard"
    assert opts["map_style"]["enum"] == ["standard", "nav_only"]
    assert opts["layer_water"]["default"] is True
