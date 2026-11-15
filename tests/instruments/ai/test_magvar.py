"""AER-1003: pin the MAGVAR consumer.

QA's declared-authority disclosure (AER-999) states that a defect in how
magnetic variation is applied -- wrong sign, a dead subscription, a stale
value -- is invisible to render verdicts at any magnitude, because nothing
in this suite reads the widget's own computed ``head_true``. The existing
coverage (tests/tools/test_svs_capture.py::test_magvar_direction_matches_
west_positive_convention) recomputes ``HEAD - MAGVAR`` itself from a seeded
dict; it never touches the AI widget.

These tests read state the widget itself computed:
  * ``widget._fpm_head_true`` -- the FPM drift-angle site
    (src/pyefis/instruments/ai/__init__.py:903), stored on the widget as a
    testability contract (mirrors ``_decluttered``, ``_excessive_bank``, ...).
  * the ``head_true`` positional argument the SVS graphics item actually
    passes to ``SVSRenderer.draw`` (src/pyefis/instruments/ai/svs.py:2372),
    captured via a spy renderer -- not recomputed.

Convention: positive MAGVAR = west variation (FAA "West is best":
MAG = TRUE + W_VAR), so true heading must read LOWER than magnetic HEAD.
"""
from unittest import mock

import pytest
from PyQt6.QtGui import QPaintEvent
from PyQt6.QtWidgets import QApplication

from pyefis.instruments import ai
from pyefis.instruments.ai.svs import make_svs_item


@pytest.fixture
def app(qtbot):
    test_app = QApplication.instance()
    if test_app is None:
        test_app = QApplication([])
    return test_app


def _reset_ai_items(fix, old=False, bad=False, fail=False):
    for key in ["PITCH", "ROLL", "ALAT", "TAS"]:
        item = fix.db.get_item(key)
        item.old = old
        item.bad = bad
        item.fail = fail


def _fpm_inputs_ok(widget):
    for k in ('VS', 'GS', 'TRACK', 'HEAD'):
        widget._fpm_fail[k] = False


def _define_magvar(fix, value):
    """Publish MAGVAR on the mock FIX db, as a real gateway would -- the
    conftest ``fix`` fixture deliberately leaves MAGVAR undefined so the
    default state stays the graceful-missing-key case."""
    fix.db.define_item(
        "MAGVAR", "Magnetic Variation", "float", -180.0, 180.0, "deg",
        50000, "")
    fix.db.set_value("MAGVAR", value)
    fix.db.get_item("MAGVAR").bad = False
    fix.db.get_item("MAGVAR").fail = False


def _show_ai(qtbot, widget, width=240, height=220):
    qtbot.addWidget(widget)
    widget.resize(width, height)
    widget.show()
    qtbot.waitExposed(widget)
    return QPaintEvent(widget.viewport().rect())


# --- (1) sign: west-positive MAGVAR must lower the widget's own head_true --

def test_magvar_west_positive_lowers_fpm_head_true(fix, qtbot):
    _reset_ai_items(fix)
    _define_magvar(fix, 10.0)
    widget = ai.AI()
    _fpm_inputs_ok(widget)
    widget._fpm_gs = 120.0
    fix.db.set_value("HEAD", 87.0)

    event = _show_ai(qtbot, widget)
    widget.paintEvent(event)

    # Read what the widget itself computed -- not a recomputation of
    # HEAD - MAGVAR by the test.
    assert widget._fpm_head_true == pytest.approx(77.0)
    assert widget._fpm_head_true < widget._fpm_head


def test_magvar_reaches_svs_projection_head_true(fix, qtbot):
    """svs.py:2372 reads getattr(ai, "_magvar", 0.0) independently of the
    FPM site -- pin it separately via a spy renderer so a fix at one site
    that misses the other still fails here."""
    _reset_ai_items(fix)
    _define_magvar(fix, 10.0)
    widget = ai.AI()
    _fpm_inputs_ok(widget)
    fix.db.set_value("HEAD", 87.0)
    _show_ai(qtbot, widget)
    widget._pitchAngle = 0.0
    widget._rollAngle = 0.0

    renderer = mock.Mock()
    renderer.ready = True
    item = make_svs_item(renderer, widget)
    item.paint(mock.Mock(), None)

    assert renderer.draw.called
    head_true_arg = renderer.draw.call_args[0][8]
    assert head_true_arg == pytest.approx(77.0)


# --- (2) subscription: a late MAGVAR publish must move the computed value --

def test_magvar_subscription_follows_late_publish(fix, qtbot):
    _reset_ai_items(fix)
    _define_magvar(fix, 0.0)
    widget = ai.AI()
    assert widget._magvar == 0.0

    _fpm_inputs_ok(widget)
    widget._fpm_gs = 120.0
    fix.db.set_value("HEAD", 87.0)
    event = _show_ai(qtbot, widget)
    widget.paintEvent(event)
    assert widget._fpm_head_true == pytest.approx(87.0)

    # Publish AFTER construction -- a dead or never-registered callback
    # leaves _magvar (and head_true) pinned at its construction-time value.
    fix.db.set_value("MAGVAR", 10.0)
    assert widget._magvar == pytest.approx(10.0)

    widget.paintEvent(event)
    assert widget._fpm_head_true == pytest.approx(77.0)


# --- (3) graceful init: an undefined MAGVAR key must NOT look like a dead
#         subscription -- construction doesn't raise, _magvar stays 0.0, and
#         (unlike a dead subscription) a warning is logged. ------------------

def test_magvar_missing_key_stays_graceful_and_distinguishable(fix, qtbot,
                                                                 caplog):
    _reset_ai_items(fix)
    # MAGVAR intentionally left undefined -- the conftest `fix` fixture
    # does not define it.
    with pytest.raises(KeyError):
        fix.db.get_item("MAGVAR")

    with caplog.at_level("WARNING"):
        widget = ai.AI()
    qtbot.addWidget(widget)

    assert widget._magvar == 0.0
    assert any("MAGVAR" in r.getMessage() for r in caplog.records)

    # Paint cycle still completes -- SVS heading falls back to raw HEAD.
    _fpm_inputs_ok(widget)
    widget._fpm_gs = 120.0
    fix.db.set_value("HEAD", 87.0)
    widget.resize(240, 220)
    widget.show()
    qtbot.waitExposed(widget)
    widget.paintEvent(QPaintEvent(widget.viewport().rect()))
    assert widget._fpm_head_true == pytest.approx(87.0)
