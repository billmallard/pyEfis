#  Copyright (c) 2026 Bill Mallard
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.

"""BACKLOG BOOT1: pyEfis boots to Data Status on the ground and straight to
the flight screen when moving. Data Status boots only when IAS is valid and
below ``IAS.Vgnd``; every failure path -- IAS fast, bad, failed, old, never
reported, the key or the Vgnd aux missing, GPS moving -- boots the flight
screen. While the boot Data Status shows, the aircraft moving switches to the
flight screen without a touch."""

import logging
import sys
import types

import pytest
from PyQt6.QtWidgets import QApplication, QWidget

import pyefis.gui as gui
import pyefis.hmi as hmi

VGND = 40.0


@pytest.fixture
def app(qtbot):
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def reset_gui_state(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("MAKERPLANE_ACK_LOG",
                       str(tmp_path / "acknowledgments.jsonl"))
    gui.screens.clear()
    gui.log = logging.getLogger("tests.pyefis.ground_boot")
    hmi.initialize({})
    yield
    for screen in gui.screens:
        if screen.object is not None:
            try:
                screen.object.close()
            except RuntimeError:
                pass
    gui.screens.clear()


class FakeClock:
    """Drives _boot_on_ground's wait without real sleeping."""

    def __init__(self):
        self.t = 0.0
        self.sleeps = 0
        self.on_sleep = None

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.sleeps += 1
        self.t += s
        if self.on_sleep:
            self.on_sleep(self.t)


def _ias(fix, value, old=False, bad=False, fail=False, vgnd=VGND,
         aux="Min,Max,Vs,Vgnd"):
    fix.db.define_item("IAS", "Indicated Airspeed", "float", 0, 2000.0,
                       "knots", 50000, aux)
    item = fix.db.get_item("IAS")
    if value is not None:
        fix.db.set_value("IAS", value)
        item.old, item.bad, item.fail = old, bad, fail
    if vgnd is not None and "Vgnd" in aux:
        item.set_aux_value("Vgnd", vgnd)
    return item


def _gs(fix, value, valid=True):
    item = fix.db.get_item("GS")
    fix.db.set_value("GS", value)
    item.old = False
    item.bad = item.fail = not valid
    return item


def _boot(clock=None):
    clock = clock or FakeClock()
    return gui._boot_on_ground(clock=clock, sleep=clock.sleep), clock


# --- the boot decision -----------------------------------------------------

def test_valid_and_slow_boots_data_status(fix):
    _ias(fix, 0.0)
    _gs(fix, 0.0)
    on_ground, clock = _boot()
    assert on_ground is True
    # Decided within the settle time, not the full wait.
    assert clock.t < gui.BOOT_GROUND_WAIT_S


def test_valid_and_fast_boots_flight_without_waiting(fix):
    _ias(fix, 85.0)
    _gs(fix, 0.0)
    on_ground, clock = _boot()
    assert on_ground is False
    assert clock.sleeps == 0


def test_ias_exactly_vgnd_is_moving(fix):
    _ias(fix, VGND)
    _gs(fix, 0.0)
    assert _boot()[0] is False


@pytest.mark.parametrize("flag", ["bad", "fail", "old"])
def test_flagged_ias_boots_flight(fix, flag):
    _ias(fix, 0.0, **{flag: True})
    _gs(fix, 0.0)
    on_ground, clock = _boot()
    assert on_ground is False
    assert clock.t >= gui.BOOT_GROUND_WAIT_S


def test_ias_never_reported_boots_flight(fix):
    # Defined but never read: define_item leaves it bad and failed.
    _ias(fix, None)
    _gs(fix, 0.0)
    on_ground, clock = _boot()
    assert on_ground is False
    assert clock.t >= gui.BOOT_GROUND_WAIT_S


def test_ias_key_absent_boots_flight(monkeypatch):
    class NoIasDb:
        def get_item(self, key, create=False, wait=True):
            raise KeyError(key)
    monkeypatch.setattr(gui.fix, "db", NoIasDb(), raising=False)
    on_ground, clock = _boot()
    assert on_ground is False
    assert clock.sleeps == 0


def test_vgnd_aux_not_defined_boots_flight(fix):
    _ias(fix, 0.0, aux="Min,Max,Vs")
    _gs(fix, 0.0)
    on_ground, clock = _boot()
    assert on_ground is False
    assert clock.sleeps == 0


def test_vgnd_never_set_boots_flight(fix):
    _ias(fix, 0.0, vgnd=None)
    _gs(fix, 0.0)
    on_ground, clock = _boot()
    assert on_ground is False
    assert clock.t >= gui.BOOT_GROUND_WAIT_S


def test_gps_moving_with_ias_low_boots_flight(fix):
    # A blocked pitot in flight reads slow; valid GPS groundspeed overrides.
    _ias(fix, 0.0)
    _gs(fix, 95.0)
    assert _boot()[0] is False


def test_gps_moving_with_ias_flagged_boots_flight_at_once(fix):
    _ias(fix, 0.0, fail=True)
    _gs(fix, 95.0)
    on_ground, clock = _boot()
    assert on_ground is False
    assert clock.sleeps == 0


def test_invalid_gps_does_not_block_ground_boot(fix):
    # Indoors or before a fix the GPS is flagged; it must not keep the
    # pilot off the data screen.
    _ias(fix, 0.0)
    _gs(fix, 95.0, valid=False)
    assert _boot()[0] is True


def test_taxi_groundspeed_still_boots_data_status(fix):
    _ias(fix, 12.0)
    _gs(fix, 15.0)
    assert _boot()[0] is True


def test_gps_moving_arriving_during_settle_boots_flight(fix):
    _ias(fix, 0.0)
    _gs(fix, 0.0, valid=False)
    clock = FakeClock()
    clock.on_sleep = lambda t: _gs(fix, 95.0)
    assert _boot(clock)[0] is False


def test_ias_arriving_late_but_within_wait_boots_data_status(fix):
    ias = _ias(fix, None)
    _gs(fix, 0.0)
    clock = FakeClock()

    def arrive(t):
        if t >= 1.0:
            fix.db.set_value("IAS", 0.0)
            ias.bad = ias.fail = False
    clock.on_sleep = arrive
    assert _boot(clock)[0] is True


def test_exception_boots_flight(monkeypatch):
    def broken(db):
        raise ValueError("boom")
    monkeypatch.setattr(gui, "_ground_state", broken)
    assert _boot()[0] is False


# --- through gui.initialize --------------------------------------------------

def _screen_module(name):
    module = types.ModuleType(name)

    class FakeScreen(QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)

    module.Screen = FakeScreen
    sys.modules[name] = module
    return module


def _config():
    _screen_module("tests.fake_ground_boot_pfd")
    _screen_module("tests.fake_ground_boot_ds")
    return {
        "main": {"screenWidth": 320, "screenHeight": 240,
                 "screenColor": "#000000", "defaultScreen": "PFD",
                 "screenFullSize": False},
        "screens": {
            "PFD": {"module": "tests.fake_ground_boot_pfd"},
            "DataStatus": {
                "module": "tests.fake_ground_boot_ds",
                "instruments": [{"type": "data_status", "options": {}}],
            },
        },
    }


def _running(window):
    return gui.screens[window.running_screen].name


@pytest.fixture
def fast_wait(monkeypatch):
    monkeypatch.setattr(gui, "BOOT_GROUND_WAIT_S", 0.0)
    monkeypatch.setattr(gui, "BOOT_GROUND_SETTLE_S", 0.0)


def _booted_line(caplog):
    # bench-deploy.sh reports the booted screen from the last such line.
    lines = [r.getMessage() for r in caplog.records
             if r.getMessage().startswith("data-status: booting ")]
    return lines[-1].split()[2]


def test_initialize_on_ground_boots_data_status(app, fix, fast_wait, caplog):
    caplog.set_level(logging.INFO)
    _ias(fix, 0.0)
    _gs(fix, 0.0)
    cfg = _config()
    gui.initialize(cfg, "/config", {"includes": {}})
    assert _running(gui.mainWindow) == "DataStatus"
    assert _booted_line(caplog) == "DataStatus"
    # Continue goes to the configured flight screen.
    assert cfg["screens"]["DataStatus"]["instruments"][0]["options"][
        "continue_screen"] == "PFD"
    # The startup notice draws over whichever screen booted.
    assert gui.mainWindow.startupNotice is not None
    assert gui.mainWindow.groundBootWatch is not None


def test_initialize_moving_boots_flight(app, fix, fast_wait, caplog):
    caplog.set_level(logging.INFO)
    _ias(fix, 110.0)
    _gs(fix, 105.0)
    gui.initialize(_config(), "/config", {"includes": {}})
    assert _running(gui.mainWindow) == "PFD"
    assert _booted_line(caplog) == "PFD"
    assert gui.mainWindow.groundBootWatch is None


def test_ias_crossing_vgnd_on_data_status_switches_to_flight(
        app, fix, fast_wait, qtbot):
    _ias(fix, 0.0)
    _gs(fix, 0.0)
    gui.initialize(_config(), "/config", {"includes": {}})
    assert _running(gui.mainWindow) == "DataStatus"
    fix.db.set_value("IAS", 25.0)          # taxi: stays
    qtbot.wait(10)
    assert _running(gui.mainWindow) == "DataStatus"
    fix.db.set_value("IAS", 45.0)          # takeoff roll: switches
    qtbot.waitUntil(lambda: _running(gui.mainWindow) == "PFD", timeout=1000)
    assert gui.mainWindow.groundBootWatch.active is False


def test_gps_moving_on_data_status_switches_to_flight(
        app, fix, fast_wait, qtbot):
    _ias(fix, 0.0)
    gs = _gs(fix, 0.0)
    gui.initialize(_config(), "/config", {"includes": {}})
    assert _running(gui.mainWindow) == "DataStatus"
    fix.db.set_value("GS", 60.0)
    qtbot.waitUntil(lambda: _running(gui.mainWindow) == "PFD", timeout=1000)


def test_ias_failing_on_data_status_does_not_leave_it(
        app, fix, fast_wait, qtbot):
    ias = _ias(fix, 0.0)
    _gs(fix, 0.0)
    gui.initialize(_config(), "/config", {"includes": {}})
    ias.fail = True
    qtbot.wait(10)
    # No timeout on the ground: it stays until Continue.
    assert _running(gui.mainWindow) == "DataStatus"


def test_watch_ends_once_data_status_is_left(app, fix, fast_wait, qtbot):
    _ias(fix, 0.0)
    _gs(fix, 0.0)
    gui.initialize(_config(), "/config", {"includes": {}})
    gui.mainWindow.showScreen("PFD")       # the pilot pressed Continue
    fix.db.set_value("IAS", 10.0)
    qtbot.wait(10)
    watch = gui.mainWindow.groundBootWatch
    assert watch.active is False
    # Opening data status later from the annunciation, in flight, is not
    # cut short by the boot watch.
    gui.mainWindow.showScreen("DataStatus")
    fix.db.set_value("IAS", 110.0)
    qtbot.wait(10)
    assert _running(gui.mainWindow) == "DataStatus"


def test_initialize_shows_the_link_monitor_cue_over_the_flight_screen(
        app, fix, fast_wait, monkeypatch):
    # AER-5983: main started the watchdog and it is off; the cue goes over
    # whichever screen boots, on top of every other child.
    from pyefis import fix_watchdog
    monkeypatch.setattr(fix_watchdog, "off_reason", fix_watchdog.OFF_NO_PING_KEY)
    _ias(fix, 110.0)
    _gs(fix, 105.0)
    gui.initialize(_config(), "/config", {"includes": {}})
    cue = gui.mainWindow.linkMonitorCue
    assert cue is not None and cue.isVisible()
    assert cue.parentWidget() is gui.mainWindow
    assert gui.mainWindow.children()[-1] is cue


def test_initialize_with_the_watchdog_running_shows_no_cue(app, fix, fast_wait, monkeypatch):
    from pyefis import fix_watchdog
    monkeypatch.setattr(fix_watchdog, "off_reason", None)
    _ias(fix, 110.0)
    _gs(fix, 105.0)
    gui.initialize(_config(), "/config", {"includes": {}})
    assert gui.mainWindow.linkMonitorCue is None
