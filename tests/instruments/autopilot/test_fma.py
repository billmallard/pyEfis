#  SPDX-License-Identifier: GPL-2.0-or-later
"""The autopilot mode annunciation strip (AFC4, docs/ap_annunciator_widget_spec.md).

Each test names the requirement it verifies. The model is asserted directly
(what the strip shows), the widget for what it paints and what it writes;
writes are asserted on the bytes queued to fix-gateway.
"""

import pytest
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QColor, QImage, QPainter, QRegion
from PyQt6.QtWidgets import QWidget

from pyefis.instruments.autopilot import fma, state
from tests.instruments.autopilot.conftest import Clock, sent


def _flying(set_):
    """AP engaged, HDG with GPS armed, VS +500 with ALT armed."""
    set_("APENG", True)
    set_("YDENG", True)
    set_("APLAT", "HDG")
    set_("APLATARM", "GPS")
    set_("APVERT", "VS")
    set_("APVERTARM", "ALT")
    set_("VSSEL", 500)


def _strip(qtbot, clock=None, w=640, h=40):
    widget = fma.ModeAnnunciator(clock=clock or Clock())
    qtbot.addWidget(widget)
    widget.resize(w, h)
    widget.show()
    qtbot.waitExposed(widget)
    return widget


def _texts(cells):
    return {slot: (c.text, c.role) for slot, c in cells.items()}


# -- AP-SRC-001 / AP-ANN-001 / AP-COLOR-001 / AP-ENG-001 ---------------------

def test_strip_shows_reported_state(ap_db, qtbot):
    """AP-SRC-001, AP-ANN-001, AP-COLOR-001, AP-ENG-001: every cell is a
    reported key, active green and armed white in their own places."""
    _flying(ap_db)
    w = _strip(qtbot)
    assert _texts(w.model.cells()) == {
        "ap": ("AP", fma.ROLE_ACTIVE),
        "yd": ("YD", fma.ROLE_ACTIVE),
        "lat": ("HDG", fma.ROLE_ACTIVE),
        "lat_arm": ("GPS", fma.ROLE_ARMED),
        "vert": ("VS +500", fma.ROLE_ACTIVE),
        "vert_arm": ("ALT", fma.ROLE_ARMED),
    }
    assert w._color(fma.ROLE_ACTIVE) == QColor("#00ff00")
    assert w._color(fma.ROLE_ARMED) == QColor("#ffffff")


def test_a_request_alone_shows_nothing(ap_db, qtbot):
    """AP-SRC-001: a press writes APCMD/APCMDSEQ; until the source reports a
    state change the strip does not change. A request is never annunciated."""
    w = _strip(qtbot)
    before = _texts(w.model.cells())
    assert state.send_request("AP")
    assert state.send_request("HDG")
    assert _texts(w.model.cells()) == before == {}
    ap_db("APENG", True)
    assert _texts(w.model.cells()) == {"ap": ("AP", fma.ROLE_ACTIVE)}


def test_refused_request_never_lights_the_mode(ap_db, qtbot):
    """AP-SRC-001 (brief section 8, the NAV-with-no-nav-source case): NAV is
    requested, the source refuses and keeps HDG; the strip keeps HDG."""
    _flying(ap_db)
    w = _strip(qtbot)
    state.send_request("NAV")
    ap_db("APLAT", "HDG")  # the source rewrites its state unchanged
    assert w.model.cells()["lat"].text == "HDG"
    assert "lat_arm" in w.model.cells()
    assert all(c.text not in ("NAV", "GPS") or slot == "lat_arm"
               for slot, c in w.model.cells().items())


def test_armed_list_in_source_order(ap_db, qtbot):
    """AP-ANN-001: an armed list shows every name in the order given."""
    _flying(ap_db)
    ap_db("APVERTARM", "GS,ALT")
    ap_db("APLATARM", " LOC , ")
    w = _strip(qtbot)
    cells = w.model.cells()
    assert cells["vert_arm"].text == "GS ALT"
    assert cells["lat_arm"].text == "LOC"


def test_nothing_engaged_is_an_empty_strip(ap_db, qtbot):
    """AP-SRC-001: fresh, AP off, no modes: the strip shows nothing."""
    w = _strip(qtbot)
    assert w.model.cells() == {}


# -- AP-ANN-002: targets ------------------------------------------------------

@pytest.mark.parametrize("mode,key,value,text", [
    ("VS", "VSSEL", 500, "VS +500"),
    ("VS", "VSSEL", -700, "VS -700"),
    ("VS", "VSSEL", 0, "VS 0"),
    ("IAS", "IASSEL", 92.4, "IAS 92"),
])
def test_vertical_target_from_its_key(ap_db, qtbot, mode, key, value, text):
    """AP-ANN-002: the active vertical mode carries the target its contract
    key reports."""
    ap_db("APENG", True)
    ap_db("APVERT", mode)
    ap_db(key, value)
    w = _strip(qtbot)
    assert w.model.cells()["vert"].text == text


def test_target_follows_the_key(ap_db, qtbot):
    """AP-ANN-002: a target edit shows at once."""
    ap_db("APENG", True)
    ap_db("APVERT", "VS")
    ap_db("VSSEL", 500)
    w = _strip(qtbot)
    ap_db("VSSEL", 1200)
    assert w.model.cells()["vert"].text == "VS +1200"


def test_target_without_a_usable_value_is_the_mode_alone(ap_db, qtbot):
    """AP-ANN-002: a failed or stale target key shows the mode alone, never a
    number that may not be the target."""
    ap_db("APENG", True)
    ap_db("APVERT", "VS")
    ap_db("VSSEL", 500, fail=True)
    w = _strip(qtbot)
    assert w.model.cells()["vert"].text == "VS"
    ap_db("VSSEL", 500, old=True)
    assert w.model.cells()["vert"].text == "VS"


def test_alt_hold_shows_no_number(ap_db, qtbot):
    """AP-ANN-002: ALT hold has no reference key; ALTSEL is not necessarily
    the altitude being held, so no number is shown."""
    ap_db("APENG", True)
    ap_db("APVERT", "ALT")
    w = _strip(qtbot)
    assert w.model.cells()["vert"].text == "ALT"


@pytest.mark.xfail(strict=True, reason="AP-ANN-002 gap: AFC1 has no key for "
                   "the altitude ALT hold is holding (spec section 7)")
def test_alt_hold_shows_its_reference(ap_db, qtbot):
    """AP-ANN-002 (gap tracker): with a source-published hold reference, ALT
    shows it. Flips red the day the key and its reader land."""
    fix = ap_db.fix
    fix.db.define_item("APALTREF", "APALTREF", "int", -1000, 60000, "ft",
                       2000, "")
    ref = fix.db.get_item("APALTREF")
    ref.value = 8500
    ref.old = ref.bad = ref.fail = False
    ap_db("APENG", True)
    ap_db("APVERT", "ALT")
    w = _strip(qtbot)
    assert w.model.cells()["vert"].text == "ALT 8500"


# -- AP-ANN-003 / AP-ANN-004: mode changes ------------------------------------

def test_mode_change_flashes_for_the_flash_time(ap_db, qtbot):
    """AP-ANN-003: armed to active boxes and flashes the new mode for
    mode_flash_s (default 10 s, AC 25.1329-1C 44.d(2)), then steady."""
    clock = Clock()
    _flying(ap_db)
    w = _strip(qtbot, clock)
    assert not w.model.cells()["lat"].boxed      # the baseline is no change
    ap_db("APLAT", "GPS")
    ap_db("APLATARM", "")
    cell = w.model.cells()["lat"]
    assert (cell.text, cell.boxed, cell.blink) == ("GPS", True, True)
    assert w._timer.isActive()
    clock.t += 9.9
    assert w.model.cells()["lat"].boxed
    clock.t += 0.2
    assert not w.model.cells()["lat"].boxed
    w._tick()
    assert not w._timer.isActive()


def test_flash_time_is_configurable(ap_db, qtbot):
    """AP-ANN-003: mode_flash_s, applied after construction as apply_options
    does."""
    clock = Clock()
    _flying(ap_db)
    w = _strip(qtbot, clock)
    w.mode_flash_s = 3
    ap_db("APVERT", "ALT")
    clock.t += 2.9
    assert w.model.cells()["vert"].boxed
    clock.t += 0.2
    assert not w.model.cells()["vert"].boxed


def test_reversion_flashes_too(ap_db, qtbot):
    """AP-ANN-003: a reversion (GPS to ROL, the source's choice) is a mode
    change like any other."""
    clock = Clock()
    _flying(ap_db)
    ap_db("APLAT", "GPS")
    w = _strip(qtbot, clock)
    ap_db("APLAT", "ROL")
    assert w.model.cells()["lat"].boxed


def test_first_reading_is_a_baseline(ap_db, qtbot):
    """AP-ANN-003: the modes already active when the strip starts are not a
    change."""
    _flying(ap_db)
    w = _strip(qtbot)
    assert not w.model.cells()["lat"].boxed
    assert not w.model.cells()["vert"].boxed


def test_recovery_flashes_only_what_changed_while_blank(ap_db, qtbot):
    """AP-ANN-003: back from no data, a mode that changed while the strip was
    blank flashes; one that did not change does not."""
    clock = Clock()
    _flying(ap_db)
    w = _strip(qtbot, clock)
    ap_db("APLAT", old=True)
    ap_db("APLAT", "GPS")            # changes while stale
    ap_db("APLAT", old=False)
    cells = w.model.cells()
    assert cells["lat"].boxed        # HDG -> GPS happened unseen
    assert not cells["vert"].boxed   # VS throughout


def test_capture_is_annunciated(ap_db, qtbot):
    """AP-ANN-004: altitude capture (APALTCAP) shows ALT CAP and flashes."""
    clock = Clock()
    _flying(ap_db)
    w = _strip(qtbot, clock)
    ap_db("APALTCAP", True)
    cell = w.model.cells()["vert"]
    assert (cell.text, cell.boxed) == (fma.CAPTURE_TEXT, True)
    clock.t += 11
    ap_db("APALTCAP", False)
    ap_db("APVERT", "ALT")
    cell = w.model.cells()["vert"]
    assert (cell.text, cell.boxed) == ("ALT", True)


def test_blink_hides_text_on_the_off_phase(ap_db, qtbot):
    """AP-ANN-003: the flash is the text on and off at 1 Hz inside a steady
    box. The off phase paints the box and no text."""
    clock = Clock(1000.0)
    _flying(ap_db)
    w = _strip(qtbot, clock)
    ap_db("APLAT", "GPS")
    rect = w.slot_rects()["lat"]

    def green_in_cell():
        img = w.grab().toImage()
        n = 0
        for x in range(int(rect.left()) + 2, int(rect.right()) - 2):
            for y in range(4, w.height() - 4):
                c = img.pixelColor(x, y)
                n += c.green() > 200 and c.red() < 80
        return n

    on = green_in_cell()
    clock.t += fma.BLINK_HALF_S
    off = green_in_cell()
    assert on > off > 0       # off phase: the box alone


# -- AP-DISC-001 / AP-DISC-002: disconnect -----------------------------------

def test_disconnect_flashes_red_ap_until_the_source_clears_it(ap_db, qtbot):
    """AP-DISC-001: APDISC shows a red, boxed, flashing AP, held with no time
    limit while the source holds the flag, and gone when it clears."""
    clock = Clock()
    _flying(ap_db)
    w = _strip(qtbot, clock)
    ap_db("APENG", False)
    ap_db("APDISC", True)
    for _ in range(5):
        clock.t += 60.0
        cell = w.model.cells()["ap"]
        assert (cell.text, cell.role, cell.boxed, cell.blink) == (
            "AP", fma.ROLE_WARNING, True, True)
        assert w.model.animating()
    assert w._color(fma.ROLE_WARNING) == QColor("#ff0000")
    ap_db("APDISC", False)
    assert "ap" not in w.model.cells()


def test_disconnect_latch_is_the_sources(ap_db, qtbot):
    """AP-DISC-001: a tap acknowledges by request; the alert stays until the
    source reports the flag cleared."""
    _flying(ap_db)
    ap_db("APENG", False)
    ap_db("APDISC", True)
    w = _strip(qtbot)
    assert w.acknowledge()
    assert w.model.cells()["ap"].role == fma.ROLE_WARNING


def test_tap_acknowledges_with_disc(ap_db, qtbot):
    """AP-DISC-002: a tap sends APCMD DISC, then bumps APCMDSEQ."""
    _flying(ap_db)
    ap_db("APENG", False)
    ap_db("APDISC", True)
    ap_db("APCMDSEQ", 41)
    fix = ap_db.fix
    fix.db.clientthread.sendqueue.put.reset_mock()
    w = _strip(qtbot)
    qtbot.mouseClick(w, Qt.MouseButton.LeftButton)
    assert sent(fix) == [("APCMD", "DISC"), ("APCMDSEQ", "42")]


@pytest.mark.parametrize("setup", ["no_alert", "engaged", "stale", "off"])
def test_tap_never_sends_disc_otherwise(ap_db, qtbot, setup):
    """AP-DISC-002: with no alert, with the autopilot engaged (DISC would
    disconnect it), on stale data, or with touch_ack off, a tap writes
    nothing."""
    _flying(ap_db)
    ap_db("APENG", setup == "engaged")
    ap_db("APDISC", setup != "no_alert")
    if setup == "stale":
        ap_db("APDISC", True, old=True)
    fix = ap_db.fix
    fix.db.clientthread.sendqueue.put.reset_mock()
    w = _strip(qtbot)
    if setup == "off":
        w.touch_ack = False
    qtbot.mouseClick(w, Qt.MouseButton.LeftButton)
    assert sent(fix) == []


def test_seq_wraps_at_its_max(ap_db, qtbot):
    """AP-DISC-002: the counter wraps to 0 at its max (AFC1: the source acts on
    any change, not only an increase)."""
    ap_db("APCMDSEQ", 2147483647)
    fix = ap_db.fix
    fix.db.clientthread.sendqueue.put.reset_mock()
    assert state.send_request("DISC")
    assert sent(fix)[-1] == ("APCMDSEQ", "0")


# -- AP-STALE-001..003 --------------------------------------------------------

@pytest.mark.parametrize("key", state.STATE_KEYS)
@pytest.mark.parametrize("flag", ["old", "bad", "fail"])
def test_any_stale_key_blanks_to_no_data(ap_db, qtbot, key, flag):
    """AP-STALE-001: one state key old, bad or failed and the strip shows NO
    AP DATA and none of the last reading."""
    _flying(ap_db)
    w = _strip(qtbot)
    ap_db(key, **{flag: True})
    cells = w.model.cells()
    assert list(cells) == ["nodata"]
    assert cells["nodata"].text == fma.NO_DATA_TEXT


def test_no_data_paints_no_mode_text(ap_db, qtbot):
    """AP-STALE-001: the painted strip carries no green or white mode text
    once stale (pixel check, not just the model)."""
    _flying(ap_db)
    w = _strip(qtbot)
    ap_db("APLAT", old=True)
    img = w.grab().toImage()
    greens = sum(img.pixelColor(x, y).green() > 200
                 and img.pixelColor(x, y).red() < 80
                 for x in range(0, w.width(), 2) for y in range(w.height()))
    assert greens == 0


def test_no_data_is_amber_after_engaged_grey_otherwise(ap_db, qtbot):
    """AP-STALE-002: data lost while the autopilot was engaged is a caution
    (amber); lost while it was off, grey."""
    _flying(ap_db)
    w = _strip(qtbot)
    ap_db("APENG", old=True)
    assert w.model.cells()["nodata"].role == fma.ROLE_NODATA_CAUTION
    ap_db("APENG", False, old=False)
    ap_db("APENG", old=True)
    assert w.model.cells()["nodata"].role == fma.ROLE_NODATA


def test_never_seen_source_draws_nothing(ap_db, qtbot):
    """AP-STALE-003: keys defined but never fresh (no autopilot installed):
    no permanent caption."""
    ap_db("APENG", old=True)
    w = _strip(qtbot)
    assert w.model.cells() == {}
    img = QImage(w.size(), QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    w.render(img, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)
    assert all(img.pixelColor(x, y).alpha() == 0
               for x in range(0, w.width(), 4) for y in range(w.height()))


def test_missing_keys_build_and_draw_nothing(fix, qtbot):
    """AP-STALE-003: a gateway older than AFC1 (no autopilot keys): the strip
    builds, logs, and shows nothing; a tap writes nothing."""
    w = _strip(qtbot)
    assert not w.ap.available
    assert w.model.cells() == {}
    assert not w.acknowledge()


def test_recovery_restores_the_reading(ap_db, qtbot):
    """AP-STALE-001: data back, the strip shows the new reading."""
    _flying(ap_db)
    w = _strip(qtbot)
    ap_db("APLAT", old=True)
    ap_db("APLAT", "LOC", old=False)
    assert w.model.cells()["lat"].text == "LOC"


# -- AP-LAYOUT-001 ------------------------------------------------------------

def test_groups_follow_the_control_head_order(ap_db, qtbot):
    """AP-LAYOUT-001: lateral | AP YD | vertical by default (the AFC3 head's
    order), AP YD first with ap_position left; active and armed apart."""
    w = _strip(qtbot)
    r = w.slot_rects()
    assert r["lat"].left() < r["lat_arm"].left() < r["ap"].left() \
        < r["yd"].left() < r["vert"].left() < r["vert_arm"].left()
    w.ap_position = "left"
    r = w.slot_rects()
    assert r["ap"].left() < r["yd"].left() < r["lat"].left() \
        < r["vert"].left()


def test_template_fits_every_slot(ap_db, qtbot):
    """AP-LAYOUT-001: at a typical strip size the worst-case text of every
    slot fits its cell without shrinking below the common size."""
    w = _strip(qtbot, w=640, h=36)
    img = QImage(w.size(), QImage.Format.Format_ARGB32)
    p = QPainter(img)
    rects = w.slot_rects()
    px = 36 * 0.6
    for slot, text in fma.TEMPLATES.items():
        fitted = w._fit_px(p.device(), text, rects[slot].width(), px)
        assert fitted >= 8.0, (slot, fitted)
    p.end()
