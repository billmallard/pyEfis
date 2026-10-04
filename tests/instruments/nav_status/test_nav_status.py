#  SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for the `nav_status` from-to-next chip (FP7, billmallard/pyEfis#189).

Defines the engine-output keys on the shared ``fix`` fixture directly, the
pattern ``tests/instruments/flight_plan/test_flight_plan.py`` uses (FP1's
``database/flightplan.yaml`` lives in fix-gateway).
"""

from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtTest import QTest

import pyefis.hmi as hmi
from pyefis.instruments import nav_status
from pyefis.screens import screenbuilder_factory as factory

_DTYPES = {"FPLSTATE": "int", "FPLPHASE": "str", "WPFROM": "str",
           "WPNAME": "str", "WPNEXT": "str", "WPDIS": "float", "WPETE": "int"}
_BOUNDS = {"float": (0.0, 1e6), "int": (0, 1_000_000), "str": (None, None)}
_INITIAL = {"int": 0, "float": 0.0, "str": ""}

MAGENTA = QColor("#ff00ff")
WHITE = QColor("#ffffff")


def _define_keys(fix, keys=None):
    for key, dtype in _DTYPES.items():
        if keys is not None and key not in keys:
            continue
        mn, mx = _BOUNDS[dtype]
        fix.db.define_item(key, key, dtype, mn, mx, "", 0, "")
        fix.db.set_value(key, _INITIAL[dtype])
        item = fix.db.get_item(key)
        item.old = item.bad = item.fail = False


def _set(fix, **values):
    for key, value in values.items():
        fix.db.set_value(key, value)


def _leg(fix, state=1, **extra):
    values = dict(FPLSTATE=state, FPLPHASE="TERM", WPFROM="KSBA",
                  WPNAME="GVO", WPNEXT="RZS", WPDIS=12.43, WPETE=372)
    values.update(extra)
    _set(fix, **values)


@pytest.fixture
def chip(qtbot, fix):
    _define_keys(fix)
    widget = nav_status.NavStatus()
    qtbot.addWidget(widget)
    widget.resize(400, 40)
    return widget


def _texts(runs):
    return [t for t, _ in runs]


def _paint(widget):
    image = QImage(widget.size(), QImage.Format.Format_ARGB32)
    image.fill(0)
    widget.render(image)
    return image


# -- underscores ------------------------------------------------------------
def test_no_plan_draws_underscores_and_no_badge(chip):
    badge, runs, data, stale = chip.fields()
    assert badge is None
    assert _texts(runs) == ["____", ">", "____", ">", "____"]
    assert data == []  # nothing to measure without an active leg
    assert not stale


def test_no_plan_ignores_leftover_idents(chip, fix):
    # The engine clears the idents on NONE, but a chip must not trust that:
    # FPLSTATE is the authority on "is there an active leg".
    _leg(fix, state=0)
    _, runs, _, _ = chip.fields()
    assert _texts(runs) == ["____", ">", "____", ">", "____"]


def test_underscores_are_never_magenta(chip, fix):
    assert {c.name() for _, c in chip.fields()[1]} == {WHITE.name()}
    _leg(fix, WPNAME="")
    assert chip.fields()[1][2] == ("____", WHITE)


def test_missing_next_is_underscores_on_the_last_leg(chip, fix):
    _leg(fix, WPNEXT="")
    _, runs, _, _ = chip.fields()
    assert _texts(runs) == ["KSBA", ">", "GVO", ">", "____"]


def test_construct_with_no_gateway_keys_never_raises(qtbot, fix):
    widget = nav_status.NavStatus()
    qtbot.addWidget(widget)
    widget.resize(300, 30)
    assert not widget.available
    badge, runs, data, _ = widget.fields()
    assert badge is None
    assert _texts(runs) == ["____", ">", "____", ">", "____"]
    _paint(widget)  # paints, does not raise


def test_partial_keys_draw_what_exists(qtbot, fix):
    _define_keys(fix, keys={"FPLSTATE", "WPNAME"})
    _set(fix, FPLSTATE=1, WPNAME="GVO")
    widget = nav_status.NavStatus()
    qtbot.addWidget(widget)
    assert not widget.available
    badge, runs, data, _ = widget.fields()
    assert badge == "LEG"
    assert _texts(runs) == ["____", ">", "GVO", ">", "____"]
    assert data == []


# -- idents, colours, badge ---------------------------------------------------
def test_synthetic_plan_idents_and_colours(chip, fix):
    _leg(fix)
    badge, runs, data, stale = chip.fields()
    assert badge == "LEG"
    assert _texts(runs) == ["KSBA", ">", "GVO", ">", "RZS"]
    colours = [c for _, c in runs]
    assert colours[2] == MAGENTA          # TO waypoint: active colour
    assert colours[0] == WHITE and colours[4] == WHITE
    assert data == [("12.4 NM", WHITE), ("0:06", WHITE),
                    ("TERM", nav_status._PHASE)]
    assert not stale


@pytest.mark.parametrize("state,label", [(1, "LEG"), (2, "DIRECT"), (3, "SUSP")])
def test_badge_follows_fplstate(chip, fix, state, label):
    _leg(fix, state=state)
    assert chip.fields()[0] == label


def test_colour_options_apply(chip, fix):
    _leg(fix)
    chip.active_color = "#00ffff"
    chip.text_color = "#ffff00"
    _, runs, _, _ = chip.fields()
    assert runs[2][1] == QColor("#00ffff")
    assert runs[0][1] == QColor("#ffff00")


def test_active_ident_is_painted_magenta(chip, fix):
    # Pixel-level check that fields() is what paintEvent draws: a magenta
    # pixel exists only once a TO ident is on the chip.
    def has_magenta(image):
        for x in range(image.width()):
            for y in range(image.height()):
                c = image.pixelColor(x, y)
                if c.red() > 200 and c.blue() > 200 and c.green() < 60:
                    return True
        return False

    assert not has_magenta(_paint(chip))
    _leg(fix)
    assert has_magenta(_paint(chip))


@pytest.mark.parametrize("size", [(600, 48), (120, 40)])
def test_long_content_shrinks_to_fit(chip, fix, size, monkeypatch):
    # Idents wider than the sizing template must shrink the text further
    # rather than overrun. A one-character template makes the live content
    # decisively wider than it whatever font the test host resolves.
    monkeypatch.setattr(nav_status, "TEMPLATE_IDENT", "W")
    _leg(fix, state=2, WPFROM="WWWWWW", WPNAME="WWWWWW", WPNEXT="WWWWWW",
         WPDIS=888.8, WPETE=36000, FPLPHASE="VECTORS")
    _set(fix, FPLPHASE="0.30 NM")
    chip.resize(*size)
    device = QImage(chip.size(), QImage.Format.Format_ARGB32)
    avail = chip.width() - 2 * chip.height() * 0.15
    badge, runs, data, _ = chip.fields()
    px = chip._fit_px(device, avail, chip.height(), badge, runs, data)
    from PyQt6.QtGui import QFontMetricsF
    _, right = chip._layout(QFontMetricsF(chip._font(px), device), badge, runs, data)
    assert right <= avail or px == 4.0
    _paint(chip)


def test_font_size_is_stable_across_content(chip, fix):
    # Sized to the worst-case template, not the live text: the idents, badge
    # and phase changing in flight must not make the chip's text jump size.
    from PyQt6.QtGui import QImage
    device = QImage(chip.size(), QImage.Format.Format_ARGB32)
    avail = chip.width() - 2 * chip.height() * 0.15

    def px():
        badge, runs, data, _ = chip.fields()
        return chip._fit_px(device, avail, chip.height(), badge, runs, data)

    sizes = {px()}
    _leg(fix)
    sizes.add(px())
    _leg(fix, state=2, WPFROM="", FPLPHASE="0.30 NM")
    sizes.add(px())
    assert len(sizes) == 1


# -- optional fields and quality ----------------------------------------------
def test_distance_and_ete_options_hide_fields(chip, fix):
    _leg(fix)
    chip.show_distance = False
    chip.show_ete = False
    chip.show_phase = False
    assert chip.fields()[2] == []


def test_ete_bad_draws_dashes(chip, fix):
    _leg(fix)
    fix.db.get_item("WPETE").bad = True
    data = chip.fields()[2]
    assert ("--:--", nav_status._GREY) in data


def test_distance_bad_is_greyed(chip, fix):
    _leg(fix)
    fix.db.get_item("WPDIS").bad = True
    assert chip.fields()[2][0] == ("12.4 NM", nav_status._GREY)


def test_fail_draws_red_xxx(chip, fix):
    _leg(fix)
    fix.db.get_item("WPDIS").fail = True
    fix.db.get_item("WPETE").fail = True
    data = chip.fields()[2]
    assert data[0] == ("XXX", nav_status._FAIL)
    assert data[1] == ("XXX", nav_status._FAIL)


def test_old_state_greys_the_whole_chip(chip, fix):
    _leg(fix)
    fix.db.get_item("FPLSTATE").old = True
    badge, runs, data, stale = chip.fields()
    assert stale
    assert {c.name() for _, c in runs + data} == {nav_status._GREY.name()}


def test_loi_phase_is_yellow(chip, fix):
    _leg(fix, FPLPHASE="LOI")
    assert chip.fields()[2][-1] == ("LOI", nav_status._PHASE_LOI)


def test_vectors_leg_shows_no_distance_or_time(chip, fix):
    # The engine publishes WPDIS=0 / WPETE=0 with no flag on a vector leg
    # (it does not invent a distance); the chip must not show "0.0 NM".
    _leg(fix, FPLPHASE="VECTORS", WPDIS=0.0, WPETE=0, WPNEXT="")
    assert chip.fields()[2] == [("VECTORS", nav_status._PHASE)]


@pytest.mark.parametrize("nm,text", [(0.04, "0.0 NM"), (99.94, "99.9 NM"),
                                     (100.0, "100 NM"), (1234.4, "1234 NM")])
def test_distance_format(nm, text):
    assert nav_status.format_distance(nm) == text


@pytest.mark.parametrize("s,text", [(0, "0:00"), (372, "0:06"), (3600, "1:00"),
                                    (36059, "10:00")])
def test_ete_format(s, text):
    assert nav_status.format_ete(s) == text


def test_value_change_repaints(chip, fix):
    chip.update = MagicMock()
    _set(fix, WPNAME="RZS")
    assert chip.update.called


# -- tap -> verb --------------------------------------------------------------
@pytest.fixture
def actions(monkeypatch):
    a = MagicMock()
    monkeypatch.setattr(hmi, "actions", a)
    return a


def test_tap_fires_flightplan_page_fpl(chip, actions):
    QTest.mouseClick(chip, Qt.MouseButton.LeftButton)
    actions.trigger.assert_called_once_with("flightplan page", "fpl")


def test_tap_targets_hmi_group(chip, actions):
    chip.hmi_group = "nav"
    QTest.mouseClick(chip, Qt.MouseButton.LeftButton)
    actions.trigger.assert_called_once_with("flightplan page", "fpl nav")


def test_tap_switches_screen_first(chip, actions):
    chip.tap_screen = "FLIGHTPLAN"
    QTest.mouseClick(chip, Qt.MouseButton.LeftButton)
    assert [c.args for c in actions.trigger.call_args_list] == [
        ("show screen", "FLIGHTPLAN"), ("flightplan page", "fpl")]


def test_tap_reaches_a_real_flight_plan_page_signal(chip, monkeypatch):
    # End to end through the real ActionClass: the verb the chip fires is a
    # registered action, so a flight_plan instrument's _act_page receives it.
    from pyefis.hmi.actionclass import ActionClass
    real = ActionClass()
    monkeypatch.setattr(hmi, "actions", real)
    got = []
    real.flightplanPage.connect(got.append)
    QTest.mouseClick(chip, Qt.MouseButton.LeftButton)
    assert got == ["fpl"]


def test_tap_without_hmi_is_a_no_op(chip, monkeypatch):
    monkeypatch.setattr(hmi, "actions", None)
    QTest.mouseClick(chip, Qt.MouseButton.LeftButton)  # does not raise


# -- registry ------------------------------------------------------------------
def test_registry_builds_nav_status(qtbot, fix):
    spec = factory.REGISTRY["nav_status"]
    widget = spec.builder(None, {"options": {}})
    qtbot.addWidget(widget)
    assert isinstance(widget, nav_status.NavStatus)
    for prop in spec.properties:
        assert getattr(widget, prop.name) == prop.default
