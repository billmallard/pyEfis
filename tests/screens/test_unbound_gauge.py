"""
A gauge marked ``unbound: true`` builds in its failed-sensor state
(AER-5390, BACKLOG FUEL1e, row F5 of the FUEL1 brief).

The configurator binds a fuel gauge to a tank in the aircraft profile. When
that tank is removed, the resolver writes the gauge with no ``dbkey``,
``unbound: true``, and the last label it knew as ``name``. Bill's decision
D3 (2026-11-09): the gauge shows the existing failed-sensor look -- value
text ``xxx``, the bar held at 0, the bad colour set -- with that label, so
the pilot sees "no data" on a named gauge and never reads it as an empty
tank.

The gauge never calls ``fix.db.get_item``. A stale reference cannot stop
the EFIS booting: before this change ``setDbkey`` raised ``KeyError`` on a
key the database does not define, and nothing caught it.
"""
import pytest
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QWidget

import pyefis.hmi as hmi
from pyefis.instruments import gauges
from pyefis.screens.screenbuilder import Screen


@pytest.fixture(autouse=True)
def hmi_actions():
    hmi.initialize({})
    yield


class _Parent(QWidget):
    """The interface screenbuilder.Screen needs from its parent."""

    def __init__(self, screen_config):
        super().__init__()
        self._screen_config = screen_config
        self.config_path = ""
        self.nodeID = 1
        self.preferences = {
            "style": {"basic": True, "dseg": False, "segmented": False,
                      "ghost": False},
            "styles": {}, "gauges": {}, "enabled": {}, "includes": {},
            "buttons": {},
        }

    def get_config_item(self, child, key):
        return self._screen_config.get(key)

    def getRunningScreen(self):
        return "TEST"


def _screen_config(instruments):
    return {
        "layout": {"rows": 10, "columns": 10},
        "instruments": instruments,
        "encoder": None,
        "encoder_button": None,
        "encoder_timeout": None,
    }


@pytest.fixture
def lookups(fix, monkeypatch):
    """Every key passed to fix.db.get_item while the test runs."""
    calls = []
    real = fix.db.get_item

    def spy(key, *args, **kwargs):
        calls.append(key)
        return real(key, *args, **kwargs)

    monkeypatch.setattr(fix.db, "get_item", spy)
    return calls


def _build(qtbot, instruments):
    screen = Screen(_Parent(_screen_config(instruments)))
    qtbot.addWidget(screen)
    screen.resize(800, 480)
    screen.init_screen()
    return screen


def _assert_failed_look(widget, name):
    assert widget.unbound
    assert widget.fail
    assert widget.value == 0.0
    assert widget.valueText == "xxx"
    assert widget.name == name
    assert widget.safeColor == QColor(widget.safe_bad_color)
    assert widget.textColor == QColor(widget.text_bad_color)
    assert widget.penColor == QColor(widget.pen_bad_color)


# A stale dbkey ahead of the flag: the resolver never writes one, but a
# hand-edited or older panel can, and the option order must not matter.
_OPTION_SETS = [
    pytest.param({"unbound": True, "name": "L TIP"}, id="no-dbkey"),
    pytest.param({"dbkey": "FUELQ7", "unbound": True, "name": "L TIP"},
                 id="stale-dbkey-first"),
    pytest.param({"name": "L TIP", "unbound": "true"}, id="quoted-true"),
]


@pytest.mark.parametrize("options", _OPTION_SETS)
@pytest.mark.parametrize("inst_type", [
    "vertical_bar_gauge", "horizontal_bar_gauge", "arc_gauge",
    "numeric_display",
])
def test_screen_with_unbound_gauge_builds_in_fail_state(
        qtbot, lookups, inst_type, options):
    screen = _build(qtbot, [
        {"type": inst_type, "row": 0, "column": 0, "span": {"rows": 4,
         "columns": 2}, "options": dict(options)},
    ])

    _assert_failed_look(screen.instruments[0], "L TIP")
    assert lookups == []


def test_unbound_bar_in_a_ganged_fuel_block_builds(qtbot, fix, lookups):
    """The stock fuel bars are a ganged block: one tank orphaned, its
    neighbour still bound."""
    screen = _build(qtbot, [{
        "type": "ganged_vertical_bar_gauge",
        "gang_type": "horizontal",
        "row": 0, "column": 0, "span": {"rows": 4, "columns": 4},
        "groups": [{
            "name": "Fuel",
            "common_options": {"decimal_places": 1},
            "instruments": [
                {"options": {"name": "L MAIN", "dbkey": "NUMOK"}},
                {"options": {"name": "L TIP", "unbound": True}},
            ],
        }],
    }])

    bound, orphan = screen.instruments[0], screen.instruments[1]
    _assert_failed_look(orphan, "L TIP")
    assert not bound.unbound and not bound.fail
    assert bound.value == pytest.approx(50.91)
    assert "FUELQ7" not in lookups and None not in lookups


def test_unbound_bar_draws_exactly_the_failed_sensor_look(qtbot, fix):
    """D3 is the existing look, not a new one: an unbound bar paints the
    same pixels as a bar whose sensor has failed, with the same label."""
    fix.db.define_item("FAILKEY", "failed sensor", "float", 0, 100, "",
                       50000, "")
    fix.db.set_value("FAILKEY", 37.0)
    fix.db.get_item("FAILKEY").fail = True

    failed = gauges.VerticalBar(min_size=False)
    failed.name = "L TIP"
    failed.setDbkey("FAILKEY")
    unbound = gauges.VerticalBar(min_size=False)
    unbound.name = "L TIP"
    unbound.setUnbound()

    images = []
    for widget in (failed, unbound):
        qtbot.addWidget(widget)
        widget.resize(120, 300)
        widget.show()
        qtbot.waitExposed(widget)
        images.append(widget.grab().toImage())
    assert images[0] == images[1]


def test_unbound_gauge_ignores_unit_switching_and_the_encoder(
        qtbot, lookups):
    widget = gauges.NumericDisplay()
    qtbot.addWidget(widget)
    widget.setUnbound()
    widget.setDbkey("FUELQ7")
    widget.setupGauge()
    widget.conversionFunction1 = widget.conversionFunction2 = lambda x: x
    widget.setUnitSwitching()
    widget.setUnits("*:toggle")

    assert widget.dbkey is None
    assert not widget.enc_selectable()
    assert widget.valueText == "xxx"
    assert lookups == []


def test_unbound_false_is_an_ordinary_bound_gauge(qtbot, fix):
    screen = _build(qtbot, [
        {"type": "vertical_bar_gauge", "row": 0, "column": 0,
         "options": {"dbkey": "NUMOK", "unbound": False, "name": "OIL"}},
    ])

    widget = screen.instruments[0]
    assert not widget.unbound and not widget.fail
    assert widget.value == pytest.approx(50.91)
