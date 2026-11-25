"""SVSSHADE2 (AER-6401): the new terrain-shading options survive the real
screen-config path, as YAML would deliver them (quoted scalars included).

- ``svs_terrain_shading`` on a virtual_vfr: build_virtual_vfr strips the
  prefix into the SVS config, apply_options then runs over the same options
  (it setattrs them raw on the AI widget), and the renderer the widget hosts
  must still hold the value -- and hand it to the shader's u_relief.
- the map's ``terrain_palette`` / ``clearance_*_ft`` through apply_options,
  coerced to the default's type, reaching the terrain layer's render.
"""
import pytest

from pyefis.instruments.ai import terrain_shading as ts
from pyefis.screens import screenbuilder_factory, screenbuilder_options


class _Screen:
    def __init__(self, inst):
        self.instruments = [inst]
        self.encoder_list = []


@pytest.mark.parametrize("value,want,relief", [
    ("clearance", "clearance", 0.0), ("relief", "relief", 1.0),
    (None, "relief", 1.0)])
def test_svs_terrain_shading_round_trip(fix, qtbot, tmp_path, value, want,
                                        relief):
    from PyQt6.QtWidgets import QWidget
    from pyefis.instruments.ai.svs_gl import SVSGLRenderer
    parent = QWidget()
    qtbot.addWidget(parent)
    opts = {"svs_enabled": True, "svs_tile_path": str(tmp_path)}
    if value is not None:
        opts["svs_terrain_shading"] = value
    config = {"type": "virtual_vfr", "options": opts}
    widget = screenbuilder_factory.build_virtual_vfr(parent, config)
    screenbuilder_options.apply_options(_Screen(widget), 0, config)
    r = widget._svs_renderer
    assert r.terrain_shading == want
    assert SVSGLRenderer(r)._relief_uniform() == relief


def test_map_shading_options_round_trip(fix, qtbot):
    from pyefis.instruments import map as moving_map
    w = moving_map.MovingMap()
    qtbot.addWidget(w)
    config = {"type": "moving_map", "options": {
        "terrain_mode": "caution", "terrain_palette": "high_contrast",
        "clearance_green_ft": "1200", "clearance_yellow_ft": 600}}
    screenbuilder_options.apply_options(_Screen(w), 0, config)
    assert w.terrain_palette == "high_contrast"
    assert w.clearance_green_ft == 1200.0
    assert type(w.clearance_green_ft) is float
    assert w.clearance_yellow_ft == 600.0
    w._build_layers()
    terrain = next(lay for lay in w._layers if lay.id == "terrain")
    assert terrain._mode == "caution"
    # The layer reads the widget's values at render time.
    assert ts.palette_rgb(terrain._owner.terrain_palette) == \
        ts.PALETTES["high_contrast"]
    assert terrain._owner.clearance_green_ft == 1200.0
