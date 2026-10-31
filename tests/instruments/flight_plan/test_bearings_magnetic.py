#  SPDX-License-Identifier: GPL-2.0-or-later
"""Bearings on the FPL page are magnetic, like the HSI and the map
(billmallard/pyEfis#335, AER-4333).

The WPT Info overlay, the Direct-To nearest-airport list and the waypoint
picker computed a great-circle bearing and printed it as-is: true, while the
HSI, the FPL rows' DTK (pyEfis#325) and the map's pointer banner are magnetic.
Around Santa Barbara that is 11.6 degrees off. Each is now ``TRUE + MAGVAR``
(positive west), and labelled ``°T`` when the gateway publishes no MAGVAR,
the same rule as ``map.pointer_banner_text``.

Aircraft over KSBA, target KSMX: true bearing about 312, magnetic about 300.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from pyefis.flightplan import fixbridge, geo
from pyefis.flightplan import model as fp_model
from pyefis.instruments import flight_plan

BEELINK = SimpleNamespace(screenWidth=1920, screenHeight=1080, screenDiagonalInches=21.5)
MAGVAR = -11.6   # positive west: 11.6 E, about Santa Barbara
AC_LAT, AC_LON = 34.42621, -119.84037            # over KSBA
KSMX = fp_model.Waypoint(id="KSMX", type="airport", lat=34.89892, lon=-120.45758,
                         name="SANTA MARIA PUBLIC")

_BOUNDS = {"float": (-1e9, 1e9), "int": (-1_000_000, 1_000_000),
           "bool": (None, None), "str": (None, None)}
_ENGINE = {
    "FPLSTATE": "int", "FPLACTLEG": "int", "FPLPHASE": "str", "FPLAPR": "int",
    "FPLINTEG": "bool", "CDISCALE": "float", "FPLCRS": "float", "FPLXTK": "float",
    "FPLCDI": "float", "FPLTF": "int", "FPLFRLAT": "float", "FPLFRLON": "float",
    "WPNAME": "str", "WPLAT": "float", "WPLON": "float", "WPFROM": "str",
    "WPNEXT": "str", "WPDIS": "float", "WPETE": "int", "FPLREMDIS": "float",
    "FPLREMETE": "int", "FPLALERT": "bool", "GPSSRC": "int",
    "FPLACTSEG": "int", "FPLSEGREM": "float",
}
_BLANK = {"int": 0, "float": 0.0, "bool": False, "str": ""}

TRUE_BRG = geo.initial_bearing(AC_LAT, AC_LON, KSMX.lat, KSMX.lon)
MAG_TEXT = "%03d°" % round(TRUE_BRG + MAGVAR)
TRUE_TEXT = "%03d°T" % round(TRUE_BRG)


def _define(fix, key, dtype, value):
    mn, mx = _BOUNDS[dtype]
    fix.db.define_item(key, key, dtype, mn, mx, "", 0, "")
    fix.db.set_value(key, value)
    item = fix.db.get_item(key)
    item.bad = item.fail = False


def _page(fix, qtbot, monkeypatch, *, route_keys=True, magvar=MAGVAR):
    if route_keys:
        for key, dtype, blank in fixbridge.route_key_specs():
            _define(fix, key, dtype, blank)
        for key, dtype in _ENGINE.items():
            _define(fix, key, dtype, _BLANK[dtype])
    if magvar is not None:
        _define(fix, "MAGVAR", "float", magvar)
    fix.db.set_value("LAT", AC_LAT)
    fix.db.set_value("LONG", AC_LON)
    w = flight_plan.FlightPlan(None)
    qtbot.addWidget(w)
    w.parent = SimpleNamespace(parent=BEELINK)
    w.resize(649, 993)
    assert w._bridge.available == route_keys
    idx = SimpleNamespace(
        nearest=lambda lat, lon, types=None: [
            (KSMX, geo.distance_nm(lat, lon, KSMX.lat, KSMX.lon),
             geo.initial_bearing(lat, lon, KSMX.lat, KSMX.lon), 6304)],
        recent=SimpleNamespace(list=lambda: []))
    monkeypatch.setattr(w, "_ensure_waypoint_index", lambda: idx)
    return w


@pytest.fixture()
def page(fix, qtbot, monkeypatch):
    return _page(fix, qtbot, monkeypatch)


def _texts(paint):
    """Every string a paint call draws, off a mock painter."""
    p = MagicMock()
    paint(p)
    return [c.args[-1] for c in p.drawText.call_args_list]


def _wpt_info(w):
    w._wpt_info = KSMX
    return _texts(lambda p: w._paint_wpt_info(p, w.width(), w.height()))


def _nearest(w):
    return _texts(lambda p: w._paint_dto_nrst_tab(p, w.width(), 0, 400))


def _picker(w):
    w._entry_tab = "Nearest"
    w._entry_mode = None
    return _texts(lambda p: w._paint_entry_list(p, w.width(), 0, 400))


SITES = [_wpt_info, _nearest, _picker]


def test_the_case_is_not_degenerate():
    """The pins below only prove anything if true and magnetic differ here."""
    assert MAG_TEXT != TRUE_TEXT.rstrip("T")


@pytest.mark.parametrize("site", SITES, ids=lambda s: s.__name__)
def test_bearing_is_magnetic_with_magvar(page, site):
    texts = _texts_with_bearing(site(page))
    assert texts, "no bearing drawn"
    assert all(MAG_TEXT in t and "°T" not in t for t in texts), texts


@pytest.mark.parametrize("site", SITES, ids=lambda s: s.__name__)
def test_bearing_is_labelled_true_without_magvar(fix, qtbot, monkeypatch, site):
    w = _page(fix, qtbot, monkeypatch, magvar=None)
    texts = _texts_with_bearing(site(w))
    assert texts and all(TRUE_TEXT in t for t in texts), texts


@pytest.mark.parametrize("site", SITES, ids=lambda s: s.__name__)
def test_bearing_is_labelled_true_without_the_flight_plan_bridge(fix, qtbot, monkeypatch, site):
    """No FPL keys on the gateway: the bridge is unavailable, so there is no
    variation to apply even if MAGVAR exists -- say true, do not guess."""
    w = _page(fix, qtbot, monkeypatch, route_keys=False)
    texts = _texts_with_bearing(site(w))
    assert texts and all(TRUE_TEXT in t for t in texts), texts


def test_north_reads_360_not_000(page, fix):
    fix.db.set_value("MAGVAR", 0.0)
    assert page._brg_text(359.7) == "360°"
    assert page._brg_text(0.2) == "360°"


def _texts_with_bearing(texts):
    return [t for t in texts if "NM" in t]
