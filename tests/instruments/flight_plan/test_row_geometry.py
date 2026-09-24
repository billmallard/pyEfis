#  SPDX-License-Identifier: GPL-2.0-or-later
"""Row geometry for the `flight_plan` list: physical sizing, and the two
drawing bugs that the old pane-fraction sizing produced.

Background, because the numbers below are otherwise arbitrary. `_paint_list`
used to be called with ``max_row_h = header_h``, i.e. 0.16 x the pane height.
On the Beelink's Flight Plan tab (a 649x993 portrait pane) that is a **158 px**
row, and row height drives the type icon and the row font. Measured off the
glass at the time: rows 90 px tall on a 160 px pitch, four legs in a 736 px
list area.

`font_percent` could not fix any of it -- `_font_scale`'s own docstring says
"Only fonts scale -- geometry and tap targets never do" -- which is why turning
the text size down had no visible effect on the thing that was actually too big.

Two drawing bugs fell out of the same oversized `rh`:

* the type icon was drawn at centre ``6 + rh*0.15`` with radius ``rh*0.28``, so
  its left edge sat at ``6 - rh*0.13`` -- negative for any ``rh > 46``, and
  -14 px at rh=158. The icons clipped off the left of the widget.
* the row label was drawn at ``rh * 0.5``, a constant chosen against that
  oversized icon. Once rows are sane the label lands *inside* the icon.

These tests pin the fix in the two directions that matter: the cap is physical
(so a taller pane shows more legs, not bigger ones), and both drawn elements
stay where they belong at row heights on either side of the old failure point.
"""

from types import SimpleNamespace

import pytest

from pyefis import display_metrics as dm
from pyefis.instruments import flight_plan


BEELINK = SimpleNamespace(screenWidth=1920, screenHeight=1080,
                          screenDiagonalInches=21.5)      # ~102.5 dpi
SEVEN_INCH = SimpleNamespace(screenWidth=1024, screenHeight=600,
                             screenDiagonalInches=7.0)    # ~169 dpi


def _widget(qtbot, size=(649, 993), display=BEELINK, **kw):
    w = flight_plan.FlightPlan(None, **kw)
    qtbot.addWidget(w)
    # The widget reads screen geometry off `screen.parent` (the main window).
    if display is not None:
        w.parent = SimpleNamespace(parent=display)
    w.resize(*size)
    return w


# --------------------------------------------------------------------------
# the cap is physical
# --------------------------------------------------------------------------

def test_row_cap_does_not_grow_with_the_pane(fix, qtbot):
    """The whole point: a taller pane shows MORE legs, not bigger ones.

    The old cap was 0.16 x pane height, so these two would differ by ~2.4x.
    """
    short = _widget(qtbot, size=(649, 400))
    tall = _widget(qtbot, size=(649, 993))
    assert short._row_h_cap() == pytest.approx(tall._row_h_cap())


def test_row_cap_tracks_the_physical_display(fix, qtbot):
    """Same pane, denser panel -> more pixels for the same millimetres."""
    bench = _widget(qtbot, display=BEELINK)
    panel = _widget(qtbot, display=SEVEN_INCH)
    assert panel._row_h_cap() > bench._row_h_cap() * 1.5


def test_row_cap_matches_the_configured_millimetres(fix, qtbot):
    w = _widget(qtbot)
    expected = dm.mm_to_px(14.0, 1920, 1080, 21.5)
    assert w._row_h_cap() == pytest.approx(expected, abs=0.5)
    # ...which is the ~56 px that was signed off on the bench.
    assert w._row_h_cap() == pytest.approx(56.5, abs=1.0)


def test_row_cap_is_independent_of_font_percent(fix, qtbot):
    """Geometry is not the text knob.

    An earlier attempt derived the cap by dividing by `_font_scale()`, which
    cancelled font_percent for rows while amplifying it everywhere else. That
    is the same class of mistake as the original bug, from the other side.
    """
    caps = {fp: _widget(qtbot, font_percent=fp)._row_h_cap()
            for fp in (None, 1.0, 0.5, 0.2)}
    assert len(set(round(c, 6) for c in caps.values())) == 1


def test_row_height_mm_is_honoured_and_bad_values_fall_back(fix, qtbot):
    big = _widget(qtbot); big.row_height_mm = 20.0
    small = _widget(qtbot); small.row_height_mm = 8.0
    assert big._row_h_cap() > small._row_h_cap()
    for bad in (None, 0, -5, "tall", float("nan")):
        w = _widget(qtbot); w.row_height_mm = bad
        assert w._row_h_cap() == pytest.approx(dm.mm_to_px(14.0, 1920, 1080, 21.5),
                                               abs=0.5)


def test_row_cap_survives_a_widget_with_no_parent_chain(fix, qtbot):
    """Tests and the twin exporter build instruments bare; paint must not raise."""
    w = _widget(qtbot, display=None)
    cap = w._row_h_cap()
    assert cap > 0


# --------------------------------------------------------------------------
# the two drawing bugs
# --------------------------------------------------------------------------

def _row_bands(w, plan_len=4):
    """Render and return (image, list of lit-pixel runs on a row's centre line)."""
    w._plan = _plan_of(plan_len)
    w._commit()
    img = w.grab().toImage()
    return img


def _plan_of(n):
    """Same shape as test_flight_plan.py's `_plan`, kept local so this file
    stands alone."""
    from pyefis.flightplan import model as fp_model
    return fp_model.FlightPlan(name="TEST", waypoints=[
        fp_model.Waypoint(id=f"WP{i:02d}", type="fix", lat=float(i), lon=float(i))
        for i in range(n)
    ])


def _plan_with_collapsed_airway_group():
    """GVO, [POM, RZS] tagged ``extra["airway"]="V27"`` (a collapsed group,
    PA6/AER-1605), KSMX -- three visible rows: GVO, "V27 -> RZS", KSMX. Built
    directly off the ``extra`` tag rather than through ``AirwayGraph``/a pack
    fixture -- collapsing is purely a function of that tag, so this stands
    alone the same way the rest of this file does."""
    from pyefis.flightplan import model as fp_model
    return fp_model.FlightPlan(name="TEST", waypoints=[
        fp_model.Waypoint(id="GVO", type="fix", lat=34.5, lon=-120.1),
        fp_model.Waypoint(id="POM", type="fix", lat=34.1, lon=-117.8, extra={"airway": "V27"}),
        fp_model.Waypoint(id="RZS", type="fix", lat=34.0, lon=-119.6, extra={"airway": "V27"}),
        fp_model.Waypoint(id="KSMX", type="airport", lat=34.9, lon=-120.5),
    ])


def _runs_on_line(img, y, x0=0, x1=None, thresh=60):
    """Runs of non-background pixels along a scanline: [(start, end), ...]."""
    x1 = img.width() if x1 is None else x1
    runs, start = [], None
    for x in range(x0, x1):
        c = img.pixelColor(x, y)
        lit = max(c.red(), c.green(), c.blue()) > thresh
        if lit and start is None:
            start = x
        elif not lit and start is not None:
            runs.append((start, x - 1)); start = None
    if start is not None:
        runs.append((start, x1 - 1))
    return runs


@pytest.mark.parametrize("size", [(649, 993), (649, 400), (1000, 600)])
def test_type_icon_is_never_drawn_off_the_left_edge(fix, qtbot, size):
    """The reported clipping. At the old cap this failed at every pane size."""
    w = _widget(qtbot, size=size)
    img = _row_bands(w)
    # Scan every row's vertical centre; nothing may be lit in column 0.
    lit_at_zero = [y for y in range(img.height())
                   if max(img.pixelColor(0, y).red(),
                          img.pixelColor(0, y).green(),
                          img.pixelColor(0, y).blue()) > 60]
    assert not lit_at_zero, f"content flush against the left edge at y={lit_at_zero[:5]}"


def test_row_label_does_not_collide_with_the_type_icon(fix, qtbot):
    """The icon and the first label glyph must be separated by background.

    `rh * 0.5` was tuned against the old oversized icon; at a sane row height it
    lands inside it.
    """
    w = _widget(qtbot)
    img = _row_bands(w)
    cap = w._row_h_cap()
    # Centre line of the first row. Ask the widget where its header ends --
    # hardcoding the old 0.16 * h put this scanline in the wrong place the
    # moment the chrome became physical, which is the same trap this file
    # exists to close.
    y = int(w._chrome_h(993, 2.0, 0.26) + cap / 2)
    runs = _runs_on_line(img, y, 0, int(w.width() * 0.35))
    assert len(runs) >= 2, f"expected an icon and a label on the row line, got {runs}"
    icon_end, label_start = runs[0][1], runs[1][0]
    assert label_start - icon_end >= 3, (
        f"label starts {label_start - icon_end}px after the icon ends -- they touch")


# --------------------------------------------------------------------------
# collapsed airway rows (PA6, AER-1605) -- must not reintroduce the #219/#234
# overlap: a collapsed "V27 -> RZS" row is drawn through the same icon/label
# geometry as an ordinary row, so it inherits these two fixes for free as
# long as it goes through `_paint_one_row`/`_paint_airway_summary_row`'s
# shared `_row_icon_geometry`, which is what these tests pin.
# --------------------------------------------------------------------------

def test_collapsed_airway_row_partitions_correctly(fix, qtbot):
    w = _widget(qtbot)
    w._plan = _plan_with_collapsed_airway_group()
    w._commit()
    assert w._row_groups() == [(0, 0, None), (1, 2, "V27"), (3, 3, None)]
    w.grab()  # must not raise


def test_collapsed_airway_row_sizes_by_visible_count_not_raw_count(fix, qtbot):
    """The whole point of collapsing: an N-fix run must size like ONE row --
    otherwise a long "V27 -> RZS" run steals the row height every other leg
    gets. Reads the actual geometry `_paint_list` used (via the tap targets
    it registers, one per visible row) rather than re-deriving the formula,
    so this fails if the row-height math regresses back to the raw count."""
    from pyefis.flightplan import model as fp_model
    w = _widget(qtbot)
    wps = [fp_model.Waypoint(id=f"WP{i:02d}", type="fix", lat=float(i), lon=float(i))
           for i in range(40)]
    for wp in wps[10:16]:
        wp.extra = {"airway": "V27"}
    w._plan = fp_model.FlightPlan(name="TEST", waypoints=wps)
    # 40 waypoints, 6 of them (10..15) collapsed to 1 row -> 35 visible rows.
    groups = w._row_groups()
    assert next(g for g in groups if g[2] == "V27") == (10, 15, "V27")
    assert len(groups) == 35

    from PyQt6.QtGui import QPainter, QPixmap
    header_h = int(w._chrome_h(w.height(), 2.0, 0.26))
    footer_h = int(w._chrome_h(w.height(), 1.3, 0.18))
    pixmap = QPixmap(w.width(), w.height())
    painter = QPainter(pixmap)
    w._tap_targets = []
    # `interactive=True` directly -- this widget has no gateway keys defined,
    # so `_bridge.available` (what `_paint_fpl` derives it from) is False and
    # a real paint pass would register no taps at all.
    w._paint_list(painter, w.width(), header_h, w.height() - footer_h, w._row_h_cap(), True)
    painter.end()
    # One tap target per visible row -- 35, not 40 (no toggle sub-rect: the
    # group is collapsed, so it registers exactly one tap like any other row).
    assert len(w._tap_targets) == 35
    list_h = w.height() - header_h - footer_h
    expected_rh = max(14, min(list_h / 35, w._row_h_cap()))
    used_rh = w._tap_targets[0][3]
    assert used_rh == pytest.approx(expected_rh)


def test_collapsed_airway_row_icon_is_never_drawn_off_the_left_edge(fix, qtbot):
    w = _widget(qtbot)
    w._plan = _plan_with_collapsed_airway_group()
    w._commit()
    img = w.grab().toImage()
    lit_at_zero = [y for y in range(img.height())
                   if max(img.pixelColor(0, y).red(),
                          img.pixelColor(0, y).green(),
                          img.pixelColor(0, y).blue()) > 60]
    assert not lit_at_zero, f"content flush against the left edge at y={lit_at_zero[:5]}"


def test_collapsed_airway_row_label_does_not_collide_with_the_type_icon(fix, qtbot):
    w = _widget(qtbot)
    w._plan = _plan_with_collapsed_airway_group()
    w._commit()
    img = w.grab().toImage()
    cap = w._row_h_cap()
    header_h = w._chrome_h(993, 2.0, 0.26)
    # Row 1 (index 1 in the visible list) is the collapsed "V27 -> RZS" row.
    y = int(header_h + cap * 1.5)
    runs = _runs_on_line(img, y, 0, int(w.width() * 0.35))
    assert len(runs) >= 2, f"expected an icon and a label on the collapsed row, got {runs}"
    icon_end, label_start = runs[0][1], runs[1][0]
    assert label_start - icon_end >= 3, (
        f"label starts {label_start - icon_end}px after the icon ends -- they touch")


def test_collapsed_airway_row_expands_to_its_members_on_toggle(fix, qtbot):
    w = _widget(qtbot)
    w._plan = _plan_with_collapsed_airway_group()
    w._commit()
    group = w._row_groups()[1]
    assert group == (1, 2, "V27")
    assert w._group_expanded(group) is False

    w._toggle_airway_group(w._group_key(group))
    assert w._group_expanded(group) is True
    w.grab()  # expanded rendering must not raise

    w._toggle_airway_group(w._group_key(group))
    assert w._group_expanded(group) is False


def test_a_long_plan_still_shrinks_rows_to_fit(fix, qtbot):
    """The cap is a ceiling, not a fixed pitch: many legs still compress."""
    w = _widget(qtbot)
    w._plan = _plan_of(40)
    w._commit()
    w.grab()
    # 40 rows cannot each be the capped height in a ~736 px list area.
    assert w._row_h_cap() * 40 > 993


# --------------------------------------------------------------------------
# chrome bands (header / footer / tab strips)
# --------------------------------------------------------------------------

def test_chrome_does_not_grow_with_the_pane(fix, qtbot):
    """Same defect as the rows, one level up.

    The FPL header was 0.16 x pane height and its footer 0.10 x -- 257 px of
    chrome on a 993 px pane, for about 20 px of text.
    """
    short = _widget(qtbot, size=(649, 500))
    tall = _widget(qtbot, size=(649, 993))
    assert short._chrome_h(500, 2.0, 0.26) == pytest.approx(
        tall._chrome_h(993, 2.0, 0.26))


def test_chrome_tracks_the_physical_display(fix, qtbot):
    bench = _widget(qtbot, display=BEELINK)
    panel = _widget(qtbot, display=SEVEN_INCH)
    assert panel._chrome_h(600, 2.0, 0.26) > bench._chrome_h(600, 2.0, 0.26)


def test_chrome_is_clamped_on_a_short_pane(fix, qtbot):
    """The list is the point of the page; chrome must not eat a short pane."""
    w = _widget(qtbot, size=(649, 200))
    header = w._chrome_h(200, 2.0, 0.26)
    footer = w._chrome_h(200, 1.3, 0.18)
    assert header + footer < 200 * 0.45


def test_chrome_never_collapses(fix, qtbot):
    """With no physical information and a tiny pane, a band is still drawable."""
    w = _widget(qtbot, size=(120, 90), display=None)
    assert w._chrome_h(90, 2.0, 0.26) >= 16.0


def test_the_list_gets_the_space_the_chrome_gave_back(fix, qtbot):
    """End to end: the reclaimed chrome becomes visible legs."""
    w = _widget(qtbot, size=(649, 993))
    header = int(w._chrome_h(993, 2.0, 0.26))
    footer = int(w._chrome_h(993, 1.3, 0.18))
    new_list = 993 - header - footer
    old_list = 993 - int(993 * 0.16) - int(993 * 0.10)   # the previous formulas
    assert new_list > old_list
    assert new_list / w._row_h_cap() >= 12      # ~12+ legs where 4 used to fit
