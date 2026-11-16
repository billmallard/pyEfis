#  SPDX-License-Identifier: GPL-2.0-or-later
"""Activate Leg asks first when the from-fix is far away (FPACT1, AER-5801).

Bill, 2026-11-15, on the Beelink: in a plan whose RNAV 24 approach into KHKY
follows KSMO, Activate Leg on SANFI made KSMO the from-fix, about 1,800 nm
behind the aircraft, and the page said nothing. The plan stays legal (an
approach at another airport is a diversion); the page now asks before it
sends ``ACT`` when the from-fix is more than 500 nm away. Ruled 2026-11-16:
ask first, no Direct To in the question.

Flat indices: KSBA 0, KSMO 1, SANFI 2, HKYFA 3, RW24 4. The aircraft sits
about 30 nm north-east of SANFI, so KSMO is about 1,800 nm away and SANFI
(the from-fix for the leg to HKYFA) is near.
"""

from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest

from pyefis.flightplan import fixbridge, geo
from pyefis.flightplan import model as fp_model
from pyefis.instruments import flight_plan

BEELINK = SimpleNamespace(screenWidth=1920, screenHeight=1080, screenDiagonalInches=21.5)

_BOUNDS = {"float": (-1e9, 1e9), "int": (-1_000_000, 1_000_000),
           "bool": (None, None), "str": (None, None)}
_ENGINE = {
    "FPLSTATE": "int", "FPLACTLEG": "int", "FPLPHASE": "str", "FPLAPR": "int",
    "FPLINTEG": "bool", "CDISCALE": "float", "FPLCRS": "float", "FPLXTK": "float",
    "FPLCDI": "float", "FPLTF": "int", "FPLFRLAT": "float", "FPLFRLON": "float",
    "WPNAME": "str", "WPLAT": "float", "WPLON": "float", "WPFROM": "str",
    "WPNEXT": "str", "WPDIS": "float", "WPETE": "int", "FPLREMDIS": "float",
    "FPLREMETE": "int", "FPLALERT": "bool", "GPSSRC": "int",
    "FPLACTSEG": "int", "FPLSEGREM": "float", "MAGVAR": "float",
}
_BLANK = {"int": 0, "float": 0.0, "bool": False, "str": ""}


def _define(fix, key, dtype, value):
    mn, mx = _BOUNDS[dtype]
    fix.db.define_item(key, key, dtype, mn, mx, "", 0, "")
    fix.db.set_value(key, value)
    item = fix.db.get_item(key)
    item.bad = item.fail = False


def _wp(ident, wtype, lat, lon):
    return fp_model.Waypoint(id=ident, type=wtype, lat=lat, lon=lon)


KSBA = _wp("KSBA", "airport", 34.42621, -119.84037)
KSMO = _wp("KSMO", "airport", 34.01583, -118.45130)
SANFI = _wp("SANFI", "fix", 35.65, -81.15)
HKYFA = _wp("HKYFA", "fix", 35.70, -81.30)
RW24 = _wp("RW24", "fix", 35.74, -81.38)
AIRCRAFT = (36.05, -80.80)
NEAR = (SANFI.lat + 40 / 60, SANFI.lon)   # 40 nm due north of SANFI


def _route():
    return fp_model.FlightPlan(name="TEST", segments=[
        fp_model.waypoint_segment(KSBA),
        fp_model.waypoint_segment(KSMO),
        fp_model.Segment(kind="approach", ident="R24", legs=[SANFI, HKYFA, RW24],
                         cycle="2611")])


def _at(fix, lat, lon):
    fix.db.set_value("LAT", lat)
    fix.db.set_value("LONG", lon)
    for key in ("LAT", "LONG"):
        item = fix.db.get_item(key)
        item.fail = item.old = item.bad = False


@pytest.fixture()
def page(fix, qtbot, monkeypatch):
    for key, dtype, blank in fixbridge.route_key_specs():
        _define(fix, key, dtype, blank)
    for key, dtype in _ENGINE.items():
        _define(fix, key, dtype, _BLANK[dtype])
    w = flight_plan.FlightPlan(None)
    qtbot.addWidget(w)
    w.parent = SimpleNamespace(parent=BEELINK)
    w.resize(649, 993)
    w._plan = _route()
    w._commit()
    sent = []
    monkeypatch.setattr(w._bridge, "command",
                        lambda verb, arg=None, on_ack=None: sent.append((verb, arg)))
    w.sent = sent
    _at(fix, *AIRCRAFT)
    return w


def _activate_sanfi_from_row(w):
    w._row_menu_index = 2
    w._row_menu_activate_leg()


def test_far_from_fix_sends_nothing_until_yes(page):
    _activate_sanfi_from_row(page)
    assert page.sent == []
    c = page._act_confirm
    assert c["slot"] == 3 and c["from_id"] == "KSMO"
    assert c["dist_nm"] == pytest.approx(
        geo.distance_nm(*AIRCRAFT, KSMO.lat, KSMO.lon))
    assert c["dist_nm"] > 1700
    page.grab()   # the question paints; still nothing sent
    assert page.sent == []

    page._act_confirm_yes()
    assert page.sent == [("ACT", 3)]
    assert page._act_confirm is None


def test_far_from_fix_no_sends_nothing_and_returns_to_list(page):
    _activate_sanfi_from_row(page)
    page._act_confirm_no()
    assert page.sent == []
    assert page._act_confirm is None
    page.grab()
    assert page._page == "fpl"
    assert page._list_view is not None   # the list takes presses again


def test_question_names_the_from_fix_and_the_distance(page, monkeypatch):
    shown = []
    real = page._paint_confirm
    monkeypatch.setattr(page, "_paint_confirm",
                        lambda p, w, h, text, *a: (shown.append(text), real(p, w, h, text, *a)))
    _activate_sanfi_from_row(page)
    page.grab()
    dist = geo.distance_nm(*AIRCRAFT, KSMO.lat, KSMO.lon)
    assert shown == [f"FROM KSMO {dist:.0f} NM\nACTIVATE LEG?"]


def _confirm_button(w, kind):
    """Centre of the Yes ("yes") or No ("no") button as painted."""
    w.grab()
    taps = list(zip(w._tap_targets, w._tap_kinds))
    if kind == "no":
        (x, y, tw, th, _), = [t for t, k in taps if k == "no"]
    else:
        (x, y, tw, th, _), = [t for t, k in taps if t[4] == w._act_confirm_yes]
    return QPoint(int(x + tw / 2), int(y + th / 2))


def test_yes_and_no_work_by_touch(page, qtbot):
    _activate_sanfi_from_row(page)
    QTest.mouseClick(page, Qt.MouseButton.LeftButton, pos=_confirm_button(page, "no"))
    assert page.sent == [] and page._act_confirm is None

    _activate_sanfi_from_row(page)
    QTest.mouseClick(page, Qt.MouseButton.LeftButton, pos=_confirm_button(page, "yes"))
    assert page.sent == [("ACT", 3)]


def test_tap_off_the_box_is_no(page, qtbot):
    _activate_sanfi_from_row(page)
    page.grab()
    QTest.mouseClick(page, Qt.MouseButton.LeftButton, pos=QPoint(5, 5))
    assert page.sent == [] and page._act_confirm is None


def test_encoder_back_is_no(page):
    _activate_sanfi_from_row(page)
    page._enc_back()
    assert page.sent == [] and page._act_confirm is None


def test_near_from_fix_sends_act_at_once(page, fix):
    # Leg SANFI -> HKYFA: the from-fix SANFI is 40 nm away.
    _at(fix, *NEAR)
    assert geo.distance_nm(*NEAR, SANFI.lat, SANFI.lon) == pytest.approx(40, abs=0.5)
    page._row_menu_index = 3
    page._row_menu_activate_leg()
    assert page.sent == [("ACT", 4)]
    assert page._act_confirm is None


@pytest.mark.parametrize("flag", ["fail", "old"])
def test_unusable_position_sends_act_at_once(page, fix, flag):
    setattr(fix.db.get_item("LAT"), flag, True)
    _activate_sanfi_from_row(page)
    assert page.sent == [("ACT", 3)]
    assert page._act_confirm is None


def test_missing_position_keys_send_act_at_once(page, monkeypatch):
    real = flight_plan.fix.db.get_item

    def get_item(key):
        if key in ("LAT", "LONG"):
            raise KeyError(key)
        return real(key)
    monkeypatch.setattr(flight_plan.fix.db, "get_item", get_item)
    _activate_sanfi_from_row(page)
    assert page.sent == [("ACT", 3)]


def test_first_waypoint_has_no_from_fix_and_sends_at_once(page):
    # Slot 1: the engine starts the leg from the aircraft, whatever the
    # distance to KSBA.
    page._row_menu_index = 0
    page._row_menu_activate_leg()
    assert page.sent == [("ACT", 1)]


def test_show_fixes_activate_leg_asks_too(page):
    page._open_seg_fixes(2)
    page._open_seg_fix_menu(2)
    page._seg_fix_activate_leg()
    assert page.sent == []
    assert page._act_confirm["from_id"] == "KSMO"
    page._act_confirm_yes()
    assert page.sent == [("ACT", 3)]


def test_segment_activate_to_entry_asks_too(page):
    # The approach segment's "Activate (to entry)" is the same leg,
    # KSMO -> SANFI, so it gets the same question.
    page._open_seg_menu(2)
    page._seg_menu_activate()
    assert page.sent == []
    assert page._act_confirm["from_id"] == "KSMO"
    page._act_confirm_no()
    assert page.sent == []
