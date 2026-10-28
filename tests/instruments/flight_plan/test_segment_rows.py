#  SPDX-License-Identifier: GPL-2.0-or-later
"""FPL page segment rows (RS3, billmallard/pyEfis#306, AER-3792).

Brief ``makerplane/briefs/route_segments_plan.md`` section 6, approved by Bill
2026-10-24 and the mock accepted 2026-10-27: an airway is one segment row when
the active leg is not in it; when it is, the FROM fix (dimmed), the active TO
fix and the next fix nest under it and the rest fold as "+N more". A tap on
the segment row opens the segment menu; Show Fixes lists every fix.

Route used throughout: KSBA, then V27 GVO-GOLET-KWANG-DEANO-HENER-VTU, then
KSMX. Flat indices: KSBA 0, GVO 1, GOLET 2, KWANG 3, DEANO 4, HENER 5, VTU 6,
KSMX 7. Coordinates are the AIRAC 2610 fixes the bench mock used.
"""

from types import SimpleNamespace

import pytest

from pyefis.flightplan import fixbridge, geo
from pyefis.flightplan import model as fp_model
from pyefis.instruments import flight_plan

BEELINK = SimpleNamespace(screenWidth=1920, screenHeight=1080, screenDiagonalInches=21.5)
MAGVAR = -11.6   # positive west: 11.6 E, about Santa Barbara

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


def _wp(ident, wtype, lat, lon, alt=""):
    return fp_model.Waypoint(id=ident, type=wtype, lat=lat, lon=lon, alt=alt)


KSBA = _wp("KSBA", "airport", 34.42621, -119.84037)
KSMX = _wp("KSMX", "airport", 34.89892, -120.45758)
V27 = [_wp("GVO", "vor", 34.53131944, -120.09108889),
       _wp("GOLET", "fix", 34.28135, -119.864375, "+6000"),
       _wp("KWANG", "fix", 34.30911389, -119.51415, "+6400"),
       _wp("DEANO", "fix", 34.31666389, -119.41645, "+4000"),
       _wp("HENER", "fix", 34.33106389, -119.22768889, "+5000"),
       _wp("VTU", "vor", 34.11506389, -119.0495, "+5000")]


def _route():
    return fp_model.FlightPlan(name="TEST", segments=[
        fp_model.waypoint_segment(KSBA),
        fp_model.Segment(kind="airway", ident="V27", legs=[w.copy() for w in V27],
                         cycle="2610"),
        fp_model.waypoint_segment(KSMX)])


class _Cmds:
    def __init__(self):
        self.sent = []


@pytest.fixture()
def page(fix, qtbot, monkeypatch):
    for key, dtype, blank in fixbridge.route_key_specs():
        _define(fix, key, dtype, blank)
    for key, dtype in _ENGINE.items():
        _define(fix, key, dtype, _BLANK[dtype])
    fix.db.set_value("MAGVAR", MAGVAR)
    w = flight_plan.FlightPlan(None)
    qtbot.addWidget(w)
    w.parent = SimpleNamespace(parent=BEELINK)
    w.resize(649, 993)
    w._plan = _route()
    w._commit()
    cmds = _Cmds()
    monkeypatch.setattr(w._bridge, "command",
                        lambda verb, arg=None, on_ack=None: cmds.sent.append((verb, arg)))
    staged = []
    monkeypatch.setattr(w._bridge, "stage_direct_to", lambda wp: staged.append(wp.id))
    w.cmds, w.staged = cmds.sent, staged
    return w


def _fly(w, fix, to_index):
    fix.db.set_value("FPLSTATE", 1)
    fix.db.set_value("FPLACTLEG", to_index + 1)
    w._sync_engine_from_bridge()


def _paint_taps(w):
    """Paint once and return (tap targets, their kinds)."""
    w.grab()
    return list(w._tap_targets), list(w._tap_kinds)


# --------------------------------------------------------------------------
# which rows are drawn
# --------------------------------------------------------------------------

def test_the_route_reads_back_as_one_airway_segment(page):
    assert [(s.kind, s.ident) for s in page._plan.segments] == [
        ("waypoint", ""), ("airway", "V27"), ("waypoint", "")]


def test_no_active_leg_shows_the_airway_as_one_segment_row(page):
    assert page._display_rows(None) == [("wpt", 0), ("wpt", 1), ("seg", 1), ("wpt", 7)]


def test_flying_to_the_entry_fix_is_not_inside_the_airway(page, fix):
    """KSBA -> GVO is the leg INTO the airway's entry; it is not one of the
    airway's legs, so the segment stays summarised."""
    _fly(page, fix, 1)
    assert page._display_rows(1) == [("wpt", 0), ("wpt", 1), ("seg", 1), ("wpt", 7)]


def test_inside_the_airway_the_working_rows_nest_and_the_rest_fold(page, fix):
    _fly(page, fix, 4)                       # KWANG -> DEANO, as on the mock
    assert page._display_rows(4) == [
        ("wpt", 0), ("wpt", 1), ("seg", 1),
        ("fix", 3, "from"), ("fix", 4, "to"), ("fix", 5, "next"), ("fold", 1, 1),
        ("wpt", 7)]


def test_on_the_first_airway_leg_from_is_the_entry_fix(page):
    rows = page._display_rows(2)             # GVO -> GOLET
    assert rows[3:7] == [("fix", 1, "from"), ("fix", 2, "to"), ("fix", 3, "next"),
                         ("fold", 1, 3)]


def test_on_the_last_airway_leg_there_is_no_next_and_no_fold(page):
    rows = page._display_rows(6)             # HENER -> VTU (the exit)
    assert rows == [("wpt", 0), ("wpt", 1), ("seg", 1),
                    ("fix", 5, "from"), ("fix", 6, "to"), ("wpt", 7)]


def test_one_fix_ahead_of_next_is_still_folded_not_shown(page):
    rows = page._display_rows(4)
    assert ("fold", 1, 1) in rows and ("fix", 6, "next") not in rows


def test_past_the_airway_it_folds_back_to_one_row(page):
    assert page._display_rows(7) == [("wpt", 0), ("wpt", 1), ("seg", 1), ("wpt", 7)]


@pytest.mark.parametrize("active, expected", [(None, "#ffffff"), (1, "#ffffff"),
                                              (2, "#ff00ff"), (6, "#ff00ff"),
                                              (7, "#808080")])
def test_segment_row_colour_follows_the_active_leg(page, active, expected):
    assert page._segment_color(1, active) == expected


# --------------------------------------------------------------------------
# the columns
# --------------------------------------------------------------------------

def test_segment_row_columns(page):
    """DTK blank (an airway changes course), DIS the airway's own length,
    CUM to its exit fix."""
    length = sum(geo.distance_nm(a.lat, a.lon, b.lat, b.lon) for a, b in zip(V27, V27[1:]))
    cum_exit = geo.distance_nm(KSBA.lat, KSBA.lon, V27[0].lat, V27[0].lon) + length
    assert page._segment_column_text("DTK", 1, None) == ""
    assert page._segment_column_text("DIS", 1, None) == f"{length:.0f}"
    assert page._segment_column_text("CUM", 1, None) == f"{cum_exit:.0f}"


def test_segment_mea_is_the_highest_leg_minimum(page):
    assert page._segment_mea(1) == 6400


def test_the_first_fix_has_no_inbound_leg(page):
    assert page._column_text("DTK", 0, None) == ""
    assert page._column_text("DIS", 0, None) == ""
    assert page._column_text("CUM", 0, None) == "0"


def test_dtk_is_the_magnetic_course_into_the_fix(page):
    true = geo.initial_bearing(V27[2].lat, V27[2].lon, V27[3].lat, V27[3].lon)
    assert page._column_text("DTK", 4, None) == f"{(true + MAGVAR) % 360:03.0f}°"
    dist = geo.distance_nm(V27[2].lat, V27[2].lon, V27[3].lat, V27[3].lon)
    assert page._column_text("DIS", 4, None) == f"{dist:.0f}"


@pytest.mark.parametrize("i", range(1, 8))
def test_dtk_on_every_row_equals_the_course_published_on_its_slot(page, fix, i):
    """The DoD check "DTK on the page equals FPLCRS on the active leg": the
    engine flies the slot's FPLfCRS, so each row must show exactly that."""
    published = fix.db.get_item(f"FPL{i + 1}CRS").value
    assert page._column_text("DTK", i, None) == f"{published:03.0f}°"


# --------------------------------------------------------------------------
# geometry
# --------------------------------------------------------------------------

def test_rows_size_by_display_rows_and_each_row_is_one_tap(page, fix):
    """One tap target per display row; the 8-fix route draws 4 rows when
    summarised and 8 when the airway is open, each at the physical cap."""
    for active, n in ((None, 4), (4, 8)):
        if active is not None:
            _fly(page, fix, active)
        taps, kinds = _paint_taps(page)
        rows = [t for t, k in zip(taps, kinds) if k == "row"]
        assert len(rows) == n
        assert rows[0][3] == pytest.approx(page._row_h_cap())


def test_nested_rows_are_indented_by_one_icon_column(page, fix):
    rh = page._row_h_cap()
    ir, icx, lx = page._row_icon_geometry(rh)
    assert page._nest_indent(rh) == pytest.approx(lx - (icx - ir))
    # Nested icon starts where a plain row's label starts.
    assert icx + page._nest_indent(rh) - ir == pytest.approx(lx)


def test_header_strip_names_the_columns(page):
    hh, rh = page._list_metrics(0, 800, page._row_h_cap(), 4)
    assert hh == pytest.approx(page._row_h_cap() * 0.5)


def test_open_airway_paints_without_left_edge_clipping(page, fix):
    _fly(page, fix, 4)
    img = page.grab().toImage()
    top = int(page._chrome_h(993, 2.0, 0.26))
    bottom = int(993 - page._chrome_h(993, 1.3, 0.18))
    lit = [y for y in range(top, bottom)
           if max(img.pixelColor(0, y).red(), img.pixelColor(0, y).green(),
                  img.pixelColor(0, y).blue()) > 60]
    assert not lit, f"list content flush against the left edge at y={lit[:5]}"


# --------------------------------------------------------------------------
# taps and menus
# --------------------------------------------------------------------------

def _tap_row(w, index):
    taps, kinds = _paint_taps(w)
    x, y, tw, th, cb = [t for t, k in zip(taps, kinds) if k == "row"][index]
    cb()


def test_tapping_the_segment_row_opens_the_segment_menu(page):
    _tap_row(page, 2)
    assert page._seg_menu == 1 and page._row_menu_index is None


def test_tapping_a_plain_row_still_opens_the_fix_menu(page):
    _tap_row(page, 1)
    assert page._row_menu_index == 1 and page._seg_menu is None


def test_segment_menu_items(page):
    page._open_seg_menu(1)
    taps, kinds = _paint_taps(page)
    # Five items plus Cancel, all on the menu layer.
    assert len(taps) - page._enc_layer_start == 6
    assert [label for label, _ in flight_plan._SEG_MENU_ITEMS] == [
        "Change Exit", "Change Entry", "Show Fixes", "Activate", "Remove Airway"]


def test_activate_flies_to_the_airway_entry(page):
    page._open_seg_menu(1)
    page._seg_menu_activate()
    assert page.cmds == [("ACT", 2)]          # GVO is slot 2
    assert page._seg_menu is None


def test_remove_airway_leaves_the_entry_fix(page, fix):
    page._open_seg_menu(1)
    page._seg_menu_remove()
    assert [w.id for w in page._plan.waypoints] == ["KSBA", "GVO", "KSMX"]
    assert all(s.kind == "waypoint" for s in page._plan.segments)
    assert fix.db.get_item("FPLSEGCNT").value in (0, 3)   # no airway on the bus
    assert all(fix.db.get_item(f"FPLS{k}KIND").value == 0
               for k in range(1, fix.db.get_item("FPLSEGCNT").value + 1))


def test_show_fixes_lists_every_fix_with_a_tap_each_and_close(page):
    page._open_seg_menu(1)
    page._seg_menu_show_fixes()
    assert page._seg_fixes == 1 and page._seg_menu is None
    taps, kinds = _paint_taps(page)
    layer = list(zip(taps, kinds))[page._enc_layer_start:]
    assert sum(1 for _, k in layer if k == "row") == len(V27)
    assert len(layer) == len(V27) + 1         # + Close


def test_fold_row_opens_show_fixes(page, fix):
    _fly(page, fix, 4)
    _tap_row(page, 6)                         # the "+ 1 more" row
    assert page._seg_fixes == 1


def test_show_fixes_direct_to_acts_on_one_fix(page):
    page._open_seg_fixes(1)
    page._open_seg_fix_menu(5)                # HENER
    page._seg_fix_direct_to()
    assert page.staged == ["HENER"] and page.cmds == [("DTO", 6)]
    assert page._seg_fixes is None and page._seg_fix_menu is None


def test_show_fixes_activate_leg_acts_on_one_fix(page):
    page._open_seg_fixes(1)
    page._open_seg_fix_menu(3)
    page._seg_fix_activate_leg()
    assert page.cmds == [("ACT", 4)]


def test_nested_fix_row_tap_opens_the_one_fix_menu(page, fix):
    _fly(page, fix, 4)
    _tap_row(page, 4)                         # DEANO, the active TO fix
    assert page._seg_fix_menu == 4
    page.grab()                               # the menu paints


def test_back_unwinds_fix_menu_then_sheet(page):
    page._open_seg_fixes(1)
    page._open_seg_fix_menu(2)
    assert page._enc_back() and page._seg_fix_menu is None and page._seg_fixes == 1
    assert page._enc_back() and page._seg_fixes is None
    assert page._enc_back() is False


def test_wpt_info_from_the_sheet_stacks_over_it(page):
    page._open_seg_fixes(1)
    page._open_seg_fix_menu(2)
    page._seg_fix_wpt_info()
    assert page._wpt_info is not None and page._seg_fixes == 1
    page.grab()
    assert page._enc_back() and page._wpt_info is None and page._seg_fixes == 1
