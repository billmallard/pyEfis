#  SPDX-License-Identifier: GPL-2.0-or-later
"""The CAS window, marker, full list and CAS NOT SHOWN cue (CAS3,
docs/cas_widget_spec.md).

Each test names the requirement it verifies. Paint is asserted per row on a
real grab; writes are asserted on the bytes queued to fix-gateway.
"""

import logging

import pytest
from PyQt6.QtCore import QPointF, QRect, Qt
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtWidgets import QWidget

from pyefis import fix_watchdog
from pyefis.instruments import cas
from pyefis.instruments import tile as tiles
from pyefis.instruments.cas import model as cm
from tests.instruments.cas.conftest import Clock, sent

RED = QColor("#ff0000")
AMBER = QColor("#ffaa00")
WHITE = QColor("#ffffff")

#: A time in the flash's "on" and "off" half-periods (tile.BLINK_HALF_S 0.5).
ON, OFF = 2000.1, 2000.6


def _model(clock):
    import pyavtools.fix as fix
    m = cm.CASModel(lambda k: fix.db.get_item(k, wait=False), clock=clock)
    clock.t += cm.BOOT_GRACE_S
    m.poll()
    return cas.PolledModel(m, clock=clock)


def _window(qtbot, clock, lines=4, w=320, h=128, model=None):
    widget = cas.CASWindow(model=model or _model(clock), clock=clock)
    widget.lines = lines
    qtbot.addWidget(widget)
    widget.resize(w, h)
    return widget


def _marker(qtbot, clock, model=None):
    widget = cas.CASMarker(model=model or _model(clock), clock=clock)
    qtbot.addWidget(widget)
    widget.resize(160, 40)
    return widget


def _grab(widget, t, clock):
    clock.t = t
    widget._polled._at = None
    widget.refresh()
    return widget.grab().toImage().convertToFormat(QImage.Format.Format_RGB32)


def _count(img, color, rect=None, tol=24):
    rect = rect or img.rect()
    n = 0
    for y in range(rect.top(), rect.bottom() + 1, 2):
        for x in range(rect.left(), rect.right() + 1, 2):
            c = img.pixelColor(x, y)
            if (abs(c.red() - color.red()) <= tol
                    and abs(c.green() - color.green()) <= tol
                    and abs(c.blue() - color.blue()) <= tol):
                n += 1
    return n


def _row(widget, i):
    r = widget.row_rects()[i].toRect()
    return QRect(r.left() + 2, r.top() + 2, r.width() - 4, r.height() - 4)


# -- CASW-WIN-001 --------------------------------------------------------------

def test_quiet_window_draws_nothing(cas_db, qtbot):
    """CASW-WIN-001 (brief 6.2, bench step 1): no message, no pixel of any
    level colour and no fill; the window costs no glass in normal flight."""
    cas_db([])
    clock = Clock()
    w = _window(qtbot, clock)
    img = _grab(w, ON, clock)
    assert w.rows() == []
    for color in (RED, AMBER):
        assert _count(img, color) == 0
    blank = QWidget()
    qtbot.addWidget(blank)
    blank.resize(w.size())
    assert img == blank.grab().toImage().convertToFormat(QImage.Format.Format_RGB32)


# -- CASW-WIN-002 --------------------------------------------------------------

def test_each_line_is_drawn_in_its_level_colour(cas_db, qtbot):
    """CASW-WIN-002 (brief 6.2, R10): warning red, caution amber, advisory
    white, each in its own row and in no other."""
    cas_db(["3|1|W|WARN LINE|", "2|1|C|CAUT LINE|", "1|1|A|ADV LINE|"])
    clock = Clock()
    w = _window(qtbot, clock, lines=3, h=96)
    img = _grab(w, ON, clock)
    assert _count(img, RED, _row(w, 0)) > 40
    assert _count(img, AMBER, _row(w, 1)) > 40
    assert _count(img, WHITE, _row(w, 2)) > 20
    assert _count(img, RED, _row(w, 1)) == _count(img, RED, _row(w, 2)) == 0
    assert _count(img, AMBER, _row(w, 0)) == _count(img, AMBER, _row(w, 2)) == 0


def test_level_colours_follow_the_options(cas_db, qtbot):
    """CASW-WIN-002: the colour props drive the drawn colour (style contract:
    a builder may override per widget)."""
    cas_db(["2|1|C|CAUT LINE|"])
    clock = Clock()
    w = _window(qtbot, clock, lines=1, h=40)
    w.caution_color = "#00ccff"
    img = _grab(w, ON, clock)
    assert _count(img, QColor("#00ccff"), _row(w, 0)) > 40
    assert _count(img, AMBER, _row(w, 0)) == 0


# -- CASW-WIN-003 --------------------------------------------------------------

def test_unacknowledged_line_flashes_and_acknowledged_is_steady(cas_db, qtbot):
    """CASW-WIN-003 (brief 6.2, R5): the unacknowledged row differs between
    the flash phases; the acknowledged row is identical in both. The text
    stays readable: the level colour is present in both phases."""
    cas_db(["2|0|NEW|NEW CAUTION|", "2|1|OLD|OLD CAUTION|"])
    clock = Clock()
    w = _window(qtbot, clock, lines=2, h=64)
    on, off = _grab(w, ON, clock), _grab(w, OFF, clock)
    r0, r1 = _row(w, 0), _row(w, 1)
    assert on.copy(r0) != off.copy(r0)
    assert on.copy(r1) == off.copy(r1)
    assert _count(on, AMBER, r0) > 0 and _count(off, AMBER, r0) > 0


def test_flash_is_in_phase_across_widgets(cas_db, qtbot):
    """CASW-WIN-003 (AC 25.1322-1: flashing alerts flash in sync): a window
    and a marker built at different times share the clock's phase."""
    cas_db(["3|0|W|WARN LINE|"])
    clock = Clock()
    pm = _model(clock)
    w = _window(qtbot, clock, lines=1, h=40, model=pm)
    clock.t += 0.3
    m = _marker(qtbot, clock, model=pm)
    for t in (ON, OFF):
        wi, mi = _grab(w, t, clock), _grab(m, t, clock)
        r = _row(w, 0)
        filled_w = _count(wi, RED, r) > 0.5 * (r.width() * r.height() / 4)
        filled_m = _count(mi, RED) > 0.5 * (mi.width() * mi.height() / 4)
        assert filled_w == filled_m == tiles.blink_on(t)


# -- CASW-WIN-004 --------------------------------------------------------------

def test_overflow_shows_plus_k_in_the_most_urgent_hidden_colour(cas_db, qtbot):
    """CASW-WIN-004 (brief 6.3, bench step 11): five messages in three lines:
    two lines and +3, coloured as the most urgent hidden line (a caution)."""
    cas_db(["3|0|W1|W ONE|", "3|0|W2|W TWO|", "2|0|C1|C ONE|",
            "1|0|A1|A ONE|", "1|0|A2|A TWO|"])
    clock = Clock()
    w = _window(qtbot, clock, lines=3, h=96)
    rows = w.rows()
    assert [(t.text, kind) for t, kind in rows] == [
        ("W ONE", "line"), ("W TWO", "line"), ("+3", "more")]
    assert rows[2][0].level == tiles.CAUTION
    img = _grab(w, ON, clock)
    assert _count(img, AMBER, _row(w, 2)) > 20


def test_overflow_counts_messages_beyond_the_slots(cas_db, qtbot):
    """CASW-WIN-004: CASCNT 15 with twelve slots: +k counts all fifteen."""
    cas_db(["1|0|A{}|ADV {}|".format(i, i) for i in range(12)], count=15)
    clock = Clock()
    w = _window(qtbot, clock, lines=4)
    assert w.rows()[-1][0].text == "+12"


def test_exactly_full_window_has_no_plus_k(cas_db, qtbot):
    """CASW-WIN-004: as many messages as lines: every one shown, no +k."""
    cas_db(["2|0|C{}|C {}|".format(i, i) for i in range(4)])
    clock = Clock()
    w = _window(qtbot, clock, lines=4)
    assert [kind for _, kind in w.rows()] == ["line"] * 4


# -- CASW-ACK-001 (widget) / CASW-WIN-005 --------------------------------------

def test_touch_acknowledges_with_the_drawn_sequence(cas_db, qtbot):
    """CASW-ACK-001 (brief 6.5, bench step 3): a touch on the window writes
    CASACK = the CASSEQ drawn, to the gateway."""
    seq = cas_db(["2|0|NAVFAIL|NAV FAIL|"], seq=57)
    clock = Clock()
    w = _window(qtbot, clock)
    _grab(w, ON, clock)
    assert w.press(5.0) == "ack"
    assert sent(cas_db.fix) == [("CASACK", str(seq))]


def test_touch_with_nothing_to_acknowledge_opens_the_list(cas_db, qtbot):
    """CASW-WIN-005 (brief 6.1): everything acknowledged: a touch writes
    nothing and opens the full list."""
    cas_db(["2|1|NAVFAIL|NAV FAIL|"])
    clock = Clock()
    host = QWidget()
    qtbot.addWidget(host)
    host.resize(800, 480)
    w = cas.CASWindow(host, model=_model(clock), clock=clock)
    w.resize(320, 128)
    assert w.press(5.0) == "list"
    assert sent(cas_db.fix) == []
    assert isinstance(host._cas_list, cas.CASList)


def test_plus_k_opens_the_list_and_the_list_acknowledges_then_closes(
        cas_db, qtbot):
    """CASW-WIN-005, CASW-ACK-001 (brief 6.3): a touch on +k opens the list
    without acknowledging; on the list a touch acknowledges, the next one
    closes it."""
    seq = cas_db(["2|0|C{}|C {}|".format(i, i) for i in range(6)])
    clock = Clock()
    host = QWidget()
    qtbot.addWidget(host)
    host.resize(800, 480)
    w = cas.CASWindow(host, model=_model(clock), clock=clock)
    w.lines = 3
    w.resize(320, 96)
    assert w.press(80.0) == "list"
    assert sent(cas_db.fix) == []
    lst = host._cas_list
    assert [t.text for t, _ in lst.rows()] == ["C {}".format(i)
                                               for i in range(6)]
    assert lst.press() == "ack"
    assert sent(cas_db.fix) == [("CASACK", str(seq))]
    cas_db(["2|1|C{}|C {}|".format(i, i) for i in range(6)])
    w._polled._at = None
    lst.refresh()
    assert lst.press() == "close"


def test_list_closes_and_reopens_and_survives_its_host(cas_db, qtbot):
    """CASW-WIN-005: closing the list forgets it, a later touch opens a new
    one, and deleting the host window with a list open does not crash (the
    list once reset its host from the destroyed signal, mid-destruction)."""
    cas_db(["2|1|NAVFAIL|NAV FAIL|"])
    clock = Clock()
    host = QWidget()
    host.resize(800, 480)
    m = cas.CASMarker(host, model=_model(clock), clock=clock)
    first = m.open_full_list()
    first.close()
    assert host._cas_list is None
    second = m.open_full_list()
    assert second is not first and host._cas_list is second
    host.deleteLater()
    qtbot.wait(50)


def test_touch_on_a_quiet_window_does_nothing(cas_db, qtbot):
    """CASW-WIN-005: a quiet window and marker are transparent to touch, so a
    tap reaches what they overlay; with a message they take the touch."""
    cas_db([])
    clock = Clock()
    pm = _model(clock)
    w = _window(qtbot, clock, model=pm)
    m = _marker(qtbot, clock, model=pm)
    for wdg in (w, m):
        _grab(wdg, ON, clock)
        assert wdg.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert w.press(5.0) is None
    assert sent(cas_db.fix) == []
    cas_db(["1|0|A|ADV|"])
    for wdg in (w, m):
        _grab(wdg, ON, clock)
        assert not wdg.testAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents)


def test_touch_during_link_loss_writes_nothing(cas_db, qtbot, monkeypatch):
    """CASW-ACK-001, CASW-STALE-001: link lost: the touch acknowledges
    GATEWAY LINK LOST locally and writes no CASACK."""
    cas_db(["2|0|NAVFAIL|NAV FAIL|"])
    import pyavtools.fix as fix
    clock = Clock()
    lost = {"v": True}
    m = cm.CASModel(lambda k: fix.db.get_item(k, wait=False),
                    link_lost=lambda: lost["v"], clock=clock)
    pm = cas.PolledModel(m, clock=clock)
    w = _window(qtbot, clock, model=pm)
    assert [t.text for t, _ in w.rows()] == ["GATEWAY LINK LOST"]
    assert w.press(5.0) == "ack"
    assert sent(cas_db.fix) == []
    assert m.messages()[0].acked


# -- CASW-MRK-001 --------------------------------------------------------------

@pytest.mark.parametrize("slots,text,color", [
    (["3|1|W|W|", "1|0|A|A|"], "WARNING", RED),
    (["2|1|C|C|"], "CAUTION", AMBER),
    (["1|1|A|A|"], "ADVISORY", WHITE),
])
def test_marker_names_and_colours_the_highest_level(cas_db, qtbot, slots,
                                                    text, color):
    """CASW-MRK-001 (brief 6.1): the marker shows the highest active level, in
    its colour and as a word, so the level does not rest on colour alone."""
    cas_db(slots)
    clock = Clock()
    m = _marker(qtbot, clock)
    t = m.marker_tile()
    assert t.text == text
    assert _count(_grab(m, ON, clock), color) > 20


def test_marker_flashes_while_anything_is_unacknowledged(cas_db, qtbot):
    """CASW-MRK-001: an unacknowledged advisory under an acknowledged warning
    still flashes the marker (something new is waiting)."""
    cas_db(["3|1|W|W|", "1|0|A|A|"])
    clock = Clock()
    m = _marker(qtbot, clock)
    assert m.marker_tile().flash
    assert _grab(m, ON, clock) != _grab(m, OFF, clock)
    cas_db(["3|1|W|W|", "1|1|A|A|"])
    _grab(m, ON, clock)
    assert not m.marker_tile().flash
    assert _grab(m, ON, clock) == _grab(m, OFF, clock)


def test_quiet_marker_draws_nothing_and_ignores_a_touch(cas_db, qtbot):
    """CASW-MRK-001: no message: empty, and a touch passes through."""
    cas_db([])
    clock = Clock()
    m = _marker(qtbot, clock)
    img = _grab(m, ON, clock)
    assert m.marker_tile() is None
    blank = QWidget()
    qtbot.addWidget(blank)
    blank.resize(m.size())
    assert img == blank.grab().toImage().convertToFormat(QImage.Format.Format_RGB32)
    assert m.press() is None


def test_marker_touch_opens_the_list_without_acknowledging(cas_db, qtbot):
    """CASW-MRK-001, CASW-WIN-005: the pilot has not read the text yet, so a
    touch on the marker opens the list and acknowledges nothing."""
    cas_db(["2|0|NAVFAIL|NAV FAIL|"])
    clock = Clock()
    host = QWidget()
    qtbot.addWidget(host)
    host.resize(800, 480)
    m = cas.CASMarker(host, model=_model(clock), clock=clock)
    m.resize(160, 40)
    assert m.press() == "list"
    assert sent(cas_db.fix) == []
    assert isinstance(host._cas_list, cas.CASList)


# -- CASW-STALE-001 (widget) ---------------------------------------------------

def test_window_drops_the_old_list_when_the_plugin_stops(cas_db, qtbot):
    """CASW-STALE-001 (bench step 16): two messages shown; every CAS key goes
    old; the window shows CAS FAIL only, and the marker turns amber."""
    cas_db(["3|0|APLINK|AP LINK LOST|", "2|0|NAVFAIL|NAV FAIL|"])
    clock = Clock()
    pm = _model(clock)
    w = _window(qtbot, clock, model=pm)
    mk = _marker(qtbot, clock, model=pm)
    assert [t.text for t, _ in w.rows()] == ["AP LINK LOST", "NAV FAIL"]
    for key in cm.LIST_KEYS:
        cas_db.flag(key, old=True)
    pm._at = None
    w.refresh()
    assert [t.text for t, _ in w.rows()] == ["CAS FAIL"]
    assert mk.marker_tile().text == "CAUTION"
    img = _grab(w, ON, clock)
    assert _count(img, RED) == 0


# -- CASW-LOC-001: the watchdog seam -------------------------------------------

def test_link_lost_reads_the_running_watchdog(monkeypatch):
    """CASW-LOC-001: link_lost() is the running watchdog's trip state, and
    False with no watchdog (LINK MON OFF covers that case)."""
    class W:
        tripped = False
    monkeypatch.setattr(fix_watchdog, "running", None)
    assert fix_watchdog.link_lost() is False
    w = W()
    monkeypatch.setattr(fix_watchdog, "running", w)
    assert fix_watchdog.link_lost() is False
    w.tripped = True
    assert fix_watchdog.link_lost() is True


def test_start_records_the_running_watchdog(fix, monkeypatch):
    """CASW-LOC-001: start() keeps the watchdog it started, and None when it
    could not start one."""
    monkeypatch.setattr(fix_watchdog, "running", "stale")
    fix.db.define_item("PITCH", "Pitch", "float", -90, 90, "deg", 200, "")
    wd = fix_watchdog.start(fix.db, {"FixLinkTimeout": 2.0})
    try:
        assert fix_watchdog.running is wd and wd is not None
    finally:
        wd.stop()
    assert fix_watchdog.start(fix.db, {"FixLinkTimeout": 0}) is None
    assert fix_watchdog.running is None


# -- CASW-LOC-004: CAS NOT SHOWN -----------------------------------------------

class _Scr:
    def __init__(self, name, obj):
        self.name = name
        self.object = obj


def test_cas_surfaces_counts_windows_and_markers_per_screen(cas_db, qtbot):
    """CASW-LOC-004: the coverage count finds CAS windows and markers by the
    class attribute, on every screen, nested or not."""
    from pyefis import gui
    clock = Clock()
    pfd, ems, empty = QWidget(), QWidget(), QWidget()
    for wdg in (pfd, ems, empty):
        qtbot.addWidget(wdg)
    cas.CASWindow(pfd, model=_model(clock), clock=clock)
    inner = QWidget(ems)
    cas.CASMarker(inner, model=_model(clock), clock=clock)
    counts = gui.cas_surfaces([_Scr("PFD", pfd), _Scr("EMS", ems),
                               _Scr("MAP", empty)])
    assert counts == {"PFD": 1, "EMS": 1, "MAP": 0}


def test_no_surface_and_live_keys_shows_cas_not_shown(cas_db, qtbot, caplog):
    """CASW-LOC-004 (bench step 14, C2): no screen carries a window or a
    marker and the CAS keys are live: the cue shows and an error is logged."""
    from pyefis import gui
    cas_db([])
    main = QWidget()
    qtbot.addWidget(main)
    main.resize(800, 480)
    watch = gui._CASCoverageWatch(main, {"PFD": 0, "EMS": 0})
    with caplog.at_level(logging.ERROR):
        watch.check()
    cue = watch.cue
    assert isinstance(cue, cas.CASNotShownCue) and cue.active
    assert "CAS NOT SHOWN" in caplog.text
    img = cue.grab().toImage()
    assert _count(img.convertToFormat(QImage.Format.Format_RGB32), WHITE) > 20


def test_no_cue_when_cas_is_not_live(fix, qtbot):
    """CASW-LOC-004: a gateway without the CAS keys has no CAS to show: no
    cue, and the check keeps waiting."""
    from pyefis import gui
    cas.reset_shared_model()
    main = QWidget()
    qtbot.addWidget(main)
    watch = gui._CASCoverageWatch(main, {"PFD": 0})
    watch.check()
    assert watch.cue is None and watch._timer.isActive()


def test_no_cue_while_the_cas_keys_are_old(cas_db, qtbot):
    """CASW-LOC-004: the keys defined but old (plugin off) is not "live": no
    cue yet; it appears once they are good."""
    from pyefis import gui
    cas_db([])
    cas_db.flag("CASSEQ", old=True)
    main = QWidget()
    qtbot.addWidget(main)
    watch = gui._CASCoverageWatch(main, {"PFD": 0})
    watch.check()
    assert watch.cue is None and watch._timer.isActive()
    cas_db.flag("CASSEQ", old=False)
    watch.check()
    assert watch.cue is not None


def test_one_surface_anywhere_means_no_cue_and_logs_bare_screens(
        cas_db, qtbot, caplog):
    """CASW-LOC-004: one window anywhere: no cue; each other flight screen
    without one is logged as a warning (R13), data status and About not."""
    from pyefis import gui
    main = QWidget()
    qtbot.addWidget(main)
    with caplog.at_level(logging.WARNING):
        watch = gui._CASCoverageWatch(main, {"PFD": 1, "EMS": 0,
                                             "DataStatus": 0, "About": 0})
    assert watch._timer is None
    assert "screen EMS has no cas_window" in caplog.text
    assert "DataStatus" not in caplog.text and "About" not in caplog.text


# -- CASW-REG-001 --------------------------------------------------------------

@pytest.mark.parametrize("type_,cls", [("cas_window", cas.CASWindow),
                                       ("cas_marker", cas.CASMarker)])
def test_registered_type_builds_and_takes_yaml_options(cas_db, qtbot, type_,
                                                       cls):
    """CASW-REG-001: each type is a registered InstrumentSpec; the screen-build
    path (builder, then apply_options with the YAML shape) reaches the
    widget, including a quoted scalar."""
    from pyefis.screens.screenbuilder_factory import REGISTRY
    from pyefis.screens.screenbuilder_options import apply_options

    spec = REGISTRY[type_]
    host = QWidget()
    qtbot.addWidget(host)
    w = spec.builder(host, {"type": type_, "options": {}})
    assert isinstance(w, cls)

    class _Screen:
        instruments = {0: w}
        encoder_list = []

    opts = {"caution_color": "#00ccff", "background_opacity": "0.5"}
    if type_ == "cas_window":
        opts["lines"] = "3"
    apply_options(_Screen, 0, {"type": type_, "options": opts})
    assert w.caution_color == "#00ccff"
    assert w.background_opacity == 0.5
    if type_ == "cas_window":
        assert w.lines == 3 and isinstance(w.lines, int)
    assert set(spec.dbkeys) == set(cm.LIST_KEYS) | {cm.ACK_KEY}
