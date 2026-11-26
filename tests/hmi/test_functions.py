import pytest
from unittest.mock import MagicMock, patch
import pyefis.hmi.functions


# Mock the fix module
@pytest.fixture
def fix_mock():
    with patch("pyefis.hmi.functions.fix") as fix_mock:
        yield fix_mock


# Test for setValue function
def test_setValue(fix_mock):
    # Mocking the arg for setValue
    arg = "key,value"
    # Setting up the mock for the item
    item_mock = MagicMock()
    item_mock.value = None
    fix_mock.db.get_item.return_value = item_mock

    # Calling the function
    pyefis.hmi.functions.setValue(arg)

    # Assertions
    fix_mock.db.get_item.assert_called_once_with("key")
    assert item_mock.value == "value"
    assert item_mock.output_value.called


# Test for changeValue function
def test_changeValue(fix_mock):
    # Mocking the arg for changeValue
    arg = "key,1"
    # Setting up the mock for the item
    item_mock = MagicMock()
    item_mock.value = 1
    item_mock.dtype.return_value = 1
    fix_mock.db.get_item.return_value = item_mock

    # Calling the function
    pyefis.hmi.functions.changeValue(arg)

    # Assertions
    fix_mock.db.get_item.assert_called_once_with("key")
    assert item_mock.value == 2
    assert item_mock.dtype.called
    assert item_mock.output_value.called


class _Item:
    """A minimal numeric FIX item for the wrap/sync math (MagicMock can't do
    real arithmetic on .min / .max / .value)."""
    def __init__(self, value=0.0, mn=0.0, mx=359.9):
        self.value = value
        self.min = mn
        self.max = mx
        self.dtype = float
        self.output_called = False

    def output_value(self):
        self.output_called = True


# changeValueWrap wraps within [min, max] instead of clamping. Without a
# period the span is max - min, so HEADBUG (0..359.9) lands 0 - 1 on 358.9.
def test_changeValueWrap_without_period_spans_max_minus_min(fix_mock):
    item = _Item(0.0, 0.0, 359.9)
    fix_mock.db.get_item.return_value = item
    pyefis.hmi.functions.changeValueWrap("HEADBUG, -1")
    assert round(item.value, 1) == 358.9
    assert item.output_called


# DSP2b (AER-6707): a declared 360 period makes HEADBUG a real circle.
def test_changeValueWrap_period_360_down_across_zero(fix_mock):
    item = _Item(0.0, 0.0, 359.9)
    fix_mock.db.get_item.return_value = item
    pyefis.hmi.functions.changeValueWrap("HEADBUG, -1, 360")
    assert item.value == 359.0
    assert item.output_called


def test_changeValueWrap_period_360_up_across_max(fix_mock):
    item = _Item(359.0, 0.0, 359.9)
    fix_mock.db.get_item.return_value = item
    pyefis.hmi.functions.changeValueWrap("HEADBUG, 1, 360")
    assert item.value == 0.0
    item.value = 357.0
    pyefis.hmi.functions.changeValueWrap("HEADBUG, 5, 360")
    assert item.value == 2.0


def test_changeValueWrap_period_360_stays_on_whole_degrees(fix_mock):
    # Ten presses down from 005 never leave a whole degree (the 359.9 span
    # left every press after the wrap 0.1 off).
    item = _Item(5.0, 0.0, 359.9)
    fix_mock.db.get_item.return_value = item
    seen = []
    for _ in range(10):
        pyefis.hmi.functions.changeValueWrap("HEADBUG, -1, 360")
        seen.append(item.value)
    assert seen == [4.0, 3.0, 2.0, 1.0, 0.0, 359.0, 358.0, 357.0, 356.0, 355.0]


def test_changeValueWrap_up_across_max(fix_mock):
    item = _Item(357.0, 0.0, 359.9)
    fix_mock.db.get_item.return_value = item
    pyefis.hmi.functions.changeValueWrap("HEADBUG, 5")
    assert round(item.value, 1) == 2.1


def test_changeValueWrap_within_range_is_plain_add(fix_mock):
    item = _Item(100.0, 0.0, 359.9)
    fix_mock.db.get_item.return_value = item
    pyefis.hmi.functions.changeValueWrap("HEADBUG, 20")
    assert round(item.value, 1) == 120.0


# NAVSRC is 0..3 on the bus; the shipped CDI SRC action declares no period, so
# it cycles 0, 1, 2 and never reaches 3 (GPS2). Nothing writes 3 yet; pinned so
# a change to the default span is a deliberate one (DSP2b).
def test_changeValueWrap_navsrc_cycles_0_1_2(fix_mock):
    item = _Item(0, 0, 3)
    item.dtype = int
    fix_mock.db.get_item.return_value = item
    seen = []
    for _ in range(4):
        pyefis.hmi.functions.changeValueWrap("NAVSRC, 1")
        seen.append(item.value)
    assert seen == [1, 2, 0, 1]


def _wrap_args_shipped():
    """Every 'change value wrap' arg in the shipped buttons and databindings."""
    import pathlib
    import yaml
    cfg = pathlib.Path(pyefis.hmi.functions.__file__).resolve().parents[1] / "config"
    out = []
    for f in sorted((cfg / "buttons").glob("*.yaml")):
        for cond in (yaml.safe_load(f.read_text()) or {}).get("conditions", []) or []:
            for act in cond.get("actions", []) or []:
                if "change value wrap" in act:
                    out.append((f.name, act["change value wrap"]))
    db = yaml.safe_load((cfg / "databindings" / "default.yaml").read_text())
    for b in db["items"]:
        if isinstance(b, dict) and b.get("action") == "change value wrap":
            out.append(("databindings/default.yaml", b["args"]))
    return out


# The shipped heading-bug controls declare the 360 circle (button files and the
# panel databindings alike); CDI SRC declares none.
def test_shipped_wrap_actions_declare_their_circle():
    args = _wrap_args_shipped()
    headbug = [(f, a) for f, a in args if a.split(",")[0].strip() == "HEADBUG"]
    navsrc = [(f, a) for f, a in args if a.split(",")[0].strip() == "NAVSRC"]
    assert len(headbug) >= 4, headbug
    assert navsrc, args
    for f, a in headbug:
        parts = [p.strip() for p in a.split(",")]
        assert len(parts) == 3 and float(parts[2]) == 360.0, (f, a)
    for f, a in navsrc:
        assert len(a.split(",")) == 2, (f, a)


# syncValue copies the source key's value into the destination key.
def test_syncValue(fix_mock):
    dest = _Item(0.0)
    src = _Item(287.0)
    fix_mock.db.get_item.side_effect = lambda k: {"HEADBUG": dest, "HEAD": src}[k.strip()]
    pyefis.hmi.functions.syncValue("HEADBUG, HEAD")
    assert dest.value == 287.0
    assert dest.output_called


# Test for toggleBool function
def test_toggleBool(fix_mock):
    # Mocking the arg for toggleBool
    arg = "key"
    # Setting up the mock for the item
    item_mock = MagicMock()
    item_mock.value = False
    fix_mock.db.get_item.return_value = item_mock

    # Calling the function
    pyefis.hmi.functions.toggleBool(arg)

    # Assertions
    fix_mock.db.get_item.assert_called_once_with("key")
    assert item_mock.value == True
    assert item_mock.output_value.called
