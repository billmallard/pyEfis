"""SVSSHADE2 (AER-6401): one terrain shading rule for the SVS and the map.

Pins, without a GL context (CI has none):

- the shared numbers (thresholds, airport gate, hazard lighting floor) in
  closed form, and that every place that carries a default -- the SVS
  config, the map widget, both editor Props -- carries the same one;
- each band edge and the lighting floor in the shared numpy rule AND in the
  GLSL the SVS fragment shader actually compiles: terrain_band(),
  apt_collapsed() and hazard_light() are read out of the shader source and
  evaluated, so a mutation of the shader text breaks a test too;
- the map's caution render: band colours from the palette, magenta above
  ownship, the airport collapse, and relief elsewhere.

A real-GL check of the relief base runs where a context exists (the bench,
a sandbox Xvfb) and skips in CI.
"""
import re
from unittest import mock

import numpy as np
import pytest

from pyefis.instruments.ai import terrain_shading as ts
from pyefis.instruments.ai.svs import SVSRenderer
from pyefis.instruments.ai.svs_gl import _FRAG_BODY


# --------------------------------------------------------------- the numbers

def test_shared_numbers_in_closed_form():
    # Bill's call on AER-6140: the SVS numbers, in both views.
    assert ts.CLEARANCE_GREEN_FT == 1000.0
    assert ts.CLEARANCE_YELLOW_FT == 500.0
    assert ts.AIRPORT_PROXIMITY_NM == 5.0
    assert ts.AIRPORT_GATE_AGL_FT == 400.0
    assert ts.HAZARD_LIGHT_FLOOR == 0.7
    assert ts.DEFAULT_SHADING == "relief"


def test_relief_stops_are_the_maps_table_unchanged():
    # Candidate B's base IS the map's relief: moving the table into the
    # shared module must not change how the map looks (copied from dev @
    # de10421e, map/layers/terrain.py _STOPS).
    assert ts.HYPSO_STOPS == (
        (-1000, 60, 110, 160), (0, 92, 130, 82), (1000, 110, 145, 88),
        (2000, 150, 160, 95), (4000, 185, 160, 100), (7000, 170, 130, 90),
        (10000, 160, 120, 105), (14000, 235, 235, 235))


def test_svs_defaults_are_the_shared_numbers():
    r = SVSRenderer({"enabled": True})
    assert r.green_ft == ts.CLEARANCE_GREEN_FT
    assert r.yellow_ft == ts.CLEARANCE_YELLOW_FT
    assert r.airport_proximity_nm == ts.AIRPORT_PROXIMITY_NM
    assert r.airport_gate_agl_ft == ts.AIRPORT_GATE_AGL_FT
    assert r.terrain_shading == "relief"


def test_map_and_svs_threshold_defaults_are_equal(fix, qtbot):
    from pyefis.instruments import map as moving_map
    w = moving_map.MovingMap()
    qtbot.addWidget(w)
    r = SVSRenderer({"enabled": True})
    assert w.clearance_green_ft == r.green_ft
    assert w.clearance_yellow_ft == r.yellow_ft
    assert w.airport_proximity_nm == r.airport_proximity_nm
    assert w.airport_gate_agl_ft == r.airport_gate_agl_ft
    assert w.terrain_palette == "clearance"


def test_editor_prop_defaults_are_the_shared_numbers():
    # screens/ is core and may not import terrain_shading, so its Prop
    # defaults are literals; this keeps them from drifting.
    from pyefis.screens import screenbuilder_factory as f
    vvfr = {p.name: p for p in f.REGISTRY["virtual_vfr"].properties}
    mmap = {p.name: p for p in f.REGISTRY["moving_map"].properties}
    assert vvfr["svs_clearance_green_ft"].default == ts.CLEARANCE_GREEN_FT
    assert vvfr["svs_clearance_yellow_ft"].default == ts.CLEARANCE_YELLOW_FT
    assert mmap["clearance_green_ft"].default == ts.CLEARANCE_GREEN_FT
    assert mmap["clearance_yellow_ft"].default == ts.CLEARANCE_YELLOW_FT
    assert vvfr["svs_terrain_shading"].default == ts.DEFAULT_SHADING
    assert tuple(vvfr["svs_terrain_shading"].enum) == ts.SHADINGS
    assert vvfr["svs_palette"].enum == mmap["terrain_palette"].enum \
        == list(ts.PALETTES)


# ------------------------------------------------- the GLSL, read and evaluated

def _glsl_consts():
    src = ts.glsl_constants()
    out = {}
    for typ, name, val in re.findall(
            r"const\s+(int|float)\s+(\w+)\s*=\s*([-\d.e]+)\s*;", src):
        out[name] = int(val) if typ == "int" else float(val)
    return out


def _glsl_fn(name, env):
    """A Python callable for the GLSL function *name* in the fragment
    shader. The function must be written as `if (C) return E;` / `return
    E;` lines (the shader's comment says so); C and E are evaluated with
    && / || / ! translated."""
    m = re.search(r"\b(?:int|float|bool)\s+" + name +
                  r"\(([^)]*)\)\s*\{(.*?)\n\}", _FRAG_BODY, re.S)
    assert m, f"{name}() not found in the fragment shader"
    params = [p.split()[-1] for p in m.group(1).split(",") if p.strip()]
    steps = []
    for line in m.group(2).strip().splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        cm = re.fullmatch(r"if \((.*)\) return (.*);", line)
        rm = re.fullmatch(r"return (.*);", line)
        assert cm or rm, f"{name}(): unexpected line {line!r}"
        cond, expr = (cm.group(1), cm.group(2)) if cm else ("true", rm.group(1))
        steps.append((_py(cond), _py(expr)))

    def call(*args):
        scope = dict(env, **dict(zip(params, args)))
        for cond, expr in steps:
            if eval(cond, {"max": max, "min": min}, scope):
                return eval(expr, {"max": max, "min": min}, scope)
        raise AssertionError(f"{name}() fell off the end")
    return call


def _py(expr):
    expr = expr.replace("&&", " and ").replace("||", " or ")
    expr = re.sub(r"!(?!=)", " not ", expr)
    return expr.replace("true", "True").replace("false", "False")


def _shader(green=1000.0, yellow=500.0, near=0.0, gate=1.0e9):
    env = dict(_glsl_consts(), u_green_ft=green, u_yellow_ft=yellow,
               u_near_airport=near, u_apt_gate_ft=gate)
    env["apt_collapsed"] = _glsl_fn("apt_collapsed", env)
    return (_glsl_fn("terrain_band", env), _glsl_fn("hazard_light", env))


def test_shader_constants_come_from_the_shared_module():
    c = _glsl_consts()
    assert c["HAZARD_LIGHT_FLOOR"] == ts.HAZARD_LIGHT_FLOOR
    assert (c["BAND_NONE"], c["BAND_CAUTION"], c["BAND_WARNING"],
            c["BAND_CONFLICT"]) == (0, 1, 2, 3)
    rows = re.findall(r"vec4\(([-\d.]+), ([\d.]+), ([\d.]+), ([\d.]+)\)",
                      ts.glsl_constants())
    assert len(rows) == len(ts.HYPSO_STOPS) == c["HYPSO_N"]
    for (e, r, g, b), stop in zip(rows, ts.HYPSO_STOPS):
        assert float(e) == stop[0]
        assert [round(float(v) * 255) for v in (r, g, b)] == list(stop[1:])


# clearance ft -> band, with no airport nearby (defaults 1000 / 500).
_EDGES = [(-0.01, ts.BAND_CONFLICT), (0.0, ts.BAND_WARNING),
          (499.99, ts.BAND_WARNING), (500.0, ts.BAND_CAUTION),
          (999.99, ts.BAND_CAUTION), (1000.0, ts.BAND_NONE),
          (5000.0, ts.BAND_NONE)]


@pytest.mark.parametrize("clr,want", _EDGES)
def test_band_edges_numpy(clr, want):
    assert ts.band(clr, 3000.0) == want


@pytest.mark.parametrize("clr,want", _EDGES)
def test_band_edges_shader(clr, want):
    band, _ = _shader()
    assert band(clr, 3000.0) == want


# Near an airport with field elevation 9,070 ft: gate 9,470 ft MSL.
_GATE = 9070.0 + 400.0
_APT = [  # (clearance, elevation, band)
    (300.0, 9469.9, ts.BAND_NONE),      # runway environment: no band
    (300.0, 9470.0, ts.BAND_WARNING),   # at the gate: bands back
    (700.0, 9469.9, ts.BAND_NONE),
    (700.0, 9500.0, ts.BAND_CAUTION),
    (-1.0, 9000.0, ts.BAND_CONFLICT),   # conflict is never suppressed
]


@pytest.mark.parametrize("clr,elev,want", _APT)
def test_airport_collapse_numpy(clr, elev, want):
    assert ts.band(clr, elev, _GATE) == want


@pytest.mark.parametrize("clr,elev,want", _APT)
def test_airport_collapse_shader(clr, elev, want):
    band, _ = _shader(near=1.0, gate=_GATE)
    assert band(clr, elev) == want


def test_shader_and_numpy_agree_on_a_dense_sweep():
    rng = np.random.default_rng(6401)
    clr = rng.uniform(-200.0, 1500.0, 400)
    elev = rng.uniform(8000.0, 10000.0, 400)
    for near, gate in ((0.0, None), (1.0, _GATE)):
        band, _ = _shader(near=near, gate=_GATE if gate else 1.0e9)
        got = [band(c, e) for c, e in zip(clr, elev)]
        assert got == ts.band(clr, elev, gate).tolist()


@pytest.mark.parametrize("band,lit,want", [
    (ts.BAND_CAUTION, 0.35, 0.7), (ts.BAND_WARNING, 0.5, 0.7),
    (ts.BAND_CONFLICT, 0.69, 0.7), (ts.BAND_CAUTION, 0.9, 0.9),
    (ts.BAND_NONE, 0.35, 0.35), (ts.BAND_NONE, 0.9, 0.9)])
def test_hazard_lighting_floor(band, lit, want):
    _, light = _shader()
    assert light(band, lit) == pytest.approx(want)
    assert float(ts.hazard_light(band, lit)) == pytest.approx(want)


def test_relief_mode_floors_only_hazard_land():
    # The floor applies in relief mode, to land, after the band pick; the
    # clearance mode keeps today's lighting untouched.
    assert re.search(r"if \(u_relief > 0\.5 && v_is_water < 0\.5\) \{\s*"
                     r"lit = hazard_light\(band, lit\);", _FRAG_BODY)
    assert "vec3 shaded = base * lit;" in _FRAG_BODY


def test_relief_base_paints_only_unbanded_land():
    body = _FRAG_BODY[_FRAG_BODY.index("void main()"):]
    order = [body.index(s) for s in (
        "base = COLOR_WATER;", "base = COLOR_CONFLICT;",
        "base = COLOR_WARNING;", "base = COLOR_CAUTION;",
        "base = hypso(elev_ft);", "base = COLOR_SAFE;")]
    assert order == sorted(order)


# ------------------------------------------------------------- GL uniforms

@pytest.mark.parametrize("mode,want", [("relief", 1.0), ("clearance", 0.0),
                                       ("Clearance", 0.0), ("nonsense", 1.0)])
def test_terrain_shading_reaches_the_relief_uniform(mode, want):
    from pyefis.instruments.ai.svs_gl import SVSGLRenderer
    r = SVSRenderer({"enabled": True, "terrain_shading": mode})
    assert SVSGLRenderer(r)._relief_uniform() == want


def test_relief_uniform_is_resolved_and_uploaded():
    import inspect
    from pyefis.instruments.ai import svs_gl
    src = inspect.getsource(svs_gl)
    assert '"u_relief"' in src[src.index("for name in (\"u_ac_alt_ft\","):]
    assert re.search(r'self\._u\["u_relief"\],\s*self\._relief_uniform\(\)',
                     src)
    assert re.search(r"uniform\s+float\s+u_relief\s*;", _FRAG_BODY)


def test_collapse_gate():
    assert ts.collapse_gate_ft(False, 9070.0) is None
    assert ts.collapse_gate_ft(True, 9070.0) == 9470.0
    assert ts.collapse_gate_ft(True, None) == ts.NO_FIELD_ELEV_GATE_FT


class _Apt:
    def __init__(self, lat, lon, elev):
        self.ref_lat, self.ref_lon, self.elev_ft = lat, lon, elev


class _AptDB:
    ready = True

    def __init__(self, airports):
        self.airports = airports
        self.calls = []

    def airports_in_range(self, lat, lon, nm):
        self.calls.append((lat, lon, nm))
        return iter(self.airports)


def test_nearest_field_takes_the_nearest_with_an_elevation():
    db = _AptDB([_Apt(37.95, -107.90, 9070.0), _Apt(37.90, -107.85, None),
                 _Apt(37.99, -107.99, 8000.0)])
    assert ts.nearest_field(db, 37.95, -107.91, 5.0) == (True, 9070.0)
    assert ts.nearest_field(_AptDB([]), 37.95, -107.91, 5.0) == (False, None)
    assert ts.nearest_field(db, 37.95, -107.91, 0.0) == (False, None)


def test_svs_near_airport_uses_the_shared_rule():
    r = SVSRenderer({"enabled": True})
    r.airport_db = _AptDB([_Apt(34.43, -119.84, 13.0)])
    assert r.near_airport(34.42, -119.85) is True
    assert r._near_airport_elev_ft == 13.0


# ------------------------------------------------------- the map's caution mode

class _FlatCache:
    def __init__(self, elev_m):
        self.elev_m = elev_m

    def get(self, la, lo):
        return np.full((1201, 1201), self.elev_m, np.float32)


ELEV_M = 1000.0
ELEV_FT = ELEV_M * 3.28084
FLAT_SHADE = 0.875      # the map hillshade on flat ground


def _map_px(clearance_ft, palette="clearance", apt_db=None, mode="caution"):
    from pyefis.instruments import map as moving_map
    from pyefis.instruments.map.layers.terrain import TerrainLayer
    lay = TerrainLayer()
    lay._cache = _FlatCache(ELEV_M)
    lay._mode = mode

    class Owner:
        _alt_ft = ELEV_FT + clearance_ft
        _lat, _lon = 37.95, -107.91
        terrain_palette = palette
        clearance_green_ft = ts.CLEARANCE_GREEN_FT
        clearance_yellow_ft = ts.CLEARANCE_YELLOW_FT
        airport_proximity_nm = ts.AIRPORT_PROXIMITY_NM
        airport_gate_agl_ft = ts.AIRPORT_GATE_AGL_FT
        terrain_caution_available = staticmethod(lambda: True)
    lay._owner = Owner
    lay._alt_ft = Owner._alt_ft
    lay._apt_db = apt_db
    lay._update_airport_gate()
    x = moving_map.MapTransform(37.95, -107.91, 10.0, 0.0, 200, 200, 0.5)
    key = lay._key(x)
    img, _meta = lay._render((key, x.lat0, x.lon0, x.range_nm, x.w, x.h,
                              x.cy))
    c = img.pixelColor(img.width() // 2, img.height() // 2)
    return (c.red(), c.green(), c.blue()), key


def _lit(rgb):
    return tuple(int(np.float32(v) * FLAT_SHADE) for v in rgb)


@pytest.mark.parametrize("clr,band", [(-50.0, 3), (300.0, 2), (700.0, 1)])
def test_map_caution_paints_the_palette_bands(clr, band):
    px, _ = _map_px(clr)
    assert px == _lit(ts.PALETTES["clearance"][band])


def test_map_caution_never_bands_water():
    # Flat 0 m terrain samples as water: water is not a terrain hazard
    # surface, so it keeps the water colour inside the warning band.
    from pyefis.instruments import map as moving_map
    from pyefis.instruments.map.layers.terrain import TerrainLayer
    lay = TerrainLayer()
    lay._cache = _FlatCache(0.0)
    lay._mode = "caution"

    class Owner:
        _alt_ft = 300.0
        _lat, _lon = 34.0, -120.0
        terrain_caution_available = staticmethod(lambda: True)
    lay._owner = Owner
    lay._alt_ft = Owner._alt_ft
    x = moving_map.MapTransform(34.0, -120.0, 10.0, 0.0, 200, 200, 0.5)
    key = lay._key(x)
    img, _ = lay._render((key, x.lat0, x.lon0, x.range_nm, x.w, x.h, x.cy))
    c = img.pixelColor(100, 100)
    assert (c.red(), c.green(), c.blue()) == (60, 110, 160)


def test_map_caution_paints_relief_where_clear():
    px, _ = _map_px(1500.0)
    r, g, b = ts.hypso_rgb(np.array([ELEV_FT]))
    assert px == _lit((r[0], g[0], b[0]))


def test_map_band_edges_match_the_svs():
    # Today's map started red at 100 ft; the shared rule starts it at 500.
    assert _map_px(499.0)[0] == _lit(ts.PALETTES["clearance"][2])
    assert _map_px(501.0)[0] == _lit(ts.PALETTES["clearance"][1])
    assert _map_px(999.0)[0] == _lit(ts.PALETTES["clearance"][1])


@pytest.mark.parametrize("name", ["subdued", "high_contrast"])
def test_map_caution_follows_the_palette(name):
    assert _map_px(700.0, palette=name)[0] == \
        _lit(ts.PALETTES[name][1])


def test_map_airport_collapse():
    # Field 100 ft below the flat terrain: the terrain is inside the gate.
    db = _AptDB([_Apt(37.95, -107.90, ELEV_FT - 100.0)])
    px, key = _map_px(300.0, apt_db=db)
    r, g, b = ts.hypso_rgb(np.array([ELEV_FT]))
    assert px == _lit((r[0], g[0], b[0]))
    assert key[-1] == pytest.approx(ELEV_FT + 300.0)
    # Conflict is never suppressed.
    assert _map_px(-50.0, apt_db=db)[0] == \
        _lit(ts.PALETTES["clearance"][3])
    # Terrain above the gate keeps its band.
    db_low = _AptDB([_Apt(37.95, -107.90, ELEV_FT - 500.0)])
    assert _map_px(300.0, apt_db=db_low)[0] == \
        _lit(ts.PALETTES["clearance"][2])


def test_map_relief_mode_has_no_bands_and_no_gate():
    px, key = _map_px(-50.0, mode="relief",
                      apt_db=_AptDB([_Apt(37.95, -107.90, 0.0)]))
    r, g, b = ts.hypso_rgb(np.array([ELEV_FT]))
    assert px == _lit((r[0], g[0], b[0]))
    assert key[-1] is None


def test_map_gate_is_recomputed_only_on_a_new_cell():
    from pyefis.instruments.map.layers.terrain import TerrainLayer
    lay = TerrainLayer()
    db = _AptDB([_Apt(37.95, -107.90, 9070.0)])
    lay._apt_db = db

    class Owner:
        _lat, _lon = 37.95, -107.91
    lay._owner = Owner
    lay._update_airport_gate()
    lay._update_airport_gate()
    assert len(db.calls) == 1
    assert lay._apt_gate == 9470.0
    Owner._lat = 37.97
    lay._update_airport_gate()
    assert len(db.calls) == 2


# ----------------------------------------------------- real GL, where it exists

def _gl_centre_px(tmp_path, alt_ft, **cfg):
    from PyQt6.QtGui import QImage, QPainter
    from tests.instruments.ai.test_svs import _make_tile_dir
    root = _make_tile_dir(tmp_path, 32, -97, elevation=500)
    r = SVSRenderer(dict({
        "enabled": True, "tile_path": str(root), "renderer": "opengl",
        "range_nm": 30, "auto_range": False, "terrain_texture": 0.0,
        "terrain_grid": 0.0, "haze": False}, **cfg))
    img = QImage(400, 300, QImage.Format.Format_RGB32)
    img.fill(0x000000)
    painter = QPainter(img)
    try:
        r.draw(painter, 400, 300, 32.5, -96.5, alt_ft,
               -10.0, 0.0, 0.0, 12.0)
    finally:
        painter.end()
    if r.gl_failed or r._gl_draw_failures or r._gl_renderer is None:
        pytest.skip("no GL context in this environment")
    return img.pixelColor(200, 280).getRgb()[:3]


def test_gl_relief_base_and_bands(tmp_path):
    """Real GL: flat 500 m (1,640 ft) terrain. In relief mode, clear ground
    is the hypsometric colour under the flat-ground light, and the caution
    band is the palette's caution under the same light (above the floor)."""
    lit = 0.35 + 0.65 * float(np.dot([0, 0, 1],
                                     np.array([-1, 1, 2]) / np.sqrt(6)))
    elev_ft = 500.0 * 3.28084
    clear = _gl_centre_px(tmp_path, elev_ft + 3000.0)
    r, g, b = ts.hypso_rgb(np.array([elev_ft]))
    want = [v[0] / 255.0 * lit * 255.0 for v in (r, g, b)]
    assert clear == pytest.approx(want, abs=2)
    caution = _gl_centre_px(tmp_path, elev_ft + 760.0)
    want = [v * lit for v in ts.PALETTES["clearance"][1]]
    assert caution == pytest.approx(want, abs=2)
    legacy = _gl_centre_px(tmp_path, elev_ft + 3000.0,
                           terrain_shading="clearance",
                           safe_gradient=False)
    want = [v * lit for v in ts.PALETTES["clearance"][0]]
    assert legacy == pytest.approx(want, abs=2)
