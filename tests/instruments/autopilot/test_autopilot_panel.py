#  SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for the ``autopilot_panel`` mode controller (AFC3, AER-5807).

The keys are AFC1's contract (fix-gateway ``database/autopilot.yaml``),
defined on the shared ``fix`` fixture here with the same types and tols.
Writes are asserted on the lines queued to fix-gateway, not on the local
item: a local-only set never reaches the bus (pyEfis #294).
"""

import pytest
from PyQt6.QtCore import QPoint, QPointF, QTimer, Qt
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtWidgets import QWidget

from pyefis.instruments import autopilot as ap
from pyefis.instruments import edit_focus
from pyefis.screens import screenbuilder_factory as factory
from pyefis.screens.screenbuilder_encoder import EncoderController

# key -> (dtype, min, max, initial, tol), from autopilot.yaml (AFC1).
CONTRACT = {
    "VSSEL": ("int", -30000, 30000, 0, 0),
    "IASSEL": ("float", 0.0, 999.9, 0.0, 0),
    "APCMD": ("str", None, None, "", 0),
    "APCMDSEQ": ("int", 0, 2147483647, 0, 0),
    "APENG": ("bool", None, None, False, 2000),
    "FDENG": ("bool", None, None, False, 2000),
    "YDENG": ("bool", None, None, False, 2000),
    "APLAT": ("str", None, None, "", 2000),
    "APLATARM": ("str", None, None, "", 2000),
    "APVERT": ("str", None, None, "", 2000),
    "APVERTARM": ("str", None, None, "", 2000),
    "APALTCAP": ("bool", None, None, False, 2000),
    "APCAPS": ("str", None, None, "", 2000),
    "APMSG": ("str", None, None, "", 2000),
    "APDISC": ("bool", None, None, False, 2000),
    "HEADBUG": ("float", 0.0, 359.9, 0.0, 0),
    "ALTSEL": ("int", -1000, 60000, 0, 0),
}
ALL_CAPS = "AP,FD,YD,LVL,HDG,TRK,NAV,APR,IAS,VNAV,VS,ALT,DISC"
GREEN = QColor("#00ff00")
AMBER = QColor("#ffaa00")


@pytest.fixture(autouse=True)
def _clean_registry():
    edit_focus.set_at_rest_hint(False)
    yield
    owner = edit_focus.owner()
    if owner is not None:
        owner.release_focus()
    edit_focus.set_at_rest_hint(True)


def _define(fix, keys=None):
    for key, (dtype, lo, hi, initial, tol) in CONTRACT.items():
        if keys is not None and key not in keys:
            continue
        fix.db.define_item(key, key, dtype, lo, hi, "", tol, "")
        fix.db.set_value(key, initial)
        item = fix.db.get_item(key)
        item.old = item.bad = item.fail = False


def _report(fix, **values):
    for key, value in values.items():
        fix.db.set_value(key, value)


class _Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def db(fix):
    _define(fix)
    _report(fix, APCAPS=ALL_CAPS, HEAD=271.4, VS=480.0, IAS=112.6,
            ALT=4130.0)
    fix.db.clientthread.sendqueue.put.reset_mock()
    return fix


def _panel(qtbot, parent=None, size=(600, 260), **opts):
    w = ap.AutopilotPanel(parent)
    for k, v in opts.items():
        if k == "layout":
            w.setPanelLayout(v)
        else:
            setattr(w, k, v)
    w._clock = _Clock()
    if parent is None:
        qtbot.addWidget(w)
    w.resize(*size)
    w.show()
    qtbot.waitExposed(w)
    return w


@pytest.fixture
def panel(db, qtbot):
    return _panel(qtbot)


def _sent(fix, keys=("APCMD", "APCMDSEQ")):
    out = []
    for call in fix.db.clientthread.sendqueue.put.call_args_list:
        line = call.args[0].decode().strip()
        key, value, _flags = line.split(";")
        if key in keys:
            out.append((key, value))
    return out


def _bar_pixel(panel, name):
    """The colour at the centre of the key's indicator bar, as painted."""
    btn = panel.button_widgets[name]
    img = QImage(btn.size(), QImage.Format.Format_ARGB32)
    img.fill(0)
    btn.render(img)
    c = btn.bar_rect().center()
    return QColor(img.pixel(int(c.x()), int(c.y())))


# --- DoD 1: one test per button state ---------------------------------------

def test_off_when_nothing_reported(panel):
    for name in panel.button_widgets:
        assert panel.display_state(name) == ap.OFF, name
    assert _bar_pixel(panel, "HDG") != GREEN


def test_armed_from_the_armed_lists(panel, db):
    _report(db, APLAT="HDG", APLATARM="GPS", APVERT="VS",
            APVERTARM="GS,ALT")
    assert panel.display_state("NAV") == ap.ARMED
    assert panel.display_state("APR") == ap.ARMED
    assert panel.display_state("ALT") == ap.ARMED
    # Armed is an outline: the bar's centre stays the key face, not green.
    assert _bar_pixel(panel, "NAV") != GREEN
    assert panel.button_widgets["NAV"].colors()[5] == QColor("#ffffff")


def test_active_from_the_active_modes_and_engaged_flags(panel, db):
    _report(db, APENG=True, FDENG=True, YDENG=True, APLAT="HDG",
            APVERT="VS")
    for name in ("AP", "FD", "YD", "HDG", "VS"):
        assert panel.display_state(name) == ap.ACTIVE, name
        assert _bar_pixel(panel, name) == GREEN, name
    for name in ("NAV", "APR", "IAS", "VNAV", "ALT", "LVL"):
        assert panel.display_state(name) == ap.OFF, name


def test_pending_after_a_press_with_no_state_change(panel, db):
    assert panel.press("HDG") is True
    assert panel.display_state("HDG") == ap.PENDING
    panel._clock.t += 1.9
    assert panel.display_state("HDG") == ap.PENDING


def test_press_alone_never_lights_a_key_active(panel, db):
    """The head asks, the autopilot decides: a press with no state change
    must not show the mode as flying, at any point of the pending cycle."""
    for name in list(panel.button_widgets):
        panel.press(name)
    for t in (0.0, 0.1, 1.0, 2.1, 4.9, 5.1):
        for name in panel.button_widgets:
            assert panel.display_state(name) != ap.ACTIVE, (name, t)
            assert panel.reported(name) == ap.OFF, (name, t)
            assert _bar_pixel(panel, name) != GREEN, (name, t)
        panel._clock.t += 0.1 if t < 5.0 else 0.0


def test_reported_change_ends_pending_and_lights_active(panel, db):
    panel.press("NAV")
    assert panel.display_state("NAV") == ap.PENDING
    _report(db, APLAT="GPS")
    assert panel.display_state("NAV") == ap.ACTIVE
    assert _bar_pixel(panel, "NAV") == GREEN


def test_not_taken_after_two_seconds_is_amber_with_apmsg(panel, db):
    panel.press("NAV")
    _report(db, APMSG="NO NAV SOURCE")
    panel._clock.t += ap.PENDING_S + 0.05
    assert panel.display_state("NAV") == ap.REFUSED
    face, border, _w, _label, bar_fill, bar_line = \
        panel.button_widgets["NAV"].colors()
    assert border == AMBER and bar_fill is None
    assert panel.message() == ("NO NAV SOURCE", AMBER)
    panel._clock.t += ap.REFUSED_HOLD_S
    assert panel.display_state("NAV") == ap.OFF
    assert panel.message()[0] == "NO NAV SOURCE"   # still the source's text
    assert panel.message()[1] != AMBER


def test_not_taken_without_apmsg_says_so(panel, db):
    panel.press("VNAV")
    panel._clock.t += ap.PENDING_S + 0.05
    assert panel.message() == ("VNAV NOT TAKEN", AMBER)


def test_unavailable_when_not_in_apcaps_greyed_not_hidden(panel, db):
    _report(db, APCAPS="AP,FD,HDG,NAV,ALT,VS,DISC")
    for name in ("APR", "YD", "LVL", "IAS", "VNAV"):
        assert panel.display_state(name) == ap.UNAVAILABLE, name
        assert panel.button_widgets[name].isVisible(), name
    assert panel.display_state("HDG") == ap.OFF


def test_reported_state_outranks_apcaps(panel, db):
    # The source's state is the truth even when its caps forgot the mode.
    _report(db, APCAPS="AP", APLAT="HDG")
    assert panel.display_state("HDG") == ap.ACTIVE


@pytest.mark.parametrize("flag", ["old", "bad", "fail"])
def test_no_autopilot_data_when_a_state_key_goes_stale(panel, db, flag):
    _report(db, APENG=True, APLAT="HDG")
    assert panel.display_state("AP") == ap.ACTIVE
    setattr(db.db.get_item("APLAT"), flag, True)
    for name in panel.button_widgets:
        assert panel.display_state(name) == ap.NO_DATA, name
        assert _bar_pixel(panel, name) != GREEN, name
    assert panel.message() == (ap.NO_DATA_TEXT, AMBER)
    setattr(db.db.get_item("APLAT"), flag, False)
    assert panel.display_state("AP") == ap.ACTIVE


def test_the_state_keys_include_the_health_keys():
    # The per-key tests below run over STATE_KEYS: a key dropped from it would
    # drop its test too.
    assert {"APENG", "FDENG", "YDENG", "APLAT", "APLATARM", "APVERT",
            "APVERTARM", "APALTCAP", "APCAPS", "APMSG"} <= set(ap.STATE_KEYS)


@pytest.mark.parametrize("key", ap.STATE_KEYS)
def test_every_state_key_gates_the_data(panel, db, key):
    """Per key, the health keys APCAPS and APMSG included: one key old puts
    the panel in "no autopilot data", and fresh again takes it out."""
    _report(db, APENG=True, APLAT="HDG")
    assert panel.has_data()
    db.db.get_item(key).old = True
    assert panel.display_state("AP") == ap.NO_DATA, key
    assert panel.message() == (ap.NO_DATA_TEXT, AMBER), key
    db.db.get_item(key).old = False
    assert panel.display_state("AP") == ap.ACTIVE, key


@pytest.mark.parametrize("key", ap.STATE_KEYS)
def test_one_undefined_state_key_is_no_data(fix, qtbot, key):
    _define(fix, keys=set(CONTRACT) - {key})
    _report(fix, **{k: v for k, v in (("APCAPS", ALL_CAPS), ("APENG", True))
                    if k != key})
    w = _panel(qtbot)
    assert w.display_state("AP") == ap.NO_DATA, key


def test_no_autopilot_data_when_the_gateway_lacks_the_keys(fix, qtbot):
    _define(fix, keys={"APCMD", "APCMDSEQ"})
    w = _panel(qtbot)
    assert w.display_state("AP") == ap.NO_DATA
    assert w.message()[0] == ap.NO_DATA_TEXT


def test_lvl_keeps_its_own_colour(panel):
    assert panel.button_widgets["LVL"].colors()[0] == QColor("#1f5fbf")
    assert panel.button_widgets["AP"].colors()[0] == QColor("#101418")


# --- the request wire -------------------------------------------------------

def test_press_writes_apcmd_then_bumps_apcmdseq(panel, db):
    db.db.set_value("APCMDSEQ", 41)
    db.db.clientthread.sendqueue.put.reset_mock()
    panel.press("HDG")
    panel.press("HDG")      # a second press is a second command
    assert _sent(db) == [("APCMD", "HDG"), ("APCMDSEQ", "42"),
                         ("APCMD", "HDG"), ("APCMDSEQ", "43")]


def test_press_on_a_greyed_key_still_asks(panel, db):
    _report(db, APCAPS="")
    panel.press("VNAV")
    assert _sent(db) == [("APCMD", "VNAV"), ("APCMDSEQ", "1")]


def test_counter_wraps_at_its_max(panel, db):
    db.db.set_value("APCMDSEQ", 2147483647)
    db.db.clientthread.sendqueue.put.reset_mock()
    panel.press("AP")
    assert _sent(db)[-1] == ("APCMDSEQ", "0")


def test_touch_on_a_key_writes_the_request(panel, db, qtbot):
    btn = panel.button_widgets["AP"]
    qtbot.mouseClick(btn, Qt.MouseButton.LeftButton, pos=btn.rect().center())
    assert _sent(db) == [("APCMD", "AP"), ("APCMDSEQ", "1")]


def test_no_request_keys_drops_the_press_without_raising(fix, qtbot):
    _define(fix, keys=set(CONTRACT) - {"APCMD", "APCMDSEQ"})
    w = _panel(qtbot)
    assert w.press("AP") is False


# --- DoD 2: LVL with any focus held, no confirmation ------------------------

class _Host(QWidget):
    """A screen stand-in for the EncoderController."""

    def __init__(self, timeout=10_000):
        super().__init__()
        self.instruments = {}
        self.encoder_list = []
        self.encoder_list_sorted = []
        self.encoder_current_selection = None
        self.encoder_timeout = timeout
        self.encoder_timestamp = 0
        self.encoder_control = False
        self.encoder_timer = QTimer()
        self.encoder = None
        self.encoder_button = None
        self.encoder_controller = EncoderController(self)

    def encoderChanged(self, value=0):
        self.encoder_controller.changed(value)


def _hosted(qtbot, **opts):
    host = _Host()
    qtbot.addWidget(host)
    w = _panel(qtbot, parent=host, **opts)
    host.instruments[0] = w
    host.resize(w.size())
    host.show()
    qtbot.waitExposed(host)
    host.encoder_controller.configure_inputs(None)
    return host, w


def _touch(qtbot, widget):
    qtbot.mouseClick(widget, Qt.MouseButton.LeftButton,
                     pos=widget.rect().center())


@pytest.mark.parametrize("box", ap.BOXES)
def test_lvl_writes_with_any_box_focused_and_no_confirmation(db, qtbot, box):
    host, w = _hosted(qtbot)
    ctl = host.encoder_controller
    _touch(qtbot, w.boxes[box])
    assert ctl.focused_instrument() is w and w.boxes[box].focused
    db.db.clientthread.sendqueue.put.reset_mock()
    _touch(qtbot, w.button_widgets["LVL"])
    # One press, one request, straight to the bus.
    assert _sent(db) == [("APCMD", "LVL"), ("APCMDSEQ", "1")]
    # The press also released the edit, as any touch elsewhere does.
    assert ctl.focused_instrument() is None


def test_lvl_writes_with_another_instruments_focus_held(db, qtbot):
    class _Other:
        released = 0

        def release_focus(self):
            self.released += 1
            edit_focus.release(self)

        def focus_hit(self, _pos):
            return False

    other = _Other()
    _host, w = _hosted(qtbot)
    edit_focus.claim(other)
    _touch(qtbot, w.button_widgets["LVL"])
    assert _sent(db) == [("APCMD", "LVL"), ("APCMDSEQ", "1")]
    assert other.released == 1


def test_lvl_press_ignores_focus_entirely(db, qtbot, monkeypatch):
    # press() must not consult the focus registry at all.
    _host, w = _hosted(qtbot)
    monkeypatch.setattr(edit_focus, "owner",
                        lambda: pytest.fail("press consulted focus"))
    assert w.press("LVL") is True
    assert _sent(db) == [("APCMD", "LVL"), ("APCMDSEQ", "1")]


# --- the value boxes (section 5.3) ------------------------------------------

def _value(fix, key):
    return fix.db.get_item(key).value


@pytest.mark.parametrize("box,key,start,inner,outer", [
    (ap.BOX_HDG, "HEADBUG", 350.0, 351, 1),        # wraps through 360
    (ap.BOX_VS, "VSSEL", 500, 600, 1100),
    (ap.BOX_IAS, "IASSEL", 100.0, 101.0, 106.0),
    (ap.BOX_ALT, "ALTSEL", 4500, 4600, 5600),
])
def test_inner_and_outer_steps(db, qtbot, box, key, start, inner, outer):
    db.db.set_value(key, start)
    host, w = _hosted(qtbot)
    ctl = host.encoder_controller
    _touch(qtbot, w.boxes[box])
    ctl.changed(1)
    assert _value(db, key) == inner
    ctl.outer_changed(1)
    assert _value(db, key) == outer
    sent = [v for k, v in _sent(db, keys=(key,))]
    assert len(sent) == 2   # each step reached the bus


@pytest.mark.parametrize("box,key,expected", [
    (ap.BOX_HDG, "HEADBUG", 271),
    (ap.BOX_VS, "VSSEL", 500),
    (ap.BOX_IAS, "IASSEL", 113),
    (ap.BOX_ALT, "ALTSEL", 4100),
])
def test_push_syncs_to_the_aircraft_and_ends_the_edit(db, qtbot, box, key,
                                                      expected):
    host, w = _hosted(qtbot)
    ctl = host.encoder_controller
    _touch(qtbot, w.boxes[box])
    ctl.button_changed(True)
    assert _value(db, key) == expected
    assert ctl.focused_instrument() is None


def test_push_with_no_valid_aircraft_value_keeps_focus(db, qtbot):
    db.db.get_item("VS").fail = True
    host, w = _hosted(qtbot)
    ctl = host.encoder_controller
    db.db.set_value("VSSEL", 700)
    _touch(qtbot, w.boxes[ap.BOX_VS])
    ctl.button_changed(True)
    assert _value(db, "VSSEL") == 700
    assert ctl.focused_instrument() is w


def test_ias_zero_is_unset_dashes_and_first_step_starts_from_ias(db, qtbot):
    host, w = _hosted(qtbot)
    assert w.box_text(ap.BOX_IAS) == ap.DASHES
    _touch(qtbot, w.boxes[ap.BOX_IAS])
    host.encoder_controller.changed(1)
    assert _value(db, "IASSEL") == 114.0


def test_box_text_formats(panel, db):
    _report(db, HEADBUG=5.0, VSSEL=-1200, IASSEL=120.0, ALTSEL=8500)
    assert [panel.box_text(b) for b in ap.BOXES] == \
        ["005", "-1200", "120", "8500"]
    _report(db, VSSEL=0)
    assert panel.box_text(ap.BOX_VS) == "0"


def test_vs_and_ias_both_shown_active_mode_box_accented(panel, db):
    assert panel.boxes[ap.BOX_VS].isVisible()
    assert panel.boxes[ap.BOX_IAS].isVisible()
    assert not panel.box_accent(ap.BOX_VS)
    _report(db, APVERT="IAS")
    assert panel.box_accent(ap.BOX_IAS) and not panel.box_accent(ap.BOX_VS)
    _report(db, APVERT="VS")
    assert panel.box_accent(ap.BOX_VS) and not panel.box_accent(ap.BOX_IAS)
    db.db.get_item("APVERT").old = True       # no data: no accent
    assert not panel.box_accent(ap.BOX_VS)


def test_boxes_stay_editable_with_no_autopilot_data(db, qtbot):
    db.db.get_item("APENG").old = True
    host, w = _hosted(qtbot)
    _touch(qtbot, w.boxes[ap.BOX_ALT])
    host.encoder_controller.changed(1)
    assert _value(db, "ALTSEL") == 100


def test_focus_hit_counts_only_the_focused_box(db, qtbot):
    host, w = _hosted(qtbot)
    _touch(qtbot, w.boxes[ap.BOX_VS])
    vs = w.boxes[ap.BOX_VS]
    ias = w.boxes[ap.BOX_IAS]
    assert w.edit_focus_hit(QPointF(vs.mapToGlobal(vs.rect().center())))
    assert not w.edit_focus_hit(QPointF(ias.mapToGlobal(ias.rect().center())))
    _touch(qtbot, ias)
    assert w._edit_box == ap.BOX_IAS and ias.focused and not vs.focused


def test_missing_target_key_box_shows_dashes_and_is_not_editable(fix, qtbot):
    _define(fix, keys=set(CONTRACT) - {"VSSEL"})
    w = _panel(qtbot)
    assert w.box_text(ap.BOX_VS) == ap.DASHES
    assert not w.box_editable(ap.BOX_VS)
    assert w.box_editable(ap.BOX_ALT)


# --- options and layout -----------------------------------------------------

def test_trk_hidden_by_default_and_buttons_option(panel, db):
    assert "TRK" not in panel.button_widgets
    assert set(panel.button_widgets) == set(ap.ALL_BUTTONS) - {"TRK"}
    panel.buttons = "AP,FD,HDG,NAV,TRK,ALT,VS,bogus"
    assert list(panel.button_widgets) == ["NAV", "HDG", "TRK", "AP", "FD",
                                          "VS", "ALT"]
    assert panel.buttons == "NAV,HDG,TRK,AP,FD,VS,ALT"


@pytest.mark.parametrize("layout,size", [("full", (600, 260)),
                                         ("compact", (900, 120))])
def test_layouts_place_every_part_inside_without_overlap(db, qtbot, layout,
                                                         size):
    w = _panel(qtbot, size=size, layout=layout)
    rects = [c.geometry() for c in
             list(w.boxes.values()) + list(w.button_widgets.values())]
    bounds = w.rect()
    for r in rects:
        assert r.width() > 10 and r.height() > 10
        assert bounds.contains(r)
    for i, a in enumerate(rects):
        for b in rects[i + 1:]:
            assert not a.intersects(b), (a, b)
    msg = w.message_rect().toRect()
    assert bounds.contains(msg)
    for r in rects:
        assert not msg.intersects(r)


def test_full_layout_groups_lateral_centre_vertical_left_to_right(panel):
    x = {n: b.geometry().center().x() for n, b in panel.button_widgets.items()}
    assert max(x[n] for n in ("APR", "NAV", "HDG")) \
        < min(x[n] for n in ap.CENTRE)
    assert max(x[n] for n in ap.CENTRE) < min(x[n] for n in ap.VERTICAL)
    assert panel.boxes[ap.BOX_HDG].geometry().right() \
        < panel.boxes[ap.BOX_VS].geometry().left()


def test_yaml_options_reach_the_panel_through_apply_options(db, qtbot):
    """The screen-build path, not the setter: ``layout: compact`` in screen
    YAML must switch the layout (AVIONICS-DATA found it inert on AER-5812,
    because the option landed as a plain attribute)."""
    from pyefis.screens.screenbuilder_options import apply_options

    class _Screen:
        instruments = {}
        encoder_list = []

    w = _panel(qtbot)
    _Screen.instruments = {0: w}
    apply_options(_Screen, 0, {"type": "autopilot_panel", "options": {
        "layout": "compact", "buttons": "AP,HDG", "active_color": "#00ee00"}})
    assert w.panel_layout == "compact"
    assert "layout" not in vars(w)          # QWidget.layout() not shadowed
    assert callable(w.layout)
    assert w.buttons == "HDG,AP"
    assert w.active_color == "#00ee00"


def test_unknown_layout_falls_back_to_full(panel):
    panel.setPanelLayout("sideways")
    assert panel.panel_layout == "full"


def test_registry_builds_it(db, qtbot):
    w = factory.create_instrument(None, {"type": "autopilot_panel"})
    qtbot.addWidget(w)
    assert isinstance(w, ap.AutopilotPanel)
    spec = factory.REGISTRY["autopilot_panel"]
    assert {p.name for p in spec.properties} >= {"layout", "buttons"}
    layout = next(p for p in spec.properties if p.name == "layout")
    assert layout.enum == ["full", "compact"] and layout.default == "full"


def test_stale_state_repaints_without_another_value_change(panel, db):
    """A quality-only change must reach the keys (the VSI-stuck-XXX class):
    a flag flip alone repaints the panel."""
    _report(db, APENG=True)
    calls = []
    panel.button_widgets["AP"].update = lambda *a: calls.append(1)
    db.db.get_item("APENG").old = True
    assert calls


def test_reported_state_mapping_table():
    s = ap.Snapshot(ap=True, lat="LOC", latarm="", vert="GS",
                    vertarm="", caps=ALL_CAPS)
    # A coupled ILS lights NAV (lateral LOC) and APR (vertical GS).
    assert ap.reported_state("NAV", s) == ap.ACTIVE
    assert ap.reported_state("APR", s) == ap.ACTIVE
    s = ap.Snapshot(lat="ROL", vert="LVL")
    assert ap.reported_state("LVL", s) == ap.ACTIVE
    s = ap.Snapshot(vert="VS", altcap=True)
    assert ap.reported_state("ALT", s) == ap.ARMED
    s = ap.Snapshot(lat="BC")
    assert ap.reported_state("NAV", s) == ap.ACTIVE
    assert ap.reported_state("HDG", s) == ap.OFF
