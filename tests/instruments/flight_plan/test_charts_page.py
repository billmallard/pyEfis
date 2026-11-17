#  SPDX-License-Identifier: GPL-2.0-or-later
"""The Charts page (PA12, billmallard/pyEfis#241, AER-1611): a d-TPP plate
drawn from the plates pack, one tap from the loaded approach, and the
airport diagram through the same page (CAP-207).

The pack holds KSBA's real catalog records (``tests/flightplan/
ksba_plates.py``); the PDFs are pages drawn here with ``QPdfWriter``, dark
over their top-left quarter and white elsewhere, so a test can tell from
the pixels where the page landed. The approach is KSBA's real ILS RWY 7
from the PA7 fixture.
"""

import sqlite3

import pytest
from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QMarginsF, QPointF, QRectF, QSizeF, Qt
from PyQt6.QtGui import QColor, QPageSize, QPainter, QPdfWriter
from PyQt6.QtTest import QTest

from pyefis.flightplan import model as fp_model
from pyefis.instruments import flight_plan
from pyefis.instruments.flight_plan import plate_render
from pyefis.screens import screenbuilder_factory
from tests.flightplan import ksba_plates
from tests.instruments.flight_plan.test_proc_page import (  # noqa: F401  (fixture)
    KSBA, RZS, _by_callback, _engine_loads, _nth_row, _press, _rect_of, page)

pytestmark = pytest.mark.skipif(not plate_render.PlateRenderer().available,
                                reason="PyQt6.QtPdf is not installed")

# A real plate's page size, in points (KSBA ILS OR LOC RWY 7).
PAGE_PT = (387.36, 594.0)


def _pdf(shade="#000000"):
    """A one-page vector PDF, *shade* over the top-left quarter."""
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    writer = QPdfWriter(buf)
    writer.setPageSize(QPageSize(QSizeF(*PAGE_PT), QPageSize.Unit.Point))
    writer.setPageMargins(QMarginsF(0, 0, 0, 0))
    writer.setResolution(72)
    p = QPainter(writer)
    p.fillRect(QRectF(0, 0, PAGE_PT[0] / 2, PAGE_PT[1] / 2), QColor(shade))
    p.end()
    buf.close()
    return bytes(data)


@pytest.fixture()
def charts(page, tmp_path):
    pdfs = {"00378IL7.PDF": _pdf(), "00378AD.PDF": _pdf("#0000ff")}
    page.plates_path = str(ksba_plates.build(tmp_path / "plates.sqlite", pdfs=pdfs))
    return page


def _load_ils07(w, fix):
    w._open_proc_page("approach")
    w._proc.update(proc=w._ensure_procedure_index().find("KSBA", "approach", "I07"),
                   transition="VECTORS")
    w._proc_load()
    _engine_loads(w, fix)
    assert [s.ident for s in w._plan.segments if s.kind == "approach"] == ["ILS07.VECTORS"]


def _view(w):
    """The chart's view rect and the frame it was painted into."""
    img = w.grab().toImage()
    return w._plate_view, img


def _sample(img, x, y):
    return QColor(img.pixel(int(x), int(y)))


def _page_rect(w):
    view = w._plate_view
    r = view["rect"]
    x = r.left() + (r.width() - view["w"]) / 2
    y = r.top() + (r.height() - view["h"]) / 2
    return QRectF(x, y, view["w"], view["h"])


# ---------------------------------------------------------------------------
# Getting there
# ---------------------------------------------------------------------------
def test_no_plates_pack_no_charts_key(page):
    page.grab()
    assert not any(cb == page._footer_charts for (*_r, cb) in page._tap_targets)


@pytest.mark.parametrize("how", ["touch", "encoder"])
def test_one_tap_from_the_loaded_approach_opens_its_plate(charts, fix, how):
    _load_ils07(charts, fix)
    _press(charts, how, _by_callback(charts._footer_charts))
    assert charts._page == "charts"
    plate = charts._charts["plate"]
    assert (plate.icao_ident, plate.chart_name) == ("KSBA", "ILS OR LOC RWY 07")
    view, img = _view(charts)
    page_rect = _page_rect(charts)
    # The page is on the glass: dark in its top-left quarter, white in the
    # bottom-right one.
    q = page_rect.width() / 4, page_rect.height() / 4
    assert _sample(img, page_rect.left() + q[0], page_rect.top() + q[1]).lightness() < 40
    assert _sample(img, page_rect.right() - q[0], page_rect.bottom() - q[1]).lightness() > 215
    # Fitted, aspect kept: the page fills the view one way.
    assert page_rect.width() / page_rect.height() == pytest.approx(PAGE_PT[0] / PAGE_PT[1], rel=0.01)
    assert (page_rect.height() == pytest.approx(view["rect"].height(), abs=1)
            or page_rect.width() == pytest.approx(view["rect"].width(), abs=1))


@pytest.mark.parametrize("how", ["touch", "encoder"])
def test_the_airport_diagram_is_the_first_chart_listed(charts, how):
    # No approach loaded: the destination's list, diagram first.
    _press(charts, how, _by_callback(charts._footer_charts))
    assert charts._charts["airport"] == "KSBA" and charts._charts["plate"] is None
    _press(charts, how, _nth_row(0))
    assert charts._charts["plate"].chart_code == "APD"
    _view_, img = _view(charts)
    r = _page_rect(charts)
    assert _sample(img, r.left() + r.width() / 4, r.top() + r.height() / 4).blue() > 200


def test_the_hmi_verb_opens_the_page(charts):
    charts._act_page("charts")
    assert charts._page == "charts"


def test_an_approach_with_no_single_chart_opens_the_list_and_says_so(page, fix, tmp_path):
    records = [r for r in ksba_plates.KSBA_RECORDS if r[2] != "00378IL7.PDF"]
    page.plates_path = str(ksba_plates.build(tmp_path / "p.sqlite", records=records))
    _load_ils07(page, fix)
    page._footer_charts()
    assert page._charts["plate"] is None
    assert page._charts["message"] == "NO SINGLE PLATE FOR ILS07"


def test_the_list_pages_and_a_different_airport_can_be_picked(charts):
    charts.resize(649, 400)
    charts._footer_charts()
    charts.grab()
    first = charts._charts["first"]
    # The rightmost soft key is the page-down arrow.
    _press(charts, "touch", lambda layer: max((t for t in layer if t[5] == "soft"),
                                              key=lambda t: t[0]))
    assert charts._charts["first"] > first
    charts._charts_change_airport()
    assert charts._page == "entry" and charts._entry_mode["kind"] == "charts_airport"
    charts._entry_cancel()
    assert charts._page == "charts"


# ---------------------------------------------------------------------------
# Zoom, pan and back
# ---------------------------------------------------------------------------
def test_zoom_pan_and_fit(charts, fix):
    _load_ils07(charts, fix)
    charts._footer_charts()
    charts.grab()
    charts._charts_zoom(5)                              # clamps at the last step
    assert charts._charts["zoom"] == len(flight_plan.CHART_ZOOMS) - 1
    view, img = _view(charts)
    r = view["rect"]
    centre = r.center()
    # Zoomed 3x on the page's centre: the dark quarter's corner is there.
    assert _sample(img, centre.x() - 20, centre.y() - 20).lightness() < 40
    assert _sample(img, centre.x() + 20, centre.y() + 20).lightness() > 215
    # Drag the page right and down: the view moves toward its top-left,
    # which is all dark, and stops at the page's edge.
    QTest.mousePress(charts, Qt.MouseButton.LeftButton, pos=centre.toPoint())
    QTest.mouseMove(charts, pos=(centre + QPointF(r.width(), r.height())).toPoint())
    QTest.mouseRelease(charts, Qt.MouseButton.LeftButton,
                       pos=(centre + QPointF(r.width(), r.height())).toPoint())
    view, img = _view(charts)
    assert _sample(img, r.right() - 5, r.bottom() - 5).lightness() < 40
    cx, cy = charts._charts["centre"]
    assert cx == pytest.approx(r.width() / 2 / view["w"], abs=0.01)
    charts._charts_fit()
    assert charts._charts["zoom"] == 0 and charts._charts["centre"] == (0.5, 0.5)


def test_a_press_on_an_unzoomed_chart_is_not_a_drag(charts, fix):
    _load_ils07(charts, fix)
    charts._footer_charts()
    charts.grab()
    centre = charts._plate_view["rect"].center().toPoint()
    QTest.mousePress(charts, Qt.MouseButton.LeftButton, pos=centre)
    assert charts._plate_drag is None
    QTest.mouseRelease(charts, Qt.MouseButton.LeftButton, pos=centre)


def test_back_goes_chart_then_list_then_fpl(charts, fix):
    _load_ils07(charts, fix)
    charts._footer_charts()
    assert charts._enc_back() and charts._page == "charts" and charts._charts["plate"] is None
    assert charts._enc_back() and charts._page == "fpl"
    charts._footer_charts()
    _press(charts, "touch", _by_callback(charts._close_charts))
    assert charts._page == "fpl" and charts._charts is None


# ---------------------------------------------------------------------------
# What it never does
# ---------------------------------------------------------------------------
def test_no_ownship_even_on_a_georeferenced_plate(charts, fix, tmp_path):
    """Guardrail 5. Until an overlay is built and checked against a measured
    error budget, a georef row -- even 'ok' with a tiny residual -- changes
    nothing on the glass."""
    _load_ils07(charts, fix)
    charts._footer_charts()
    before = charts.grab().toImage()
    con = sqlite3.connect(charts.plates_path)
    con.execute("INSERT INTO plate_georef VALUES ('00378IL7.PDF', 'ok', 0.01, 5, 1, 0, 0, 0, "
                "34.4, -119.8, 'test')")
    con.commit()
    con.close()
    charts._plate_index = None
    charts._plate_renderer = plate_render.PlateRenderer()
    assert charts.grab().toImage() == before


def test_an_expired_chart_is_drawn_and_annunciated(page, fix, tmp_path):
    page.plates_path = str(ksba_plates.build(tmp_path / "p.sqlite", cycle="2601",
                                             pdfs={"00378IL7.PDF": _pdf()}))
    _load_ils07(page, fix)
    page._footer_charts()
    view, img = _view(page)
    assert view is not None                              # drawn, not refused
    assert page._cycle_text("2601") == ("AIRAC 2601 EXPIRED", "#ffb000")
    amber = QColor("#ffb000")
    strip = range(int(page.width() * 0.6), page.width() - 10)
    rows = range(int(view["rect"].top()) - 30, int(view["rect"].top()))
    assert any(QColor(img.pixel(x, y)) == amber for x in strip for y in rows)


def test_a_pdf_that_cannot_be_read_is_said_not_raised(page, fix, tmp_path):
    page.plates_path = str(ksba_plates.build(tmp_path / "p.sqlite"))   # junk PDFs
    _load_ils07(page, fix)
    page._footer_charts()
    view, _img = _view(page)
    assert page._charts["plate"] is not None and view is None


def test_without_qtpdf_the_page_says_what_to_install(charts, fix, monkeypatch):
    monkeypatch.setattr(plate_render, "QPdfDocument", None)
    charts._plate_renderer = plate_render.PlateRenderer()
    _load_ils07(charts, fix)
    charts._footer_charts()
    view, _img = _view(charts)
    assert view is None
    assert "python3-pyqt6.qtpdf" in charts._plate_renderer.unavailable_reason


def test_the_registry_declares_the_option(page):
    spec = screenbuilder_factory.REGISTRY["flight_plan"]
    prop = next(p for p in spec.properties if p.name == "plates_path")
    assert prop.default == page.plates_path == ""
