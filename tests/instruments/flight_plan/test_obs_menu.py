#  SPDX-License-Identifier: GPL-2.0-or-later
"""The FPL page's OBS key (OBS3, AER-6086), beside Suspend/Resume.

Pressing it outside OBS sends ``FPLCMD OBS <deg>`` seeded with the current
desired track (FPLCRS), so the needle does not move until the pilot turns
CRS; in OBS (FPLSTATE = 4) it reads "OBS Off" and sends ``OBS OFF``. A
refusal shows the engine's FPLMSG text. The OBS badge comes from FPLSTATE.
"""

import pytest

from pyefis.instruments import flight_plan

from .test_flight_plan import _define_all_fp1_keys, _menu_labels, _plan


@pytest.fixture
def page(fix, qtbot):
    _define_all_fp1_keys(fix)
    w = flight_plan.FlightPlan(None)
    qtbot.addWidget(w)
    w.resize(480, 320)
    w._plan = _plan(3)
    w._commit()
    fix.db.set_value("FPLSTATE", 1)
    fix.db.set_value("FPLACTLEG", 2)
    fix.db.set_value("FPLCRS", 269.6)
    w._sync_engine_from_bridge()
    return w


def _cmd(fix):
    text = fix.db.get_item("FPLCMD").value
    return int(text.split()[0]), text.split(None, 1)[1]


def test_menu_offers_obs_beside_suspend(page, monkeypatch):
    labels = _menu_labels(page, monkeypatch)
    assert labels.index("OBS") == labels.index("Suspend") + 1


def test_obs_enters_on_the_current_desired_track(page, fix):
    page._menu_obs()
    assert _cmd(fix)[1] == "OBS 270"
    assert page._menu_open is False


def test_obs_seed_wraps_north_to_zero(page, fix):
    fix.db.set_value("FPLCRS", 359.7)
    page._sync_engine_from_bridge()
    page._menu_obs()
    assert _cmd(fix)[1] == "OBS 0"


def test_in_obs_the_key_reads_obs_off_and_leaves_it(page, fix, monkeypatch):
    fix.db.set_value("FPLSTATE", 4)
    page._sync_engine_from_bridge()
    labels = _menu_labels(page, monkeypatch)
    assert "OBS Off" in labels and "OBS" not in labels
    page._menu_obs()
    assert _cmd(fix)[1] == "OBS OFF"


def test_a_refusal_shows_the_engine_text(page, fix, qtbot):
    page._menu_obs()
    seq, _ = _cmd(fix)
    fix.db.set_value("FPLMSG", "OBS NOT ON FAC")
    fix.db.set_value("FPLCMDACK", -seq)
    qtbot.waitUntil(lambda: page._message == "OBS NOT ON FAC", timeout=1000)


def test_an_accepted_obs_shows_no_message(page, fix, qtbot):
    page._message = ""
    page._menu_obs()
    seq, _ = _cmd(fix)
    fix.db.set_value("FPLCMDACK", seq)
    qtbot.wait(20)
    assert page._message == ""


@pytest.mark.parametrize("state,badge", [(0, ""), (1, "LEG"), (2, "DIRECT"),
                                         (3, "SUSP"), (4, "OBS")])
def test_obs_badge_from_fplstate_only(page, fix, state, badge):
    fix.db.set_value("FPLSTATE", state)
    page._sync_engine_from_bridge()
    assert page._state_badge() == badge
