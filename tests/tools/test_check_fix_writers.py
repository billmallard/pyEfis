"""tools/check_fix_writers.py: pyEfis's FIX key writes are declared in fix-gateway's
writer register, and no new class takes a route-concept name (ARCHG2, AER-6403).

These run fix-gateway's real scanner and register at the pinned commit, fetched
the way the CI step fetches them.  Without network that fetch fails: a skip
locally, a failure under CI (where the gate step has already fetched it).
"""

import importlib.util
import os
import pathlib
import shutil
import subprocess
import textwrap

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("check_fix_writers", ROOT / "tools" / "check_fix_writers.py")
cfw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cfw)


@pytest.fixture(scope="module")
def pinned():
    """(checkout, sha, scanner module, catalog) at the pin."""
    try:
        fixgw, sha = cfw.pinned_checkout()
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        if os.environ.get("CI"):
            pytest.fail("could not fetch fix-gateway at the pin: %s" % e)
        pytest.skip("could not fetch fix-gateway at the pin (no network?)")
    kw = cfw.load_scanner(fixgw)
    return fixgw, sha, kw, kw.load_catalog(str(fixgw))


def tree(tmp_path, files):
    """A pyEfis-shaped tree holding `files` (rel path -> source), with the pin."""
    for rel, src in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(src))
    (tmp_path / "tests" / "arch").mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / cfw.PIN_FILE, tmp_path / cfw.PIN_FILE)
    return tmp_path


def test_dev_passes(pinned):
    fixgw, _, _, catalog = pinned
    fails, notices, _ = cfw.run_checks(ROOT, fixgw, catalog)
    assert fails == []
    assert notices == []


def test_a_second_baro_writer_fails(pinned, tmp_path):
    """The altimeter knob is BARO's declared pyEfis writer; another instrument
    writing it is not declared, and the check names it."""
    fixgw, _, _, catalog = pinned
    root = tree(tmp_path, {
        "src/pyefis/instruments/altimeter/__init__.py": """
            from pyefis import fix
            def knob(v):
                item = fix.db.get_item("BARO")
                item.value = v
            """,
        "src/pyefis/instruments/baro_box/__init__.py": """
            from pyefis import fix
            def press():
                fix.db.set_value("BARO", 29.92)
            """,
    })
    fails, _, sha = cfw.run_checks(root, fixgw, catalog)
    assert fails == [
        "BARO: pyefis/instruments/baro_box writes it "
        "(src/pyefis/instruments/baro_box/__init__.py:4), and fix-gateway's writers.yaml at "
        "%s does not list pyefis/instruments/baro_box under `pyefis`; declare it in "
        "fix-gateway writers.yaml first, then bump tests/arch/fix_gateway.pin "
        "(docs/key_writers.md)" % sha[:12]]


def test_a_write_to_an_unregistered_key_fails(pinned, tmp_path):
    """A key no module writes today (so it has no register line at all)."""
    fixgw, _, _, catalog = pinned
    root = tree(tmp_path, {"src/pyefis/instruments/hsi/__init__.py": """
        from pyefis import fix
        fix.db.set_value("ALT", 1000)
        """})
    fails, _, _ = cfw.run_checks(root, fixgw, catalog)
    assert len(fails) == 1
    assert fails[0].startswith("ALT: pyefis/instruments/hsi writes it")
    assert "declare it in fix-gateway writers.yaml first" in fails[0]


def test_a_declared_writer_that_stopped_writing_is_a_notice(pinned, tmp_path):
    """Failing here would need both repos to change at once; fix-gateway fixes it."""
    fixgw, _, _, catalog = pinned
    fails, notices, _ = cfw.run_checks(tree(tmp_path, {}), fixgw, catalog)
    assert fails == []
    assert ("BARO: fix-gateway's writers.yaml lists pyefis/instruments/altimeter under "
            "`pyefis`, and the scan finds no write from it; remove it there") in notices


def test_a_new_class_waypoint_fails(pinned, tmp_path):
    fixgw, _, _, catalog = pinned
    allowed = (ROOT / cfw.CONCEPTS).read_text()
    listed = {"src/pyefis/flightplan/" + f: (ROOT / "src/pyefis/flightplan" / f).read_text()
              for f in ("model.py", "waypoints.py", "fixbridge.py", "procedures.py")}
    root = tree(tmp_path, dict(listed, **{
        cfw.CONCEPTS: allowed,
        "src/pyefis/instruments/map/route.py": """
            class Waypoint:
                pass
            """,
    }))
    fails, _, _ = cfw.run_checks(root, fixgw, catalog)
    assert fails == [
        "class Waypoint: defined in src/pyefis/instruments/map/route.py, and concept_names.yaml "
        "allows it only in src/pyefis/flightplan/model.py, src/pyefis/flightplan/waypoints.py.  "
        "Use the existing Waypoint, or name the new shape for what it is; adding the file to "
        "tests/arch/concept_names.yaml is an architecture change (ORG-018) for review"]


def test_a_listed_file_that_no_longer_defines_the_class_fails(pinned, tmp_path):
    fixgw, _, _, catalog = pinned
    root = tree(tmp_path, {cfw.CONCEPTS: "Segment: [src/pyefis/flightplan/model.py]\n",
                           "src/pyefis/flightplan/model.py": "x = 1\n"})
    fails, _, _ = cfw.run_checks(root, fixgw, catalog)
    assert fails == ["class Segment: concept_names.yaml lists src/pyefis/flightplan/model.py, "
                     "which no longer defines it; remove the file from the list"]


def test_a_checkout_off_the_pin_is_refused(pinned, tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t",
                    "commit", "-q", "--allow-empty", "-m", "x"], check=True)
    with pytest.raises(cfw.PinError, match="pins %s" % pinned[1]):
        cfw.pinned_checkout(tmp_path)


@pytest.mark.parametrize("text", [
    "",
    "29cd2ba\n",
    "29cd2ba7057defd120a578bf1151a025e867058f\n29cd2ba7057defd120a578bf1151a025e867058f\n",
    "dev\n",
])
def test_the_pin_is_one_full_sha(tmp_path, text):
    (tmp_path / "tests" / "arch").mkdir(parents=True)
    (tmp_path / cfw.PIN_FILE).write_text("# comment\n" + text)
    with pytest.raises(cfw.PinError, match="exactly one full 40-character commit SHA"):
        cfw.read_pin(tmp_path)


def test_the_committed_pin_parses():
    assert len(cfw.read_pin()) == 40
