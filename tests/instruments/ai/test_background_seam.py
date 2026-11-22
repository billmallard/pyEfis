"""CERT12b (AER-6080): the SVS reaches the attitude widget only through the
background-renderer seam (``background.py``; CERT12 brief R2b, U1, U2).

Before it, ``ai_widget.py`` imported the SVS renderer, the SVS camera and the
pose interpolator at module level (brief E1-E3), so every attitude indicator
loaded numpy and the overlay databases whether it drew terrain or not.
"""
import ast
import json
import os
import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from PyQt6.QtGui import QPainter, QImage

from pyefis.instruments import ai
from pyefis.instruments.ai import background, camera, projection

_ROOT = Path(__file__).resolve().parents[3]
_AI_DIR = _ROOT / "src" / "pyefis" / "instruments" / "ai"

# The brief's "not core" list for the ai package (section 3), plus the
# third-party footprint that arrives only with the SVS.
_SVS_MODULES = {f"pyefis.instruments.ai.{m}" for m in (
    "svs", "svs_gl", "camera", "pose", "road_ribbon",
    "airport_db", "highway_db", "obstacle_db", "water_db")}
_SVS_THIRD_PARTY = {"numpy", "sqlite3", "OpenGL"}


# --- The AI loads no SVS code without a renderer ---------------------------

_CHILD = """\
import json, sys
sys.path.insert(0, {root!r})
import tests.mock_db.client, tests.mock_db.scheduler
sys.modules["pyavtools.fix.client"] = tests.mock_db.client
sys.modules["pyavtools.scheduler"] = tests.mock_db.scheduler
import pyavtools.fix as fix
fix.initialize({{"main": {{"FixServer": "localhost", "FixPort": "3490"}}}})
for key in ("PITCH", "ROLL", "ALAT", "TAS"):
    fix.db.define_item(key, key, "float", -180, 180, "", 50000, "")
from PyQt6.QtWidgets import QApplication
app = QApplication([])
from pyefis.instruments.ai import AI

def loaded():
    return sorted(m for m in sys.modules
                  if m.startswith("pyefis.instruments.ai.")
                  or m.split(".")[0] in ("numpy", "sqlite3", "OpenGL"))

w = AI()
w.resize(400, 300)
w.show()
app.processEvents()
w._frame_tick()
w.repaint()
app.processEvents()
bare = loaded()
w.set_svs_config({{"enabled": False}})
app.processEvents()
print(json.dumps({{"bare": bare, "with_svs": loaded()}}))
"""


@pytest.fixture(scope="module")
def child_modules():
    env = dict(os.environ, PYTHONPATH=str(_ROOT / "src"),
               QT_QPA_PLATFORM="offscreen")
    result = subprocess.run(
        [sys.executable, "-c", _CHILD.format(root=str(_ROOT))],
        cwd=str(_ROOT), env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_ai_with_no_renderer_loads_no_svs_module(child_modules):
    """Built, shown, ticked and painted with no renderer: nothing from the
    SVS side is in sys.modules."""
    bare = set(child_modules["bare"])
    assert not bare & _SVS_MODULES
    assert not {m.split(".")[0] for m in bare} & _SVS_THIRD_PARTY


def test_plugging_the_svs_in_loads_it(child_modules):
    """The same probe sees the SVS once a screen asks for it, so the check
    above cannot pass by looking in the wrong place."""
    assert "pyefis.instruments.ai.svs" in child_modules["with_svs"]


def _imports(path):
    """Every module a file imports, at top level or inside a function."""
    names = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{a.name}" for a in node.names)
    return names


@pytest.mark.parametrize("name", ["ai_widget.py", "background.py",
                                  "projection.py"])
def test_core_side_of_the_seam_names_no_svs_module(name):
    """Static half: no literal import of SVS code from the AI or the seam,
    even one deferred into a function."""
    names = _imports(_AI_DIR / name)
    assert not names & _SVS_MODULES
    assert not {n.split(".")[0] for n in names} & _SVS_THIRD_PARTY


# --- The renderer gets a frame pose, not the widget ------------------------

class _Recorder:
    """A minimal renderer: the interface background.py documents, without
    a pose source."""
    enabled = True
    ready = True
    gl_failed = False
    drew_terrain = True

    def __init__(self):
        self.calls = []

    def consume_async_dirty(self):
        return False

    def paint_frame(self, *args, **kwargs):
        self.calls.append((args, kwargs))


def _reset(fix):
    for key in ("PITCH", "ROLL", "ALAT", "TAS", "LAT", "LONG"):
        item = fix.db.get_item(key)
        item.old = item.bad = item.fail = False


def _hosted(fix, qtbot, renderer):
    _reset(fix)
    widget = ai.AI()
    qtbot.addWidget(widget)
    widget.resize(400, 300)
    widget.set_background_renderer(renderer)
    widget.show()
    qtbot.waitExposed(widget)
    return widget


def _paint_item(widget):
    img = QImage(10, 10, QImage.Format.Format_RGB32)
    p = QPainter(img)
    widget._svs_item.paint(p, None)
    p.end()


def test_renderer_is_handed_a_frozen_pose_and_nothing_else(fix, qtbot):
    renderer = _Recorder()
    widget = _hosted(fix, qtbot, renderer)
    widget.horizon_position = 70
    widget._svs_lat, widget._svs_lon, widget._svs_alt = 39.2, -106.8, 9000.0
    widget._fpm_head, widget._magvar = 100.0, -8.0
    renderer.calls.clear()
    _paint_item(widget)

    (args, kwargs), = renderer.calls
    assert kwargs == {}
    painter, pose = args
    assert isinstance(painter, QPainter)
    assert isinstance(pose, background.FramePose)
    assert (pose.lat, pose.lon, pose.alt_ft) == (39.2, -106.8, 9000.0)
    assert pose.heading_true_deg == pytest.approx(108.0)    # HEAD - MAGVAR
    assert pose.roll_pivot_px == pose.lens_shift_px == pytest.approx(
        widget._horizon_offset_px())
    assert pose.roll_pivot_px != 0.0
    assert (pose.width, pose.height) == (widget.viewport().width(),
                                         widget.viewport().height())
    assert pose.position_valid is True
    with pytest.raises(FrozenInstanceError):
        pose.lat = 0.0


def test_pose_carries_position_validity(fix, qtbot):
    renderer = _Recorder()
    widget = _hosted(fix, qtbot, renderer)
    fix.db.get_item("LONG").bad = True
    renderer.calls.clear()
    _paint_item(widget)
    (args, _), = renderer.calls
    assert args[1].position_valid is False


def test_renderer_without_a_pose_source_leaves_position_raw(fix, qtbot):
    """No interpolator offered: the host keeps the raw FIX position and the
    frame clock still runs."""
    renderer = _Recorder()
    widget = _hosted(fix, qtbot, renderer)
    assert widget._pose is None
    fix.db.set_value("LAT", 12.5)
    widget._frame_tick()
    assert widget._svs_lat == 12.5


def test_the_svs_brings_its_own_pose_source_seeded_from_fix(fix, qtbot):
    from pyefis.instruments.ai.pose import PoseSource
    _reset(fix)
    fix.db.set_value("LAT", 34.4)
    fix.db.set_value("LONG", -119.8)
    widget = ai.AI()
    qtbot.addWidget(widget)
    widget.set_svs_config({"enabled": False})
    assert isinstance(widget._pose, PoseSource)
    lat, lon, _ = widget._pose.sample()
    assert (lat, lon) == pytest.approx((34.4, -119.8))


# --- U2: the horizontal projection lives in the core ----------------------

def test_camera_uses_the_core_projection():
    assert camera.terrain_horizontal_px is projection.terrain_horizontal_px
    assert camera.TERRAIN_HFOV_PITCH_DEG == projection.TERRAIN_HFOV_PITCH_DEG


def test_the_svs_factory_attaches_traffic_to_the_bus(fix, qtbot, monkeypatch):
    """SVSTFC1 traffic is attached by the SVS's own factory, not by the AI:
    set_svs_config still hands the renderer the FIX database."""
    from pyefis.instruments.ai import svs
    seen = []
    monkeypatch.setattr(svs.SVSRenderer, "attach_traffic",
                        lambda self, db: seen.append(db))
    widget = ai.AI()
    qtbot.addWidget(widget)
    widget.set_svs_config({"enabled": False})
    assert seen == [fix.db]
