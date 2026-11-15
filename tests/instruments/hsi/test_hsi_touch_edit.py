#  SPDX-License-Identifier: GPL-2.0-or-later
"""HSI touch-select + knob edit of the HDG and CRS readouts (pyEfis #309, TK2).

Touching HDG edits HEADBUG; touching CRS edits NAV1CRS or NAV2CRS, following
NAVSRC, and is not editable on GPS. COURSE is never written. Inner knob 1 deg,
outer ring 10 deg, wrapping through 360; push syncs HDG to the heading and
centres the CDI on CRS. The nav-source tab keeps cycling NAVSRC.
"""

import pytest
from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, QTimer, Qt
from PyQt6.QtGui import QPaintEvent
from PyQt6.QtWidgets import QWidget

from pyefis import display_metrics
from pyefis.instruments import edit_focus, hsi
from pyefis.screens.screenbuilder_encoder import EncoderController

LAYOUTS = ("top_panel", "corners", "split")


@pytest.fixture(autouse=True)
def _clean_registry():
    edit_focus.set_at_rest_hint(False)
    yield
    owner = edit_focus.owner()
    if owner is not None:
        owner.release_focus()
    edit_focus.release(edit_focus.owner())
    edit_focus.set_at_rest_hint(False)


@pytest.fixture
def nav(fix, monkeypatch):
    """The nav keys the HSI edits, plus a recorder on what is sent to
    fix-gateway (a local value alone never leaves pyEfis, pyEfis #294)."""
    for key, val in (("HEADBUG", 120.0), ("NAVSRC", 0.0), ("NAVTYPE", 1.0),
                     ("NAV1CRS", 45.0), ("NAV2CRS", 200.0), ("GPSCRS", 10.0),
                     ("VOR1BRG", 77.4), ("VOR2BRG", 301.0)):
        fix.db.define_item(key, key, "float", 0.0, 359.9, "deg", 50000, "")
        fix.db.set_value(key, val)
        it = fix.db.get_item(key)
        it.old = it.bad = it.fail = False
    fix.db.set_value("HEAD", 87.0)
    fix.db.set_value("COURSE", 45.0)
    sent = []
    monkeypatch.setattr(fix.db, "queue_out", lambda b: sent.append(b.decode()))
    fix.sent = sent
    return fix


class _Host(QWidget):
    """Stands in for a Screen: the HSI finds encoder_controller by walking up
    its parents, exactly as on a real screen."""

    def __init__(self):
        super().__init__()
        self.instruments = {}
        self.encoder_list = []
        self.encoder_list_sorted = []
        self.encoder_current_selection = None
        self.encoder_timeout = 10_000
        self.encoder_timestamp = 0
        self.encoder_control = False
        self.encoder_timer = QTimer(self)
        self.encoder = None
        self.encoder_button = None
        self.encoder_controller = EncoderController(self)

    def encoderChanged(self, value=0):
        self.encoder_controller.changed(value)

    def hideEvent(self, event):
        self.encoder_controller.release_focus()
        super().hideEvent(event)


def _hsi(qtbot, layout="top_panel", touch_edit=True):
    host = _Host()
    w = hsi.HSI(host, font_percent=0.05, cdi_enabled=True)
    w.readout_layout = layout
    w.touch_edit = touch_edit
    w.setGeometry(0, 0, 432, 425)
    host.instruments[0] = w
    qtbot.addWidget(host)
    host.resize(432, 425)
    host.show()
    qtbot.waitExposed(host)
    _paint(w)
    return host, w


def _paint(w):
    # Direct, as the other HSI tests do: offscreen Qt does not reliably run
    # the viewport's paint synchronously, and the paint records the targets.
    w.paintEvent(QPaintEvent(QRect(w.rect())))


def _centre(w, field):
    return w._edit_rects[field][0].center().toPoint()


def _tap(qtbot, w, pos):
    qtbot.mouseClick(w.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(pos))
    _paint(w)


def _sent(fix, key):
    return [float(m.split(";")[1]) for m in fix.sent if m.startswith(key + ";")]


# --- hit-testing in every layout that shows the boxes ------------------------

@pytest.mark.parametrize("layout", LAYOUTS)
def test_touching_hdg_focuses_it_in_every_layout(nav, qtbot, layout):
    host, w = _hsi(qtbot, layout)
    _tap(qtbot, w, _centre(w, "hdg"))
    assert w._edit_field == "hdg"
    assert host.encoder_controller.focused_instrument() is w
    assert edit_focus.owner() is host.encoder_controller


@pytest.mark.parametrize("layout", LAYOUTS)
def test_touching_crs_focuses_it_in_every_layout(nav, qtbot, layout):
    host, w = _hsi(qtbot, layout)
    _tap(qtbot, w, _centre(w, "crs"))
    assert w._edit_field == "crs"
    assert host.encoder_controller.focused_instrument() is w


@pytest.mark.parametrize("layout", LAYOUTS)
def test_the_hit_boxes_are_the_drawn_readouts(nav, qtbot, layout):
    """The recorded targets sit where the readouts are drawn: HDG and CRS on
    the sides the layout puts them, inside the widget, not overlapping."""
    _host, w = _hsi(qtbot, layout)
    hdg, crs = w._edit_rects["hdg"][0], w._edit_rects["crs"][0]
    inside = QRectF(w.rect())
    assert inside.contains(hdg) and inside.contains(crs)
    assert not hdg.intersects(crs)
    if layout == "split":      # CRS bottom-left, HDG bottom-right
        assert crs.center().x() < w.width() / 2 < hdg.center().x()
        assert hdg.top() > w.height() / 2 and crs.top() > w.height() / 2
    else:                      # HDG left, CRS right, along the top
        assert hdg.center().x() < w.width() / 2 < crs.center().x()
        assert hdg.bottom() < w.height() / 2 and crs.bottom() < w.height() / 2


def test_layout_none_has_nothing_to_touch(nav, qtbot):
    host, w = _hsi(qtbot, "none")
    assert w._edit_rects == {}
    _tap(qtbot, w, QPoint(60, 20))
    assert w._edit_field is None
    assert host.encoder_control is False


def test_touch_edit_is_on_by_default(nav, qtbot):
    """Bill's call on pyEfis #317: an HSI touch-edits HDG and CRS unless the
    panel turns it off, and the editor offers the same default."""
    from pyefis.editor import schema as eschema
    host = _Host()
    qtbot.addWidget(host)
    assert hsi.HSI(host, font_percent=0.05, cdi_enabled=True).touch_edit is True
    opts = eschema.build_schema()["instruments"][
        "horizontal_situation_indicator"]["options"]
    opt = opts["touch_edit"] if isinstance(opts, dict) else next(
        o for o in opts if o.get("name") == "touch_edit")
    assert opt["default"] is True


def test_touch_edit_off_leaves_the_readouts_inert(nav, qtbot):
    host, w = _hsi(qtbot, touch_edit=False)
    _tap(qtbot, w, _centre(w, "hdg"))
    assert w._edit_field is None
    assert host.encoder_control is False


def test_touch_target_is_grown_to_a_gloved_finger(nav, qtbot):
    """A press just outside the drawn box, inside the 12.7 mm target, still
    focuses: the hit area is sized for a gloved finger, not the box."""
    _host, w = _hsi(qtbot, "corners")
    assert w._min_touch_px() == pytest.approx(
        display_metrics.mm_to_px(hsi.EDIT_TOUCH_MM, qscreen=w.screen()))
    # A dense panel: 12.7 mm is more pixels than the box is tall.
    w._min_touch_px = lambda: 100.0
    box = w._edit_rects["crs"][0]
    grown = w._touch_rect(box)
    assert grown.width() == pytest.approx(100.0)
    assert grown.height() == pytest.approx(100.0)
    below = QPointF(box.center().x(), box.bottom() + (grown.bottom() - box.bottom()) / 2)
    assert not box.contains(below)
    _tap(qtbot, w, below.toPoint())
    assert w._edit_field == "crs"


def test_closed_form_touch_rect():
    w = hsi.HSI.__new__(hsi.HSI)
    w._min_touch_px = lambda: 48.0
    r = hsi.HSI._touch_rect(w, QRectF(10, 10, 20, 60))
    assert r == QRectF(-4, 10, 48, 60)   # widened only; already tall enough


# --- knob: fine/coarse, wrap at 0/360 -----------------------------------------

def test_hdg_inner_fine_outer_coarse_writes_headbug_to_the_bus(nav, qtbot):
    host, w = _hsi(qtbot)
    _tap(qtbot, w, _centre(w, "hdg"))
    ctl = host.encoder_controller
    ctl.changed(3)
    assert nav.db.get_item("HEADBUG").value == 123.0
    ctl.outer_changed(-2)
    assert nav.db.get_item("HEADBUG").value == 103.0
    assert _sent(nav, "HEADBUG") == [123.0, 103.0]
    assert _sent(nav, "COURSE") == []


@pytest.mark.parametrize("start, inner, outer, expect", [
    (359.0, 1, 0, 0.0),
    (0.0, -1, 0, 359.0),
    (355.0, 0, 1, 5.0),
    (5.0, 0, -1, 355.0),
    (359.6, 1, 0, 1.0),      # steps from the whole degree the readout shows
    (350.0, 0, 3, 20.0),
])
def test_hdg_wraps_through_360(nav, qtbot, start, inner, outer, expect):
    nav.db.set_value("HEADBUG", start)
    host, w = _hsi(qtbot)
    _tap(qtbot, w, _centre(w, "hdg"))
    if inner:
        host.encoder_controller.changed(inner)
    if outer:
        host.encoder_controller.outer_changed(outer)
    assert nav.db.get_item("HEADBUG").value == expect


def test_crs_wraps_through_360(nav, qtbot):
    nav.db.set_value("NAV1CRS", 2.0)
    host, w = _hsi(qtbot)
    _tap(qtbot, w, _centre(w, "crs"))
    host.encoder_controller.outer_changed(-1)
    assert nav.db.get_item("NAV1CRS").value == 352.0
    host.encoder_controller.changed(8)
    assert nav.db.get_item("NAV1CRS").value == 0.0


# --- per-source CRS routing -----------------------------------------------------

@pytest.mark.parametrize("src, key, other", [(0, "NAV1CRS", "NAV2CRS"),
                                             (1, "NAV2CRS", "NAV1CRS")])
def test_crs_writes_the_selected_nav_radios_course(nav, qtbot, src, key, other):
    nav.db.set_value("NAVSRC", float(src))
    host, w = _hsi(qtbot)
    before = nav.db.get_item(other).value
    _tap(qtbot, w, _centre(w, "crs"))
    start = nav.db.get_item(key).value
    host.encoder_controller.changed(1)
    assert nav.db.get_item(key).value == (round(start) + 1) % 360
    assert _sent(nav, key) == [(round(start) + 1) % 360]
    assert nav.db.get_item(other).value == before
    assert _sent(nav, other) == []
    assert _sent(nav, "COURSE") == []
    assert nav.db.get_item("COURSE").value == 45.0


def test_crs_readout_shows_the_edited_course_at_once(nav, qtbot):
    """COURSE only follows NAV1CRS after fix-gateway's select runs; while CRS
    is focused the readout shows the key being turned."""
    host, w = _hsi(qtbot)
    assert w._crs_display() == 45.0
    _tap(qtbot, w, _centre(w, "crs"))
    host.encoder_controller.changed(10)
    assert w._crs_display() == 55.0
    assert w._courseSelect == 45.0


def test_crs_is_not_focusable_on_gps(nav, qtbot):
    nav.db.set_value("NAVSRC", 2.0)
    host, w = _hsi(qtbot)
    assert not w._field_editable("crs")
    _tap(qtbot, w, _centre(w, "crs"))
    assert w._edit_field is None
    assert host.encoder_control is False
    assert _sent(nav, "GPSCRS") == [] and _sent(nav, "COURSE") == []


def test_source_change_while_crs_focused_ends_the_edit(nav, qtbot):
    host, w = _hsi(qtbot)
    _tap(qtbot, w, _centre(w, "crs"))
    nav.db.set_value("NAVSRC", 1.0)
    assert w._edit_field is None
    assert host.encoder_control is False
    assert edit_focus.owner() is None


def test_source_change_while_hdg_focused_keeps_it(nav, qtbot):
    host, w = _hsi(qtbot)
    _tap(qtbot, w, _centre(w, "hdg"))
    nav.db.set_value("NAVSRC", 2.0)
    assert w._edit_field == "hdg"
    assert host.encoder_controller.focused_instrument() is w


# --- the nav-source tab is unchanged -------------------------------------------

def test_source_tab_tap_still_cycles_navsrc_and_focuses_nothing(nav, qtbot):
    host, w = _hsi(qtbot, "top_panel")
    x, y, tw, th = w._source_label_rect
    _tap(qtbot, w, QPointF(x + tw / 2, y + th / 2).toPoint())
    assert nav.db.get_item("NAVSRC").value == 1.0
    assert w._edit_field is None
    assert host.encoder_control is False


def test_source_tab_tap_while_crs_focused_cycles_and_releases(nav, qtbot):
    host, w = _hsi(qtbot, "top_panel")
    _tap(qtbot, w, _centre(w, "crs"))
    x, y, tw, th = w._source_label_rect
    _tap(qtbot, w, QPointF(x + tw / 2, y + th / 2).toPoint())
    assert nav.db.get_item("NAVSRC").value == 1.0
    assert w._edit_field is None
    assert edit_focus.owner() is None


# --- push -----------------------------------------------------------------------

def test_hdg_push_syncs_the_bug_to_the_heading_and_keeps_focus(nav, qtbot):
    host, w = _hsi(qtbot)
    _tap(qtbot, w, _centre(w, "hdg"))
    host.encoder_controller.button_changed(True)
    assert nav.db.get_item("HEADBUG").value == 87.0
    assert _sent(nav, "HEADBUG") == [87.0]
    assert w._edit_field == "hdg"


def test_hdg_push_with_a_failed_heading_only_ends_the_edit(nav, qtbot):
    nav.db.get_item("HEAD").fail = True
    host, w = _hsi(qtbot)
    _tap(qtbot, w, _centre(w, "hdg"))
    assert w._edit_field == "hdg"
    host.encoder_controller.button_changed(True)
    assert nav.db.get_item("HEADBUG").value == 120.0
    assert w._edit_field is None
    assert edit_focus.owner() is None


@pytest.mark.parametrize("src, key, brg", [(0, "NAV1CRS", 77.0), (1, "NAV2CRS", 301.0)])
def test_crs_push_centres_the_cdi_on_the_station_bearing(nav, qtbot, src, key, brg):
    nav.db.set_value("NAVSRC", float(src))
    host, w = _hsi(qtbot)
    _tap(qtbot, w, _centre(w, "crs"))
    host.encoder_controller.button_changed(True)
    assert nav.db.get_item(key).value == brg
    assert _sent(nav, key) == [brg]
    assert w._edit_field == "crs"


@pytest.mark.parametrize("why", ["localizer", "flagged", "absent"])
def test_crs_push_without_a_bearing_to_centre_on_ends_the_edit(nav, qtbot, why):
    if why == "localizer":
        nav.db.set_value("NAVTYPE", 2.0)
    elif why == "flagged":
        nav.db.get_item("VOR1BRG").old = True
    host, w = _hsi(qtbot)
    if why == "absent":
        w._fix_item = (lambda key, real=w._fix_item:
                       None if key == "VOR1BRG" else real(key))
    _tap(qtbot, w, _centre(w, "crs"))
    host.encoder_controller.button_changed(True)
    assert nav.db.get_item("NAV1CRS").value == 45.0
    assert _sent(nav, "NAV1CRS") == []
    assert w._edit_field is None
    assert edit_focus.owner() is None


# --- focus moves, clears, and keeps the value ----------------------------------

def test_touching_the_other_readout_moves_focus(nav, qtbot):
    host, w = _hsi(qtbot)
    _tap(qtbot, w, _centre(w, "hdg"))
    _tap(qtbot, w, _centre(w, "crs"))
    assert w._edit_field == "crs"
    host.encoder_controller.changed(1)
    assert nav.db.get_item("NAV1CRS").value == 46.0
    assert nav.db.get_item("HEADBUG").value == 120.0


def test_touching_the_rose_clears_focus(nav, qtbot):
    host, w = _hsi(qtbot)
    _tap(qtbot, w, _centre(w, "hdg"))
    _tap(qtbot, w, QPoint(w.width() // 2, int(w.height() * 0.6)))
    assert w._edit_field is None
    assert host.encoder_control is False


def test_timeout_clears_focus_and_keeps_the_value(nav, qtbot):
    host, w = _hsi(qtbot)
    host.encoder_timeout = 50
    _tap(qtbot, w, _centre(w, "hdg"))
    host.encoder_controller.changed(5)
    qtbot.waitUntil(lambda: host.encoder_control is False, timeout=2000)
    assert w._edit_field is None
    assert nav.db.get_item("HEADBUG").value == 125.0


def test_screen_hide_clears_focus(nav, qtbot):
    host, w = _hsi(qtbot)
    _tap(qtbot, w, _centre(w, "crs"))
    host.hide()
    assert w._edit_field is None
    assert edit_focus.owner() is None


def test_the_hsi_is_not_in_the_knob_walk(nav, qtbot):
    """Touch-only: encoder_order is ignored for the HSI (it has no
    enc_selectable), so the knob walk never lands on it unasked."""
    _host, w = _hsi(qtbot)
    assert not callable(getattr(w, "enc_selectable", None))


# --- the shared marks -----------------------------------------------------------

def _marks(monkeypatch, w):
    calls = []
    monkeypatch.setattr(hsi.edit_focus, "draw_edit_marks",
                        lambda p, rect, focused, bounds=None:
                        calls.append((QRectF(rect), focused)))
    _paint(w)
    return calls


@pytest.mark.parametrize("layout", LAYOUTS)
def test_marks_on_both_readouts_ring_on_the_focused_one(nav, qtbot, monkeypatch, layout):
    host, w = _hsi(qtbot, layout)
    _tap(qtbot, w, _centre(w, "hdg"))
    calls = _marks(monkeypatch, w)
    assert len(calls) == 2
    focused = [rect for rect, f in calls if f]
    assert len(focused) == 1
    assert focused[0] == w._edit_rects["hdg"][1]


def test_no_marks_on_crs_when_the_source_is_gps(nav, qtbot, monkeypatch):
    nav.db.set_value("NAVSRC", 2.0)
    _host, w = _hsi(qtbot)
    calls = _marks(monkeypatch, w)
    assert [r for r, _f in calls] == [w._edit_rects["hdg"][1]]


def test_no_marks_at_all_without_touch_edit(nav, qtbot, monkeypatch):
    _host, w = _hsi(qtbot, touch_edit=False)
    assert _marks(monkeypatch, w) == []


def test_top_panel_ring_stays_inside_its_cell(nav, qtbot):
    """Inside the sectioned panel the ring must not cross into MAG or the
    source tab: the marks rect is the cell inset for the ring."""
    _host, w = _hsi(qtbot, "top_panel")
    cell, marks, bounds = w._edit_rects["hdg"]
    assert bounds == cell
    assert cell.contains(edit_focus.ring_rect(marks))


# --- the moved corners source label keeps its tap (see test_hsi.py) -----------

def _rect(t):
    return QRectF(*t)


def test_corners_tap_on_the_moved_source_label_still_cycles_navsrc(nav, qtbot):
    host, w = _hsi(qtbot, "corners")
    label = _rect(w._source_label_rect)
    _tap(qtbot, w, label.center().toPoint())
    assert nav.db.get_item("NAVSRC").value == 1.0
    assert host.encoder_control is False
