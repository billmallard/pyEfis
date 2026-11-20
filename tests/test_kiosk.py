#  SPDX-License-Identifier: GPL-2.0-or-later
"""DEMO4 (AER-5626): the demo kiosk -- DEMO marking, scripted page key with
an idle return, and the touch lock (makerplane/briefs/demo_mode_redesign.md
sections 4, 6.2 and 7)."""

import logging
from types import SimpleNamespace
from unittest import mock

import pytest
from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication, QWidget

import pyefis.hmi as hmi
import pyefis.kiosk as kiosk
from pyefis.hmi.actionclass import ActionClass
from pyefis.instruments import data_status
from pyefis.instruments import flight_plan
from pyefis.instruments.tab_section import TabSection
from tests.instruments.flight_plan.test_flight_plan import _define_all_fp1_keys, _plan
from tests.instruments.test_map_graphical_edit import _map, _paint, _tap
from tests.screens.test_font_percent_widgets import _TABS, _build


@pytest.fixture(autouse=True)
def kiosk_off():
    kiosk.configure(None)
    yield
    kiosk.configure(None)


def _demo_keys(fix, live=True, page=""):
    fix.db.define_item("DEMOLIVE", "Demo live", "bool", None, None, "", 2000, "")
    fix.db.define_item("DEMOPAGE", "Demo page", "str", None, None, "", 0, "")
    item = fix.db.get_item("DEMOLIVE")
    item.value = live
    item.bad = item.fail = item.old = False
    pg = fix.db.get_item("DEMOPAGE")
    pg.value = page
    pg.bad = pg.fail = False
    return item, pg


def _press(widget):
    ev = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(5, 5), QPointF(5, 5),
                     Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, ev)


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cfg,locked,idle", [
    (None, False, 60.0),
    ({}, False, 60.0),
    ({"enabled": False}, False, 60.0),
    ({"enabled": True}, True, 60.0),
    ({"enabled": True, "idle_return_s": 15}, True, 15.0),
    # malformed: logged, and the kiosk stays off rather than locking a panel
    ({"enabled": True, "idle_return_s": "soon"}, False, 60.0),
    ({"enabled": True, "idle_return_s": 0}, False, 60.0),
    ("yes", False, 60.0),
])
def test_configure(cfg, locked, idle):
    kiosk.configure(cfg)
    assert kiosk.locked() is locked
    assert kiosk.idle_return_s() == idle


# ---------------------------------------------------------------------------
# the lock: actions
# ---------------------------------------------------------------------------

def test_kiosk_refuses_exit_and_evaluate_and_nothing_else(qtbot, monkeypatch):
    actions = ActionClass()
    ran = []
    monkeypatch.setitem(actions.signalMap, "evaluate", ran.append)
    exits = []
    actions.doExit.connect(exits.append)
    shows = []
    actions.showScreen.connect(shows.append)

    actions.trigger("evaluate", "1")
    actions.trigger("Exit", "")
    assert ran == ["1"] and exits == [""]

    kiosk.configure({"enabled": True})
    actions.trigger("evaluate", "2")
    actions.trigger("Exit", "")
    actions.trigger("show screen", "EMS")
    assert ran == ["1"] and exits == [""]
    assert shows == ["EMS"]


# ---------------------------------------------------------------------------
# the lock: FPL page, map banner, Data Status
# ---------------------------------------------------------------------------

def _fpl(fix, qtbot):
    _define_all_fp1_keys(fix)
    hmi.initialize({})
    w = flight_plan.FlightPlan(None)
    qtbot.addWidget(w)
    w.resize(480, 320)
    w._plan = _plan(4)
    return w


def test_fpl_page_is_read_only_in_a_kiosk(fix, qtbot):
    w = _fpl(fix, qtbot)
    w.grab()
    assert "soft" in w._tap_kinds and "row" in w._tap_kinds
    assert w.enc_selectable()

    kiosk.configure({"enabled": True})
    w.grab()
    # nothing on the page takes a tap: no soft keys, no rows
    assert w._tap_targets == []
    assert not w.enc_selectable()
    # the same paint still shows the plan, not the gateway warning
    assert w._bridge.available


def test_fpl_actions_cannot_open_an_edit_page_in_a_kiosk(fix, qtbot):
    w = _fpl(fix, qtbot)
    kiosk.configure({"enabled": True})
    for page in ("dto", "catalog", "proc", "entry"):
        hmi.actions.trigger("flightplan page", page)
        assert w._page in (None, "fpl"), page
    hmi.actions.trigger("flightplan direct to", "")
    hmi.actions.trigger("flightplan direct to", "KSMX")
    w._act_create_waypoint((34.5, -120.0))
    assert w._page in (None, "fpl") and w._modal is None
    # and FPL itself is still allowed
    hmi.actions.trigger("flightplan page", "fpl")
    assert w._page == "fpl"


def test_fpl_actions_open_their_pages_outside_a_kiosk(fix, qtbot):
    # the guard above has teeth: the same calls do move the page unlocked
    w = _fpl(fix, qtbot)
    hmi.actions.trigger("flightplan page", "catalog")
    assert w._page == "catalog"
    w._act_create_waypoint((34.5, -120.0))
    assert w._page == "entry" and w._modal is not None


def test_wpt_info_on_a_user_waypoint_offers_only_close_in_a_kiosk(fix, qtbot):
    from pyefis.flightplan.waypoints import Waypoint
    w = _fpl(fix, qtbot)
    user = Waypoint(id="USR01", type="user", lat=34.5, lon=-120.0, name="x")
    w._wpt_info = user
    w.grab()
    # unlocked: Edit, Delete and Close on the user waypoint's card
    assert len(w._tap_targets) - w._enc_layer_start == 3
    kiosk.configure({"enabled": True})
    w._wpt_info = user
    w.grab()
    # locked: Close alone, and it still works
    assert [t[4] for t in w._tap_targets] == [w._close_wpt_info]
    w._tap_targets[-1][4]()
    assert w._wpt_info is None


def test_map_banner_keeps_only_info_and_close_in_a_kiosk(fix, qtbot):
    _define_all_fp1_keys(fix)
    hmi.initialize({})
    m = _map(qtbot)
    x = m._transform()
    _tap(m, x.cx + 40, x.cy)
    kiosk.configure({"enabled": True})
    _paint(m)
    names = {getattr(cb, "__name__", "") for _r, cb in m._ui_targets}
    assert {"banner_info", "clear_pointer"} <= names
    assert not names & {"banner_direct_to", "banner_insert", "banner_create_wpt"}
    sent = len(fix.db.clientthread.sendqueue.put.call_args_list)
    m.banner_direct_to()
    m.banner_insert()
    assert len(fix.db.clientthread.sendqueue.put.call_args_list) == sent


def test_data_status_update_is_off_in_a_kiosk(fix, qtbot, tmp_path):
    w = data_status.DataStatus(status_path=str(tmp_path / "none.json"))
    qtbot.addWidget(w)
    assert w.btn_update.isEnabled()
    kiosk.configure({"enabled": True})
    w = data_status.DataStatus(status_path=str(tmp_path / "none.json"))
    qtbot.addWidget(w)
    assert not w.btn_update.isEnabled()
    w._run = mock.Mock()
    w._on_update()
    w._run.assert_not_called()
    w._fail("x")                                    # a failure path re-enabling it
    assert not w.btn_update.isEnabled()


# ---------------------------------------------------------------------------
# the DEMO marking
# ---------------------------------------------------------------------------

def _window(qtbot, w=800, h=480):
    win = QWidget()
    qtbot.addWidget(win)
    win.resize(w, h)
    win.show()
    return win


def test_marking_shows_while_demolive_is_true_and_current(fix, qtbot):
    item, _ = _demo_keys(fix, live=True)
    win = _window(qtbot)
    kiosk.initialize(win, fix, [])
    m = kiosk.marking
    assert m is not None and m.isVisible()
    assert m.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    for flag in ("old", "bad", "fail"):
        setattr(item, flag, True)
        assert not m.isVisible(), flag
        setattr(item, flag, False)
        assert m.isVisible(), flag
    item.value = False
    assert not m.isVisible()
    item.value = True
    assert m.isVisible()


def test_marking_is_built_without_kiosk_mode(fix, qtbot):
    # the glass says DEMO whenever the data is the demo's, kiosk or not
    _demo_keys(fix, live=True)
    win = _window(qtbot)
    kiosk.initialize(win, fix, [])
    assert kiosk.marking is not None and kiosk.marking.isVisible()
    assert kiosk.follower is None


def test_marking_starts_hidden_on_a_never_written_key(fix, qtbot):
    fix.db.define_item("DEMOLIVE", "Demo live", "bool", None, None, "", 2000, "")
    win = _window(qtbot)
    kiosk.initialize(win, fix, [])
    assert not kiosk.marking.isVisible()


def test_marking_stays_top_centre_across_a_resize(fix, qtbot):
    _demo_keys(fix)
    win = _window(qtbot, 800, 480)
    kiosk.initialize(win, fix, [])
    g = kiosk.marking.geometry()
    assert g.top() == 0 and abs(g.center().x() - 400) <= 1
    win.resize(1024, 600)
    QApplication.processEvents()
    g = kiosk.marking.geometry()
    assert g.top() == 0 and abs(g.center().x() - 512) <= 1


def test_no_demolive_key_no_marking_and_no_raise(fix, qtbot, caplog):
    win = _window(qtbot)
    kiosk.configure({"enabled": True})
    with caplog.at_level(logging.INFO, logger="pyefis.kiosk"):
        marking, follower = kiosk.initialize(win, fix, [])
    assert marking is None and follower is None
    assert "no DEMOLIVE" in caplog.text and "no DEMOPAGE" in caplog.text


# ---------------------------------------------------------------------------
# the page follower and the idle return
# ---------------------------------------------------------------------------

class _Window(QWidget):
    def __init__(self, names):
        super().__init__()
        self.names = names
        self.shown = []

    def showScreen(self, name):
        if name not in self.names:
            raise KeyError(name)
        self.shown.append(name)


def _follower(fix, qtbot, idle_s=0.2, names=("PFD", "FPL", "EMS"), screens=(),
              page=""):
    _, page = _demo_keys(fix, page=page)
    win = _Window(list(names))
    qtbot.addWidget(win)
    kiosk.configure({"enabled": True, "idle_return_s": idle_s})
    kiosk.initialize(win, fix, list(screens))
    assert kiosk.follower is not None
    return win, page


def test_the_page_key_is_ignored_outside_kiosk_mode(fix, qtbot):
    _, page = _demo_keys(fix)
    win = _Window(["PFD", "FPL"])
    qtbot.addWidget(win)
    kiosk.initialize(win, fix, [])
    page.value = "FPL"
    assert win.shown == [] and kiosk.follower is None


def test_it_follows_the_script_page(fix, qtbot):
    win, page = _follower(fix, qtbot)
    page.value = "FPL"
    page.value = "EMS"
    assert win.shown == ["FPL", "EMS"]


def test_it_joins_the_script_page_already_set_at_start(fix, qtbot):
    # DEMO11 (AER-6005): a pyEfis restart mid-script reads DEMOPAGE before the
    # follower exists, so no change signal ever arrives for that page.
    win, page = _follower(fix, qtbot, page="FPL")
    assert win.shown == ["FPL"]
    page.value = "EMS"
    assert win.shown == ["FPL", "EMS"]


def test_it_joins_the_script_tab_already_set_at_start(fix, qtbot):
    hmi.initialize({})
    section = _build(qtbot, "tab_section", tabs=_TABS)
    screen = SimpleNamespace(name="EMS", object=section.parentWidget())
    win, _ = _follower(fix, qtbot, screens=[screen], page="EMS/nav")
    assert win.shown == ["EMS"]
    assert section.stack.currentIndex() == 1


def test_a_reconnect_with_the_same_page_rejoins_the_script(fix, qtbot):
    # pyavtools marks every item failed on a disconnect and re-reads it on
    # reconnect; an unchanged value comes back as fail clearing, no valueChanged.
    win, page = _follower(fix, qtbot, page="FPL")
    page.fail = True
    assert win.shown == ["FPL"]       # going failed does not move the panel
    page.fail = False
    assert win.shown == ["FPL", "FPL"]


def test_a_reconnect_does_not_break_a_touch_hold(fix, qtbot):
    win, page = _follower(fix, qtbot, idle_s=0.3, page="FPL")
    _press(win)
    page.fail = True
    page.fail = False
    assert win.shown == ["FPL"]
    assert kiosk.follower.holding()


def test_a_touch_holds_the_panel_then_it_rejoins_the_script(fix, qtbot):
    win, page = _follower(fix, qtbot, idle_s=0.3)
    page.value = "FPL"
    _press(win)                       # the attendee taps
    page.value = "EMS"                # the script moves on: held
    assert win.shown == ["FPL"]
    assert kiosk.follower.holding()
    qtbot.waitUntil(lambda: not kiosk.follower.holding(), timeout=2000)
    # idle ran out: back to where the script is NOW
    assert win.shown == ["FPL", "EMS"]


def test_every_touch_restarts_the_idle_time(fix, qtbot):
    win, page = _follower(fix, qtbot, idle_s=0.3)
    _press(win)
    page.value = "EMS"
    for _ in range(3):
        qtbot.wait(150)
        _press(win)
    assert win.shown == []            # 0.45 s of touches > one idle time
    qtbot.waitUntil(lambda: win.shown == ["EMS"], timeout=2000)


def test_idle_return_with_no_script_page_does_nothing(fix, qtbot):
    win, page = _follower(fix, qtbot, idle_s=0.1)
    _press(win)
    qtbot.wait(300)
    assert win.shown == []


def test_an_unknown_screen_is_logged_once_and_ignored(fix, qtbot, caplog):
    win, page = _follower(fix, qtbot)
    with caplog.at_level(logging.WARNING, logger="pyefis.kiosk"):
        page.value = "NOPE"
        page.value = "PFD"
        page.value = "NOPE"
    assert win.shown == ["PFD"]
    assert len([r for r in caplog.records if "NOPE" in r.getMessage()]) == 1


def test_screen_slash_tab_brings_the_tab_forward(fix, qtbot):
    hmi.initialize({})
    section = _build(qtbot, "tab_section", tabs=_TABS)
    assert isinstance(section, TabSection)
    assert section.stack.currentIndex() == 0
    screen = SimpleNamespace(name="EMS", object=section.parentWidget())
    win, page = _follower(fix, qtbot, screens=[screen])
    page.value = "EMS/nav"
    assert win.shown == ["EMS"]
    assert section.stack.currentIndex() == 1 and section.tab_bar.currentIndex() == 1
    page.value = "EMS/Engine"
    assert section.stack.currentIndex() == 0


def test_tab_section_show_tab_labelled(fix, qtbot):
    hmi.initialize({})
    section = _build(qtbot, "tab_section", tabs=_TABS)
    assert section.show_tab_labelled(" NAV ")
    assert section.stack.currentIndex() == 1
    assert not section.show_tab_labelled("Map")
    assert section.stack.currentIndex() == 1


# ---------------------------------------------------------------------------
# the visitor reset (DEMO12, AER-6077): brief 6.2's settings go back to the
# show defaults each loop, when the demo goes live, and on the idle return
# ---------------------------------------------------------------------------

SHOW = {"NAVSRC": 2, "BARO": 29.92, "ALTSEL": 3000, "MAPRANGE": 2}
# what a visitor leaves behind: VLOC, a fat-fingered baro, a bug, 80 NM
VISITOR = {"NAVSRC": 0.0, "BARO": 30.41, "ALTSEL": 9500, "MAPRANGE": 5}
_KEY_DEFS = {"NAVSRC": ("float", 0.0, 3.0), "BARO": ("float", 0.0, 35.0),
             "ALTSEL": ("int", -1000, 60000), "MAPRANGE": ("int", 0, 7)}
VISITOR_KEYS_ALL = tuple(_KEY_DEFS)


def _visitor_keys(fix, monkeypatch, keys=VISITOR_KEYS_ALL):
    for key in keys:
        dtype, lo, hi = _KEY_DEFS[key]
        fix.db.define_item(key, key, dtype, lo, hi, "", 0, "")
        it = fix.db.get_item(key)
        it.value = VISITOR[key]
        it.old = it.bad = it.fail = False
    sent = []
    monkeypatch.setattr(fix.db, "queue_out", lambda b: sent.append(b.decode()))
    return sent


def _loop_key(fix, n=1):
    fix.db.define_item("DEMOLOOP", "Demo pass", "int", 0, 1000000, "", 0, "")
    loop = fix.db.get_item("DEMOLOOP")
    loop.value = n
    loop.bad = loop.fail = False
    return loop


def _resetter(fix, qtbot, monkeypatch, live=True, loop=True, defaults=SHOW,
              idle_s=60, keys=VISITOR_KEYS_ALL):
    sent = _visitor_keys(fix, monkeypatch, keys)
    live_item, _ = _demo_keys(fix, live=live, page="PFD")
    loop_item = _loop_key(fix) if loop else None
    win = _Window(["PFD", "EMS"])
    qtbot.addWidget(win)
    kiosk.configure({"enabled": True, "idle_return_s": idle_s, "defaults": defaults})
    kiosk.initialize(win, fix, [])
    return win, live_item, loop_item, sent


def _values(fix, keys=VISITOR_KEYS_ALL):
    return {k: fix.db.get_item(k).value for k in keys}


def _visit(fix, keys=VISITOR_KEYS_ALL):
    for k in keys:
        fix.db.get_item(k).value = VISITOR[k]


@pytest.mark.parametrize("cfg,want", [
    (None, {}),
    ({"NAVSRC": 2, "BARO": "29.92"}, {"NAVSRC": 2.0, "BARO": 29.92}),
    # not a visitor key: the demo's or an engine's, never a kiosk default
    ({"LAT": 34.0, "COURSE": 90, "FPLSEQ": 1, "MAPRANGE": 2}, {"MAPRANGE": 2.0}),
    ({"BARO": "low", "ALTSEL": None, "NAVSRC": True, "MAPRANGE": 3}, {"MAPRANGE": 3.0}),
    (["NAVSRC", 2], {}),
])
def test_configure_defaults(cfg, want, caplog):
    with caplog.at_level(logging.ERROR, logger="pyefis.kiosk"):
        kiosk.configure({"enabled": True, "defaults": cfg})
    assert kiosk.defaults() == want
    assert kiosk.locked()             # a bad default never unlocks the panel
    dropped = (len(cfg) - len(want)) if isinstance(cfg, dict) else int(cfg is not None)
    assert len(caplog.records) == dropped


def test_visitor_keys_are_the_brief_6_2_settings():
    assert kiosk.VISITOR_KEYS == ("NAVSRC", "BARO", "ALTSEL", "MAPRANGE")


@pytest.mark.parametrize("key", list(_KEY_DEFS))
def test_each_visitor_key_goes_back_to_its_show_default_at_the_next_loop(fix, qtbot, monkeypatch, key):
    _, _, loop, sent = _resetter(fix, qtbot, monkeypatch, defaults={key: SHOW[key]})
    _visit(fix)
    sent.clear()
    loop.value = 2                    # the demo starts its next pass
    assert fix.db.get_item(key).value == pytest.approx(SHOW[key])
    # sent to fix-gateway, not only set here (pyEfis #294)
    assert [s.split(";")[:2] for s in sent if s.startswith(key + ";")]
    assert float(sent[-1].split(";")[1]) == pytest.approx(SHOW[key])
    # the others were not configured, so they keep the visitor's value
    others = [k for k in _KEY_DEFS if k != key]
    assert _values(fix, others) == pytest.approx({k: VISITOR[k] for k in others})


def test_a_vloc_tap_through_the_hsi_reverts_at_the_next_loop(fix, qtbot, monkeypatch):
    from pyefis.instruments.hsi import HSI
    _, _, loop, sent = _resetter(fix, qtbot, monkeypatch)
    fix.db.get_item("NAVSRC").value = 2.0
    HSI._send_key("NAVSRC", 0.0)      # the HSI source tab's own write
    assert fix.db.get_item("NAVSRC").value == 0.0
    assert sent[-1].startswith("NAVSRC;0.0;")
    before = len(sent)
    loop.value = 2
    assert fix.db.get_item("NAVSRC").value == 2.0
    assert any(s.startswith("NAVSRC;2.0;") for s in sent[before:])


def test_every_loop_resets_not_only_the_first(fix, qtbot, monkeypatch):
    _, _, loop, _ = _resetter(fix, qtbot, monkeypatch)
    for n in (2, 3, 4):
        _visit(fix)
        loop.value = n
        assert _values(fix) == pytest.approx(SHOW)
    assert kiosk.resetter.resets == 1 + 3      # the start, then each loop


def test_the_demo_going_live_resets(fix, qtbot, monkeypatch):
    _, live, _, _ = _resetter(fix, qtbot, monkeypatch, live=False)
    assert _values(fix) == pytest.approx(VISITOR)
    live.value = True
    assert _values(fix) == pytest.approx(SHOW)


def test_the_demo_coming_back_after_going_old_resets(fix, qtbot, monkeypatch):
    # a gateway restart: DEMOLIVE stays true locally, goes old, then current
    _, live, _, _ = _resetter(fix, qtbot, monkeypatch)
    _visit(fix)
    live.old = True
    assert _values(fix) == pytest.approx(VISITOR)
    live.old = False
    assert _values(fix) == pytest.approx(SHOW)


def test_the_once_a_second_demolive_refresh_does_not_reset(fix, qtbot, monkeypatch):
    _, live, _, _ = _resetter(fix, qtbot, monkeypatch)
    _visit(fix)
    for _ in range(3):
        live.value = True
        live.old = False
        # and if a client ever signals a same-value write, still no reset
        live.valueChanged[bool].emit(True)
        live.oldChanged.emit(False)
    assert _values(fix) == pytest.approx(VISITOR)


def test_a_pyefis_start_with_the_demo_running_resets_at_once(fix, qtbot, monkeypatch):
    # state_persist brought NAVSRC back as the last visitor left it
    _resetter(fix, qtbot, monkeypatch)
    assert _values(fix) == pytest.approx(SHOW)


def test_nothing_is_written_while_the_demo_is_not_live(fix, qtbot, monkeypatch):
    _, live, loop, sent = _resetter(fix, qtbot, monkeypatch, live=False)
    loop.value = 2
    kiosk.resetter.idle_return()
    assert _values(fix) == pytest.approx(VISITOR)
    assert not [s for s in sent if s.split(";")[0] in VISITOR]


def test_the_idle_return_resets(fix, qtbot, monkeypatch):
    win, _, _, _ = _resetter(fix, qtbot, monkeypatch, idle_s=0.2)
    _visit(fix)
    _press(win)
    assert _values(fix) == pytest.approx(VISITOR)
    qtbot.waitUntil(lambda: not kiosk.follower.holding(), timeout=2000)
    assert _values(fix) == pytest.approx(SHOW)
    assert win.shown[-1] == "PFD"     # and it rejoined the script page


def test_without_demoloop_it_resets_when_the_demo_goes_live(fix, qtbot, monkeypatch, caplog):
    with caplog.at_level(logging.WARNING, logger="pyefis.kiosk"):
        _, live, _, _ = _resetter(fix, qtbot, monkeypatch, live=False, loop=False)
    assert any("DEMOLOOP" in r.getMessage() for r in caplog.records)
    assert kiosk.resetter is not None
    live.value = True
    assert _values(fix) == pytest.approx(SHOW)


def test_a_visitor_key_the_database_lacks_is_said_once_and_skipped(fix, qtbot, monkeypatch, caplog):
    keys = ("NAVSRC", "BARO", "ALTSEL")
    with caplog.at_level(logging.WARNING, logger="pyefis.kiosk"):
        _, _, loop, _ = _resetter(fix, qtbot, monkeypatch, keys=keys)
    assert [r.getMessage() for r in caplog.records].count(
        "kiosk: the database has no MAPRANGE; it is not reset") == 1
    _visit(fix, keys)
    loop.value = 2
    assert _values(fix, keys) == pytest.approx({k: SHOW[k] for k in keys})


def test_no_reset_without_defaults_or_outside_kiosk_mode(fix, qtbot, monkeypatch):
    _, _, loop, _ = _resetter(fix, qtbot, monkeypatch, defaults=None)
    assert kiosk.resetter is None
    kiosk.configure({"enabled": False, "defaults": SHOW})
    kiosk.initialize(_Window([]), fix, [])
    assert kiosk.resetter is None
    loop.value = 5
    assert _values(fix) == pytest.approx(VISITOR)
