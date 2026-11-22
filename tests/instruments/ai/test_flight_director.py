#  SPDX-License-Identifier: GPL-2.0-or-later
"""Flight director command bars on the attitude indicator and SVS (AFC5,
CAP-508, AER-6052).

FDPITCH/FDROLL are the commanded attitude and FDENG says the FD is on
(fix-gateway autopilot.yaml). The bars are drawn only while FDENG is true and
all three keys are current: a stale command is removed, never frozen in place
(brief section 5.7). Two styles share one implementation: single_cue (the
default, D4) and cross_pointer.
"""

import math
from types import SimpleNamespace

import numpy as np
import pytest
from PyQt6.QtGui import QImage, QPainter

from pyefis.instruments.ai import AI
from pyefis.instruments.ai import ai_widget

W, H = 480, 360
STYLES = ("single_cue", "cross_pointer")


def _define_fd(fix):
    """The FD keys as fix-gateway autopilot.yaml defines them."""
    fix.db.define_item("FDENG", "Flight director on", "bool",
                       0, 1, "", 2000, "")
    fix.db.define_item("FDPITCH", "Flight director commanded pitch",
                       "float", -90.0, 90.0, "deg", 1000, "")
    fix.db.define_item("FDROLL", "Flight director commanded roll",
                       "float", -180.0, 180.0, "deg", 1000, "")


def _good(fix, *keys):
    for key in keys:
        item = fix.db.get_item(key)
        item.old = item.bad = item.fail = False


def _set(fix, key, value):
    fix.db.set_value(key, value)


@pytest.fixture
def fd(fix):
    """Attitude level and valid; FD on, commanding level, all fresh."""
    _define_fd(fix)
    for key, value in (("PITCH", 0.0), ("ROLL", 0.0), ("ALAT", 0.0),
                       ("TAS", 100.0), ("FDENG", True), ("FDPITCH", 0.0),
                       ("FDROLL", 0.0)):
        _set(fix, key, value)
    _good(fix, "PITCH", "ROLL", "ALAT", "TAS", *ai_widget.FD_KEYS)
    return fix


def _ai(qtbot, style="single_cue", svs=False):
    w = AI()
    qtbot.addWidget(w)
    w.fd_style = style
    w.resize(W, H)
    w.show()
    qtbot.waitExposed(w)
    if svs:
        # Configured and enabled, so the symbology registers with the
        # terrain's projection (the SVS path's _pitch_px is the tangent).
        w._svs_renderer = SimpleNamespace(
            enabled=True, ready=False, gl_failed=False, drew_terrain=False,
            consume_async_dirty=lambda: False)
        w.redraw()
    return w


def _overlays(w):
    img = QImage(w.width(), w.height(), QImage.Format.Format_RGB32)
    img.fill(0)
    p = QPainter(img)
    w._paint_overlays(p)
    p.end()
    return _array(img)


def _array(img):
    img = img.convertToFormat(QImage.Format.Format_RGB32)
    ptr = img.constBits()
    ptr.setsize(img.sizeInBytes())
    return np.frombuffer(ptr, np.uint8).reshape(
        img.height(), img.bytesPerLine() // 4, 4)[:, :img.width()].copy()


def _magenta(arr):
    """Mask of FD-magenta pixels (BGRA). Nothing else on the AI is magenta:
    the symbol is yellow, the scales white, the FPM green, the cautions
    amber, the bank bug cyan."""
    b, g, r = (arr[..., i].astype(int) for i in range(3))
    return (r > 180) & (b > 180) & (g < 90)


def _drawn(w):
    return int(_magenta(_overlays(w)).sum())


# --- removed, never frozen (definition of done 1) ---------------------------

@pytest.mark.parametrize("style", STYLES)
def test_fresh_command_draws_the_bars(fd, qtbot, style):
    w = _ai(qtbot, style)
    assert _drawn(w) > 200
    assert w._fd_drawn is True


@pytest.mark.parametrize("style", STYLES)
def test_fd_off_draws_nothing(fd, qtbot, style):
    _set(fd, "FDENG", False)
    w = _ai(qtbot, style)
    assert _drawn(w) == 0
    assert w._fd_drawn is False


@pytest.mark.parametrize("style", STYLES)
@pytest.mark.parametrize("flag", ["old", "bad", "fail"])
@pytest.mark.parametrize("key", ai_widget.FD_KEYS)
def test_stale_key_removes_the_bars(fd, qtbot, style, key, flag):
    """Each FD key, each quality flag, each style: the bar goes."""
    w = _ai(qtbot, style)
    assert _drawn(w) > 200
    setattr(fd.db.get_item(key), flag, True)
    assert _drawn(w) == 0
    assert w.flight_director_command() is None


@pytest.mark.parametrize("style", STYLES)
def test_stale_command_on_the_real_paint_path(fd, qtbot, style):
    """Through paintEvent (widget.grab), not just the overlay helper: the
    frame after FDPITCH goes old carries no bar."""
    w = _ai(qtbot, style)
    assert _magenta(_array(w.grab().toImage())).sum() > 200
    fd.db.get_item("FDPITCH").old = True
    assert _magenta(_array(w.grab().toImage())).sum() == 0


@pytest.mark.parametrize("key", ai_widget.FD_KEYS)
def test_going_stale_repaints_at_once(fd, qtbot, monkeypatch, key):
    """The frame clock skips a frame whose pose did not move. A stale flag
    must force the repaint itself, or the last bar stays on the glass."""
    w = _ai(qtbot)
    calls = []
    monkeypatch.setattr(w, "update", lambda: calls.append(1))
    w._frame_dirty = False
    fd.db.get_item(key).old = True
    assert calls and w._frame_dirty is True


def test_recovery_draws_the_bars_again(fd, qtbot):
    w = _ai(qtbot)
    fd.db.get_item("FDROLL").old = True
    assert _drawn(w) == 0
    fd.db.get_item("FDROLL").old = False
    assert _drawn(w) > 200


@pytest.mark.parametrize("key", ["PITCH", "ROLL"])
def test_invalid_attitude_removes_the_bars(fd, qtbot, key):
    """The bars show command minus attitude; with no attitude they point at
    nothing."""
    w = _ai(qtbot)
    fd.db.get_item(key).old = True
    assert _drawn(w) == 0


def test_missing_keys_build_and_draw_nothing(fix, qtbot):
    """A gateway older than AFC1 has no FD keys: the AI still builds."""
    for key in ai_widget.FD_KEYS:
        with pytest.raises(KeyError):
            fix.db.get_item(key)
    w = _ai(qtbot)
    assert w.flight_director_command() is None
    assert _drawn(w) == 0


def test_style_off_draws_nothing(fd, qtbot):
    w = _ai(qtbot, "off")
    assert _drawn(w) == 0


def test_unknown_style_falls_back_to_single_cue(fd, qtbot):
    w = _ai(qtbot, "sideways")
    assert w._fd_style() == "single_cue"
    assert _drawn(w) > 200


@pytest.mark.parametrize("style", STYLES)
def test_hidden_by_the_unusual_attitude_declutter(fd, qtbot, style):
    _set(fd, "ROLL", 70.0)
    _set(fd, "FDROLL", 70.0)
    w = _ai(qtbot, style)
    assert _drawn(w) == 0
    assert w._decluttered is True
    assert w._fd_drawn is False


# --- geometry: the cue shows command minus attitude --------------------------

def _rows_cols(mask):
    ys, xs = np.nonzero(mask)
    return ys, xs


@pytest.mark.parametrize("svs", [False, True], ids=["ai", "svs"])
@pytest.mark.parametrize("style", STYLES)
def test_pitch_command_sits_on_its_ladder_rung(fd, qtbot, style, svs):
    """Pitch 5 up, command level: the cue sits on the zero-pitch line, the
    ladder's own scale (the tangent under SVS)."""
    _set(fd, "PITCH", 5.0)
    w = _ai(qtbot, style, svs=svs)
    _drawn(w)
    assert w._fd_y_px == pytest.approx(w._pitch_px(5.0))
    if svs:
        ppd = w.pixelsPerDeg
        assert w._fd_y_px == pytest.approx(
            ppd * math.degrees(math.tan(math.radians(5.0))))


@pytest.mark.parametrize("svs", [False, True], ids=["ai", "svs"])
@pytest.mark.parametrize("style", STYLES)
def test_pitch_up_command_draws_above_the_symbol(fd, qtbot, style, svs):
    cy = H / 2.0
    _set(fd, "FDPITCH", 6.0)
    w = _ai(qtbot, style, svs=svs)
    mask = _magenta(_overlays(w))
    if style == "cross_pointer":
        # The pitch bar is the wide run of rows; the roll bar is centred.
        rows = np.nonzero(mask.sum(axis=1) > W * 0.2)[0]
    else:
        rows = np.nonzero(mask.any(axis=1))[0]
    assert rows.size and rows.max() < cy - w._pitch_px(6.0) * 0.5
    _set(fd, "FDPITCH", -6.0)
    mask = _magenta(_overlays(w))
    if style == "cross_pointer":
        rows = np.nonzero(mask.sum(axis=1) > W * 0.2)[0]
    else:
        rows = np.nonzero(mask.any(axis=1))[0]
    assert rows.size and rows.min() > cy


@pytest.mark.parametrize("svs", [False, True], ids=["ai", "svs"])
def test_single_cue_banks_toward_the_command(fd, qtbot, svs):
    """Right bank commanded from wings level: the chevron's right arm is
    lower on the glass (right wing down), the bank the pilot rolls to."""
    _set(fd, "FDROLL", 20.0)
    w = _ai(qtbot, "single_cue", svs=svs)
    ys, xs = _rows_cols(_magenta(_overlays(w)))
    right = ys[xs > W / 2 + W * 0.08].mean()
    left = ys[xs < W / 2 - W * 0.08].mean()
    assert right > left + 10
    assert w._fd_roll_err == pytest.approx(20.0)


def test_single_cue_level_once_the_bank_is_flown(fd, qtbot):
    _set(fd, "FDROLL", 20.0)
    _set(fd, "ROLL", 20.0)
    w = _ai(qtbot, "single_cue")
    ys, xs = _rows_cols(_magenta(_overlays(w)))
    right = ys[xs > W / 2 + W * 0.08].mean()
    left = ys[xs < W / 2 - W * 0.08].mean()
    assert abs(right - left) < 2
    assert w._fd_roll_err == pytest.approx(0.0)


@pytest.mark.parametrize("svs", [False, True], ids=["ai", "svs"])
def test_cross_pointer_roll_bar_moves_toward_the_command(fd, qtbot, svs):
    _set(fd, "FDROLL", 15.0)
    w = _ai(qtbot, "cross_pointer", svs=svs)
    mask = _magenta(_overlays(w))
    # The roll bar is the tall run of columns.
    cols = np.nonzero(mask.sum(axis=0) > H * 0.2)[0]
    span = W * 0.16
    assert cols.size
    assert cols.mean() == pytest.approx(W / 2 + span / 2, abs=3)
    _set(fd, "FDROLL", -60.0)       # past full scale: pinned at the end
    mask = _magenta(_overlays(w))
    cols = np.nonzero(mask.sum(axis=0) > H * 0.2)[0]
    assert cols.mean() == pytest.approx(W / 2 - span, abs=3)


def test_bank_error_wraps_across_180(fd, qtbot):
    _set(fd, "ROLL", 170.0)
    _set(fd, "FDROLL", -170.0)
    w = _ai(qtbot)
    w.unusualBankDeg = 181          # isolate the wrap from the declutter
    _drawn(w)
    assert w._fd_roll_err == pytest.approx(20.0)


def test_large_pitch_error_pins_the_cue_on_the_glass(fd, qtbot):
    _set(fd, "FDPITCH", 15.0)
    _set(fd, "PITCH", -15.0)
    w = _ai(qtbot)
    w.unusualPitchLowDeg = -90      # keep it from de-cluttering
    ys, _xs = _rows_cols(_magenta(_overlays(w)))
    assert ys.size and ys.min() >= 0


# --- the screen option ---------------------------------------------------------

@pytest.mark.parametrize("itype", ["atitude_indicator", "virtual_vfr"])
def test_configurator_offers_both_styles_single_cue_default(itype, fix, qtbot):
    from pyefis.screens import screenbuilder_factory as factory
    props = {p.name: p for p in factory.REGISTRY[itype].properties}
    prop = props["fd_style"]
    assert prop.default == "single_cue"
    assert set(prop.enum) == set(ai_widget.FD_STYLES)
    w = AI()
    qtbot.addWidget(w)
    assert w.fd_style == prop.default


@pytest.mark.parametrize("itype", ["atitude_indicator", "virtual_vfr"])
def test_yaml_style_reaches_the_widget_through_apply_options(fd, qtbot,
                                                             itype):
    """The screen-build path, not a direct assignment."""
    from pyefis.screens import screenbuilder_factory as factory
    from pyefis.screens.screenbuilder_options import apply_options

    w = factory.create_instrument(None, {"type": itype})
    qtbot.addWidget(w)

    class _Screen:
        instruments = {0: w}
        encoder_list = []

    apply_options(_Screen, 0, {"type": itype,
                               "options": {"fd_style": "cross_pointer"}})
    w.resize(W, H)
    w.show()
    qtbot.waitExposed(w)
    assert w._fd_style() == "cross_pointer"
    mask = _magenta(_overlays(w))
    assert (mask.sum(axis=0) > H * 0.2).any()     # the vertical roll bar


# --- a real X-Plane flight (definition of done 3, replayed) ------------------

FLIGHT = __file__.rsplit("/", 1)[0] + "/data/afc2_bf3a33402db4_fd_bus.csv.gz"


def _flight_rows():
    """The AFC2 sim-bench session bf3a33402db4 (X-Plane 12.4.3, Laminar C172
    G1000, 2026-11-18): every PITCH, ROLL, FD and mode key value the gateway
    published, with its netfix flags (annunciate, old, bad, fail, secfail),
    t in seconds from the first row. See data/README.md."""
    import csv
    import gzip
    with gzip.open(FLIGHT, "rt") as fh:
        for row in csv.DictReader(fh):
            yield float(row["t_s"]), row["key"], row["value"], row["flags"]


def _apply(fix, key, value, flags):
    item = fix.db.get_item(key)
    if item.dtype is bool:
        value = value == "True"
    elif item.dtype is float:
        value = float(value)
    fix.db.set_value(key, value)
    item.old = flags[1] == "1"
    item.bad = flags[2] == "1"
    item.fail = flags[3] == "1"


@pytest.mark.parametrize("style", STYLES)
def test_real_flight_bars_follow_the_command_and_go_when_stale(fd, qtbot,
                                                               style):
    """The bus of a real X-Plane flight through HDG, VS to ALT capture, IAS,
    NAV capture, LVL and a disconnect, after which the sim stops sending.
    Every 0.25 s the bars are drawn exactly when FDENG is on and every input
    is fresh, at command minus attitude; once the keys go old they are gone.
    The expectation is computed from the recorded flags, not the widget."""
    for key in ("APLAT", "APVERT", "APLATARM", "APVERTARM"):
        fd.db.define_item(key, key, "str", None, None, "", 2000, "")
    w = _ai(qtbot, style)
    w.unusualBankDeg = 65
    state = {}
    seen = {"drawn": 0, "removed": 0, "off": 0, "climb": 0}
    next_t = 0.0
    for t, key, value, flags in _flight_rows():
        while t >= next_t:
            if state.get("PITCH") and state.get("FDPITCH"):
                fresh = all(state[k][1][1:4] == "000" for k in
                            ("PITCH", "ROLL", "FDENG", "FDPITCH", "FDROLL"))
                on = state["FDENG"][0] == "True"
                drawn = _drawn(w) > 0
                assert drawn == (on and fresh and not w._decluttered), next_t
                if drawn:
                    seen["drawn"] += 1
                    pitch, roll = (float(state[k][0]) for k in ("PITCH", "ROLL"))
                    fdp, fdr = (float(state[k][0]) for k in ("FDPITCH", "FDROLL"))
                    assert w._fd_y_px == pytest.approx(w._pitch_px(pitch - fdp))
                    assert w._fd_roll_err == pytest.approx(fdr - roll, abs=1e-6)
                    if state["APVERT"][0] == "VS":
                        seen["climb"] += 1
                elif not on:
                    seen["off"] += 1
                else:
                    seen["removed"] += 1
            next_t += 0.25
        state[key] = (value, flags)
        _apply(fd, key, value, flags)
    # FD off before the autopilot couples, on through the modes, VS climb
    # included, and removed (not frozen) after the sim stopped sending.
    assert seen["off"] >= 20
    assert seen["drawn"] >= 600
    assert seen["climb"] >= 150
    assert seen["removed"] >= 4
    assert w.flight_director_command() is None
