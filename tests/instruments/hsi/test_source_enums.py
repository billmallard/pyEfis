#  SPDX-License-Identifier: GPL-2.0-or-later
"""Every value fix-gateway allows on a nav-source selector has an HSI label
(ENUM2, AER-6457).

fix-gateway's ``database/ahrs.yaml`` gives ``NAVSRC``, ``BRG1SRC`` and
``BRG2SRC`` the range 0..3, and its NAVSRC comment reserves 3 for GPS2. The
HSI turns each value into an annunciation through module tables:
``NAVSRC_NAV_SLOTS`` (a NAV radio, VOR/LOC colour) and ``NAVSRC_GPS_LABELS``
(a GPS, GPS colour) for ``NAVSRC``, ``BRGSRC_LABELS`` for the bearing
selectors. Before ENUM2, NAVSRC 3 read "VLOC4" in the radio colour and a
bearing pointer on 3 had no name.

Both sides are read as source (the database with ``yaml``, the HSI with
``ast``), so fix-gateway's CI runs this file from a sparse pyEfis checkout
with no Qt imports, as it runs ``tests/flightplan/test_engine_enums.py``: a
range widened in the gateway goes red there until pyEfis has the label.
``FIXGW_AHRS_DB`` points at the database in CI; with it set, a missing file
is a failure, not a skip.
"""

import ast
import os
import pathlib

import pytest
import yaml

_HSI = (pathlib.Path(__file__).resolve().parents[3] / "src" / "pyefis"
        / "instruments" / "hsi" / "__init__.py")


def _ahrs_path():
    """The database: ``FIXGW_AHRS_DB`` (CI; required), else ``ahrs.yaml`` in
    the ``FIX_GATEWAY_SRC`` checkout the conformance tests use."""
    env = os.environ.get("FIXGW_AHRS_DB")
    if env:
        return pathlib.Path(env), True
    root = pathlib.Path(os.environ.get("FIX_GATEWAY_SRC") or "/nonexistent")
    return root / "src" / "fixgw" / "config" / "database" / "ahrs.yaml", False


def key_values(text, key):
    """Every whole value in ``key``'s ``min``..``max`` range in a fix-gateway
    database file."""
    for item in yaml.safe_load(text)["items"]:
        if item.get("key") == key:
            lo, hi = float(item["min"]), float(item["max"])
            assert lo == int(lo) and hi == int(hi), (key, lo, hi)
            return set(range(int(lo), int(hi) + 1))
    raise AssertionError(f"{key} is not in the database")


def int_dict(source, name):
    """The module-level dict literal ``name`` as {int key: literal value}."""
    for node in ast.parse(source).body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == name and isinstance(node.value, ast.Dict)):
            return {ast.literal_eval(k): ast.literal_eval(v)
                    for k, v in zip(node.value.keys, node.value.values)}
    raise AssertionError(f"no module-level dict literal {name}")


@pytest.fixture(scope="module")
def ahrs():
    path, required = _ahrs_path()
    if not path.is_file():
        if required:
            pytest.fail(f"FIXGW_AHRS_DB={path} does not exist")
        pytest.skip("set FIX_GATEWAY_SRC to a fix-gateway checkout; CI sets "
                    "FIXGW_AHRS_DB")
    return path.read_text()


@pytest.fixture(scope="module")
def hsi_source():
    return _HSI.read_text()


def test_every_navsrc_value_has_a_label_and_one_colour(ahrs, hsi_source):
    values = key_values(ahrs, "NAVSRC")
    # The reader still finds what it was written against.
    assert {0, 1, 2} <= values
    nav = int_dict(hsi_source, "NAVSRC_NAV_SLOTS")
    gps = int_dict(hsi_source, "NAVSRC_GPS_LABELS")
    assert set(nav) & set(gps) == set(), (
        "a NAVSRC value is both a NAV radio and a GPS: it has two colours")
    assert values - set(nav) - set(gps) == set(), (
        "fix-gateway allows these NAVSRC values and the HSI has no label or "
        "colour for them: add them to NAVSRC_NAV_SLOTS (a radio) or "
        "NAVSRC_GPS_LABELS (a GPS) in instruments/hsi")
    assert all(isinstance(v, str) and v for v in gps.values())


@pytest.mark.parametrize("key", ["BRG1SRC", "BRG2SRC"])
def test_every_bearing_source_value_has_a_label(ahrs, hsi_source, key):
    values = key_values(ahrs, key)
    assert {0, 1} <= values
    labels = int_dict(hsi_source, "BRGSRC_LABELS")
    assert values - set(labels) == set(), (
        f"fix-gateway allows these {key} values and the HSI has no bearing-"
        "source label for them: add them to BRGSRC_LABELS in instruments/hsi")
    assert all(isinstance(v, str) and v for v in labels.values())


def test_gps2_is_labelled_as_a_gps():
    """Bill's ruling for ENUM2: NAVSRC 3 is GPS2, in the GPS colour."""
    source = _HSI.read_text()
    assert int_dict(source, "NAVSRC_GPS_LABELS")[3] == "GPS2"
    assert int_dict(source, "BRGSRC_LABELS")[3] == "GPS2"


def test_the_readers_catch_a_new_value():
    """The coverage tests fail for the change they exist to catch: a range
    widened past the tables (the pre-ENUM2 HSI, against today's range)."""
    db = ("items:\n- key: NAVSRC\n  type: float\n  min: 0.0\n  max: 3.0\n"
          "- key: BRG1SRC\n  type: float\n  min: 0.0\n  max: 2.0\n")
    assert key_values(db, "NAVSRC") == {0, 1, 2, 3}
    assert key_values(db, "BRG1SRC") == {0, 1, 2}
    old = ('NAVSRC_NAV_SLOTS = {0: 1, 1: 2}\nNAVSRC_GPS_LABELS = {2: "GPS"}\n'
           'BRGSRC_LABELS = {0: "VOR1", 1: "VOR2", 2: "GPS"}\n')
    nav, gps = int_dict(old, "NAVSRC_NAV_SLOTS"), int_dict(old, "NAVSRC_GPS_LABELS")
    assert key_values(db, "NAVSRC") - set(nav) - set(gps) == {3}
    with pytest.raises(AssertionError):
        int_dict(old, "MISSING")
    with pytest.raises(AssertionError):
        key_values(db, "BRG2SRC")
