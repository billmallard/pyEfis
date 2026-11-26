#  SPDX-License-Identifier: GPL-2.0-or-later
"""A refused Activate says why (G97, AER-6536, billmallard/pyEfis#555).

``refusal.py`` had plain words for the engine's ACT refusals and for the
notices an accepted commit writes when it drops the active leg, but the FPL
page sent Activate Leg, Activate (to entry) and the far-fix Yes with no
acknowledgement callback, and read no notice after ``FPLLDSEQ``: the pilot
saw nothing. Only the PPOS hold's ACT showed its refusal. Now every ACT the
page sends shows the engine's reason in plain words, and a dropped active
leg is toasted.

Route and positions as in ``test_activate_leg_far_fix``.
"""

import pytest

from pyefis.flightplan import fixbridge
from tests.instruments.flight_plan.test_activate_leg_far_fix import (
    NEAR, _activate_sanfi_from_row, _at, _define, page)  # noqa: F401 (fixture)


@pytest.fixture()
def acks(page, monkeypatch):
    """Every ``on_ack`` the page passes with a command, by verb."""
    got = []

    def command(verb, arg=None, on_ack=None):
        page.sent.append((verb, arg))
        got.append((verb, on_ack))
    monkeypatch.setattr(page._bridge, "command", command)
    return got


def _refuse_last(page, acks, msg):
    verb, on_ack = acks[-1]
    assert verb == "ACT" and on_ack is not None
    on_ack(9, False, msg)


def test_activate_leg_refusal_is_shown(page, acks, fix):
    _at(fix, *NEAR)
    page._row_menu_index = 3
    page._row_menu_activate_leg()
    assert page.sent == [("ACT", 4)]
    _refuse_last(page, acks, "ACT N/A TURNED")
    assert page._message == "ALREADY TURNED TOWARD FIX: USE DIRECT-TO"


def test_far_fix_yes_refusal_is_shown(page, acks):
    _activate_sanfi_from_row(page)
    page._act_confirm_yes()
    assert page.sent == [("ACT", 3)]
    _refuse_last(page, acks, "ACT N/A TOO CLOSE")
    assert page._message == "TOO CLOSE FOR CODED TURN: USE DIRECT-TO"


def test_activate_to_entry_refusal_is_shown(page, acks, fix):
    # The approach segment's "Activate (to entry)" with the aircraft near
    # enough that no question is asked.
    _at(fix, 34.2, -118.9)   # near KSMO, the from-fix for SANFI
    page._open_seg_menu(2)
    page._seg_menu_activate()
    assert page.sent == [("ACT", 3)]
    _refuse_last(page, acks, "NO POSITION")
    assert page._message == "NO GPS POSITION"


def test_show_fixes_activate_leg_refusal_is_shown(page, acks, fix):
    _at(fix, *NEAR)
    page._open_seg_fixes(2)
    page._open_seg_fix_menu(3)
    page._seg_fix_activate_leg()
    assert page.sent == [("ACT", 4)]
    _refuse_last(page, acks, "ACT N/A NO TRACK")
    assert page._message == "NO GPS TRACK FOR CODED TURN: USE DIRECT-TO"


def test_unknown_or_empty_reason_is_never_nothing(page, acks, fix):
    _at(fix, *NEAR)
    page._row_menu_index = 3
    page._row_menu_activate_leg()
    _refuse_last(page, acks, "")
    assert page._message == "LEG NOT ACTIVATED"
    _refuse_last(page, acks, "ACT N/A SOMETHING NEW")
    assert page._message == "ACT N/A SOMETHING NEW"


def test_an_accepted_act_shows_nothing(page, acks, fix):
    _at(fix, *NEAR)
    page._row_menu_index = 3
    page._row_menu_activate_leg()
    page._message = ""
    acks[-1][1](9, True, "")
    assert page._message == ""


# -- the active-leg notices an accepted commit writes (fix-gateway HOLDFIX0) --------

def _loaded(fix):
    _define(fix, "FPLLDSEQ", "int", int(fix.db.get_item("FPLSEQ").value))


@pytest.mark.parametrize("code, words", [
    ("ACTIVE LEG REMOVED", "ACTIVE WAYPOINT REMOVED: NO LEG ACTIVE"),
    ("ACTIVE LEG CHANGED", "ACTIVE LEG CHANGED: NO LEG ACTIVE"),
    ("ACTIVE LEG AMBIGUOUS", "ACTIVE LEG REPEATED IN PLAN: NO LEG ACTIVE"),
])
def test_active_leg_notice_after_an_accepted_commit_is_shown(page, fix, code, words):
    _loaded(fix)
    page._message = ""
    fix.db.set_value("FPLMSG", code)
    assert page._message == words
    assert not page._plan_refused()


def test_the_same_notice_twice_is_shown_twice(page, fix):
    _loaded(fix)
    fix.db.set_value("FPLMSG", "ACTIVE LEG REMOVED")
    page._message = ""
    fix.db.set_value("FPLMSG", "ACTIVE LEG REMOVED")
    assert page._message == "ACTIVE WAYPOINT REMOVED: NO LEG ACTIVE"


def test_a_notice_on_a_route_not_yet_loaded_is_not_shown(page, fix):
    # FPLLDSEQ behind FPLSEQ: the route on the bus is not the one flown.
    _define(fix, "FPLLDSEQ", "int", int(fix.db.get_item("FPLSEQ").value) - 1)
    page._message = ""
    fix.db.set_value("FPLMSG", "ACTIVE LEG REMOVED")
    assert page._message == ""


def test_a_command_refusal_on_fplmsg_is_not_a_notice(page, fix):
    _loaded(fix)
    page._message = ""
    fix.db.set_value("FPLMSG", "ACT N/A TURNED")
    assert page._message == ""


def test_no_fplldseq_no_notice(page, fix):
    # A gateway from before FPLLDSEQ also predates the notices.
    assert "FPLLDSEQ" not in [k for k, _, _ in fixbridge.route_key_specs()]
    page._message = ""
    fix.db.set_value("FPLMSG", "ACTIVE LEG REMOVED")
    assert page._message == ""
