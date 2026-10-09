#  SPDX-License-Identifier: GPL-2.0-or-later
"""Encoder path for the `flight_plan` instrument (FP5c, billmallard/pyEfis#188).

Drives the widget through the ``enc_*`` protocol exactly as
``screens/screenbuilder_encoder.py`` does -- ``enc_select`` to take control,
then ``enc_changed(steps)`` / ``enc_clicked()`` / ``enc_long_clicked()`` --
with no touch or keyboard input. The controller's long-push routing is
pinned separately in ``tests/screens/test_screenbuilder_encoder_long_press.py``.

Helpers come from ``test_flight_plan`` by module (not by name, so pytest does
not collect its tests twice).
"""

from PyQt6.QtGui import QColor

from pyefis.instruments import flight_plan
from tests.instruments.flight_plan import test_flight_plan as base


def _widget(fix, qtbot, tmp_path=None, n=0, size=(480, 640)):
    base._define_all_fp1_keys(fix)
    w = flight_plan.FlightPlan(None)
    qtbot.addWidget(w)
    w.resize(*size)
    if tmp_path is not None:
        base._install_index(w, base._build_fixture_index(tmp_path))
    if n:
        w._plan = base._plan(n)
        w._commit()
    return w


def _take_control(w):
    w.enc_highlight(True)
    assert w.enc_select() is True


def _focused(w):
    ring = w._enc_prepare()
    if w._enc_focus is None:
        return None
    return ring[w._enc_focus]


def _dial(w, ch):
    """Turn the knob from the character under the cursor to *ch* in one
    accumulated step count, the way the controller passes a fast spin."""
    field, cur = w._entry_field, w._enc_cursor
    here = field[cur] if cur < len(field) else " "
    cs = flight_plan.ENC_CHARSET
    delta = (cs.index(ch) - cs.index(here)) % len(cs)
    assert w.enc_changed(delta) is True


def _knob_type(w, text):
    for ch in text:
        _dial(w, ch)
        w.enc_clicked()          # keep it, cursor advances


# ---------------------------------------------------------------------------
# protocol shape
# ---------------------------------------------------------------------------
def test_flight_plan_is_encoder_selectable_and_opts_into_long_push(fix, qtbot):
    w = _widget(fix, qtbot)
    assert w.enc_selectable() is True
    assert callable(w.enc_long_clicked)
    assert w.enc_long_press_ms == flight_plan.ENC_LONG_PRESS_MS == 600


def test_encoder_order_option_enrols_the_instrument(fix, qtbot):
    from pyefis.screens import screenbuilder_options
    w = _widget(fix, qtbot)
    screen = type("S", (), {})()
    screen.instruments = {0: w}
    screen.encoder_list = []
    screenbuilder_options.apply_options(
        screen, 0, {"type": "flight_plan", "options": {"encoder_order": 3}})
    assert screen.encoder_list == [{"inst": 0, "order": 3}]


def test_without_gateway_keys_the_knob_is_inert_and_long_push_releases(fix, qtbot):
    w = flight_plan.FlightPlan(None)   # FP1 keys never defined
    qtbot.addWidget(w)
    _take_control(w)
    assert w.enc_changed(1) is True
    assert w.enc_clicked() is True
    assert w._page in (None, "fpl")
    assert w.enc_long_clicked() is False


# ---------------------------------------------------------------------------
# DoD: enter, scroll to a row, open the row menu, pick Activate Leg
# ---------------------------------------------------------------------------
def test_scroll_to_row_open_menu_activate_leg_issues_act(fix, qtbot):
    w = _widget(fix, qtbot, n=4)
    _take_control(w)
    assert w._enc_focus is None          # FPL page: nothing focused on entry

    w.enc_changed(1)                     # -> row 1 (WP00)
    w.enc_changed(1)                     # -> row 2 (WP01)
    kind, _rect, _cb = _focused(w)
    assert kind == "row"

    w.enc_clicked()
    assert w._row_menu_index == 1

    labels = [label for label, _attr in flight_plan._ROW_MENU_ITEMS]
    w.enc_changed(labels.index("Activate Leg"))   # menu opens focused on item 0
    w.enc_clicked()

    assert w._row_menu_index is None
    assert fix.db.get_item("FPLCMD").value.endswith("ACT 2")


def test_ring_walks_only_the_topmost_layer(fix, qtbot):
    # Tall enough that the row menu does not need its scroll arrows.
    w = _widget(fix, qtbot, n=4, size=(480, 1000))
    _take_control(w)
    w.enc_changed(1)
    w.enc_clicked()                      # row menu over the FPL page
    ring = w._enc_prepare()
    # Menu items + Cancel only -- never the dimmed rows/soft keys behind it.
    assert len(ring) == len(flight_plan._ROW_MENU_ITEMS) + 1
    # Wraps rather than escaping to the page behind.
    w.enc_changed(len(ring))
    assert w._enc_focus == 0


def test_turn_wraps_through_nothing_focused_on_the_fpl_page(fix, qtbot):
    w = _widget(fix, qtbot, n=2)
    _take_control(w)
    ring = w._enc_prepare()
    w.enc_changed(-1)                    # back past "nothing" onto the last soft key
    assert ring[w._enc_focus][0] == "soft"
    w.enc_changed(1)
    assert w._enc_focus is None


# ---------------------------------------------------------------------------
# DoD: Entry page -- turn/push builds KSBA; long push cancels
# ---------------------------------------------------------------------------
def test_entry_turn_push_builds_ksba_and_commits(fix, qtbot, tmp_path):
    w = _widget(fix, qtbot, tmp_path)
    _take_control(w)
    w.enc_changed(1)                     # FPL page has no rows: first soft key
    assert _focused(w)[2] == w._footer_add
    w.enc_clicked()                      # ADD WPT -> Entry page, field editing
    assert w._page == "entry"
    assert w._enc_editing is True

    _knob_type(w, "KSBA")
    assert w._entry_field == "KSBA"
    w.enc_clicked()                      # blank under the cursor: accept

    assert w._page == "fpl"
    assert [wp.id for wp in w._plan.waypoints] == ["KSBA"]


def test_entry_single_detents_scroll_the_character_both_ways(fix, qtbot, tmp_path):
    w = _widget(fix, qtbot, tmp_path)
    _take_control(w)
    w._footer_add()
    w._enc_prepare()                     # Entry page default: field, editing
    for _ in range(3):
        w.enc_changed(1)
    assert w._entry_field == "C"
    w.enc_changed(-1)
    assert w._entry_field == "B"
    w.enc_changed(-2)                    # B -> A -> space: the character is gone
    assert w._entry_field == ""
    w.enc_changed(-1)                    # wraps to the end of the set
    assert w._entry_field == "9"


def test_entry_push_on_blank_accepts_the_fastfind_prediction(fix, qtbot, tmp_path):
    w = _widget(fix, qtbot, tmp_path)
    _take_control(w)
    w._footer_add()
    w._enc_prepare()
    _knob_type(w, "KS")
    assert w._entry_suffix() == "BA"
    w.enc_clicked()
    assert [wp.id for wp in w._plan.waypoints] == ["KSBA"]


def test_entry_long_push_cancels(fix, qtbot, tmp_path):
    w = _widget(fix, qtbot, tmp_path)
    _take_control(w)
    w._footer_add()
    w._enc_prepare()
    _knob_type(w, "KS")
    assert w.enc_long_clicked() is True   # still in control, back on FPL
    assert w._page == "fpl"
    assert w._entry_mode is None
    assert w._plan.count == 0


def test_entry_keypad_is_out_of_the_ring_and_push_on_empty_leaves_the_field(
        fix, qtbot, tmp_path):
    w = _widget(fix, qtbot, tmp_path)
    _take_control(w)
    w._footer_add()
    ring = w._enc_prepare()
    assert ring[0][0] == "field"
    assert "key" not in [k for k, _r, _c in ring]
    w.enc_clicked()                      # nothing typed: hand the turn to the ring
    assert w._enc_editing is False
    w.enc_changed(1)
    assert w._entry_field == ""          # the turn moved focus, not a character


def test_entry_pick_from_nearest_tab_by_knob(fix, qtbot, tmp_path):
    w = _widget(fix, qtbot, tmp_path)
    w._aircraft_position = lambda: (34.4, -119.8)   # near the fixture airports
    _take_control(w)
    w._footer_add()
    ring = w._enc_prepare()
    w.enc_clicked()                      # leave the empty field
    tab = next(i for i, (k, r, c) in enumerate(ring)
               if k is None and getattr(c, "__defaults__", None) == ("Nearest",))
    w.enc_changed(tab - w._enc_focus)
    w.enc_clicked()
    assert w._entry_tab == "Nearest"
    ring = w._enc_prepare()
    row = next(i for i, (k, _r, _c) in enumerate(ring) if k == "row")
    w.enc_changed(row - w._enc_focus)
    w.enc_clicked()
    assert w._plan.count == 1


# ---------------------------------------------------------------------------
# Direct-To knob shortcut (guide 3-45)
# ---------------------------------------------------------------------------
def test_push_with_nothing_focused_opens_dto_second_push_activates(fix, qtbot):
    w = _widget(fix, qtbot, n=4)
    fix.db.set_value("FPLACTLEG", 3)
    w._sync_engine_from_bridge()
    _take_control(w)

    w.enc_clicked()
    assert w._page == "dto"
    assert w._dto_target[:2] == ("fpl", 2)
    assert _focused(w)[0] == "activate"

    w.enc_clicked()
    assert w._page == "fpl"
    assert fix.db.get_item("FPLCMD").value.endswith("DTO 3")


def test_dto_shortcut_without_an_active_leg_opens_the_waypoint_field(fix, qtbot, tmp_path):
    w = _widget(fix, qtbot, tmp_path)
    _take_control(w)
    w.enc_clicked()
    assert w._page == "dto" and w._dto_tab == "Waypoint"
    w._enc_prepare()
    assert w._enc_editing is True
    _knob_type(w, "KSBA")
    w.enc_clicked()
    assert fix.db.get_item("FPLCMD").value.endswith("DTO")
    assert fix.db.get_item("DTOID").value == "KSBA"


# ---------------------------------------------------------------------------
# Back, confirms, highlight
# ---------------------------------------------------------------------------
def test_long_push_backs_out_one_level_then_releases_control(fix, qtbot):
    w = _widget(fix, qtbot, n=3)
    _take_control(w)
    w.enc_changed(1)
    w.enc_clicked()
    assert w._row_menu_index is not None
    assert w.enc_long_clicked() is True
    assert w._row_menu_index is None
    assert w.enc_long_clicked() is False   # FPL page, nothing open: knob goes back


def test_confirm_box_defaults_to_no(fix, qtbot):
    w = _widget(fix, qtbot, n=3)
    _take_control(w)
    w._footer_menu()
    w._menu_clear_request()
    w.enc_clicked()
    assert w._plan.count == 3            # the default answer did not clear it
    assert w._confirm is None and w._menu_open is False


def _orange_pixels(img, rect):
    want = QColor(flight_plan._ENC_FOCUS_COLOR)
    hits = 0
    for x in range(int(rect.left()), int(rect.right())):
        for y in (int(rect.top()) + 3, int(rect.bottom()) - 3):
            c = img.pixelColor(x, y)
            if abs(c.red() - want.red()) < 40 and abs(c.green() - want.green()) < 40 \
                    and c.blue() < 60:
                hits += 1
    return hits


def test_focus_ring_is_drawn_on_the_focused_row_only(fix, qtbot):
    w = _widget(fix, qtbot, n=4)
    _take_control(w)
    w.enc_changed(2)
    ring = w._enc_prepare()
    focused = ring[w._enc_focus][1]
    other = ring[w._enc_focus + 1][1]
    img = w.grab().toImage()
    assert _orange_pixels(img, focused) > focused.width()   # top + bottom edges
    assert _orange_pixels(img, other) == 0


def test_highlight_without_control_outlines_the_instrument(fix, qtbot):
    w = _widget(fix, qtbot, n=2)
    w.enc_highlight(True)
    img = w.grab().toImage()
    c = img.pixelColor(1, w.height() // 2)
    assert c.red() > 200 and c.blue() < 60
    w.enc_highlight(False)
    assert w._enc_active is False
    c = w.grab().toImage().pixelColor(1, w.height() // 2)
    assert c.red() < 60
