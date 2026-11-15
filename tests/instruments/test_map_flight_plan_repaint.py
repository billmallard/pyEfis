#  SPDX-License-Identifier: GPL-2.0-or-later
"""The map's flight_plan layer asks for a frame only when what it draws
changed, and asks the map's frame clock, not ``update()``.

The fix-gateway flight-plan engine rewrites all of its outputs every
guidance cycle (25 keys, 5 Hz by default). The layer used to wire each of
those writes straight to ``owner.update``, so the whole map -- terrain
blit, airways, fixes, every enabled layer -- repainted once per engine
cycle whether or not the route, the active leg or anything else on the map
had moved, bypassing the frame clock that exists to stop exactly that
(``MovingMap._frame_tick``). On the Beelink bench a map repaint with the
usual layers on held the GUI thread a median 36 ms.

These tests use a moving map on its own: there is no ``flight_plan``
instrument in the process, and the layer must not need one.
"""

import inspect
import re

import pytest
from PyQt6.QtWidgets import QWidget

from pyefis.flightplan import fixbridge
from pyefis.flightplan import model as fp_model
from pyefis.instruments import map as moving_map
from pyefis.instruments.map.layers import flight_plan as fp_layer
from tests.instruments import test_map_flight_plan_layer as base

# Engine outputs that are numbers on a data field, not anything the layer
# draws: they change every cycle in flight.
READOUTS = {"WPDIS": 11.5, "WPETE": 420, "FPLREMDIS": 96.0, "FPLREMETE": 3200,
            "FPLSEGREM": 31.0, "FPLXTK": 0.2, "FPLCDI": 0.1}


def _plan(n=4):
    return fp_model.FlightPlan(name="TEST", waypoints=[
        fp_model.Waypoint(id=f"WP{i:02d}", type="fix",
                          lat=34.0 + i * 0.1, lon=-119.0 - i * 0.1)
        for i in range(n)])


def _flying_map(fix, qtbot):
    """A MovingMap whose bus holds a 4-waypoint route on its second leg."""
    base._publish_plan(fix, 4)
    fix.db.set_value("FPLSTATE", 1)
    fix.db.set_value("FPLACTLEG", 2)
    w = moving_map.MovingMap(None)
    qtbot.addWidget(w)
    w.resize(300, 300)
    # Counted before the layers are built: a layer that connects a signal
    # to owner.update binds whatever update is at that moment.
    updates = []
    w.update = lambda *a: updates.append(1)
    w._build_layers()
    del updates[:]
    w._frame_dirty = False
    return w, updates


def _engine_cycle(fix, **changed):
    for key in fixbridge.ENGINE_OUTPUT_KEYS:
        fix.db.set_value(key, changed.get(key, fix.db.get_item(key).value))


def test_readout_writes_neither_repaint_nor_mark_a_frame(fix, qtbot):
    w, updates = _flying_map(fix, qtbot)

    for n in range(5):
        _engine_cycle(fix, **{k: v + n for k, v in READOUTS.items()})

    assert updates == []
    assert w._frame_dirty is False


def test_active_leg_change_marks_a_frame_without_calling_update(fix, qtbot):
    w, updates = _flying_map(fix, qtbot)

    _engine_cycle(fix, FPLACTLEG=3)

    assert updates == []
    assert w._frame_dirty is True


def test_the_frame_clock_paints_the_marked_frame(fix, qtbot):
    w, updates = _flying_map(fix, qtbot)
    w.show()
    qtbot.waitExposed(w)
    w._frame_tick()            # settle the pose key
    del updates[:]
    _engine_cycle(fix, FPLACTLEG=3)
    assert updates == []

    w._frame_tick()

    assert updates == [1]
    assert w._frame_dirty is False


def test_route_commit_marks_a_frame(fix, qtbot):
    w, updates = _flying_map(fix, qtbot)

    fixbridge.FixBridge(fix).publish(_plan(3))

    assert updates == []
    assert w._frame_dirty is True


def test_a_flag_on_a_drawn_key_marks_a_frame(fix, qtbot):
    """The active leg is drawn from FPLFRLAT only while it has not failed."""
    w, updates = _flying_map(fix, qtbot)

    fix.db.get_item("FPLFRLAT").fail = True
    _engine_cycle(fix)

    assert w._frame_dirty is True


def test_request_frame_marks_dirty_without_calling_update(fix, qtbot):
    w = moving_map.MovingMap(None)
    qtbot.addWidget(w)
    updates = []
    w.update = lambda *a: updates.append(1)
    w._frame_dirty = False

    w.request_frame()

    assert updates == []
    assert w._frame_dirty is True


class _PlainOwner(QWidget):
    """An owner with no frame clock of its own (the layer's unit-test
    stand-in, or any future host): the layer falls back to ``update()``."""

    perf = None

    def __init__(self):
        super().__init__()
        self.updates = 0

    def update(self, *args):
        self.updates += 1


def test_owner_without_a_frame_clock_is_updated_only_on_a_drawn_change(fix, qtbot):
    base._publish_plan(fix, 4)
    owner = _PlainOwner()
    qtbot.addWidget(owner)
    layer = fp_layer.FlightPlanLayer()
    layer.configure(owner)

    _engine_cycle(fix, **READOUTS)
    assert owner.updates == 0

    _engine_cycle(fix, FPLSTATE=1, FPLACTLEG=2)
    assert owner.updates >= 1


def test_every_engine_key_the_layer_reads_is_in_its_draw_signature():
    """A key the layer starts drawing from must join ``_DRAW_KEYS``, or a
    change of it would wait for the aircraft to move before it showed."""
    source = inspect.getsource(fp_layer)
    read = set(re.findall(r'"((?:FPL|WP|CDI|GPS)[A-Z]+)"', source))
    read &= set(fixbridge.ENGINE_OUTPUT_KEYS) | set(fixbridge.OPTIONAL_ENGINE_OUTPUT_KEYS)
    assert read, "the scan found no engine keys: the pattern no longer matches"
    assert read <= set(fp_layer._DRAW_KEYS)


@pytest.mark.parametrize("key", sorted(READOUTS))
def test_readout_keys_stay_out_of_the_draw_signature(key):
    assert key not in fp_layer._DRAW_KEYS
