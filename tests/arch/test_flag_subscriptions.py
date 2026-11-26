"""Ratchet on hand-rolled FIX flag subscriptions (ARCHG4, AER-6678).

ARCH3 section 4.2 counts the widgets that subscribe to a FIX item's quality
flags (``old``, ``bad``, ``fail``) by hand instead of through a shared helper,
and INS6 plans to fold them onto one.  Until it does, nothing stopped the count
growing by copy.  ``flag_subscriptions.yaml`` holds a per-file count of flag
subscription sites under ``src/pyefis``; this test fails when a file's count
rises or a file not in the baseline gains a site, and warns when a count falls,
so lowering the baseline is a reviewed one-line edit in the same diff.

A site is any of:

- a ``failChanged``, ``oldChanged`` or ``badChanged`` attribute reference;
- a string constant naming one of those signals (``getattr(item, "oldChanged")``,
  a signal-name tuple);
- a signal name built at run time: ``flag + "Changed"`` or ``f"{flag}Changed"``.

The scan reads the AST, so comments and docstrings do not count; that is why
the totals here are lower than a plain ``grep`` over the same tree.  The shared
helpers are excluded: they are where the subscriptions are meant to go.

Regenerate the baseline (after a reviewed reduction) with
``python -m tests.arch.test_flag_subscriptions``.
"""

import ast
import pathlib
import shutil
import warnings

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
SRC = REPO / "src" / "pyefis"
BASELINE = pathlib.Path(__file__).with_name("flag_subscriptions.yaml")

FLAG_SIGNALS = {"failChanged", "oldChanged", "badChanged"}

# The shared helpers, relative to src/pyefis: the place these belong.
EXCLUDED = {
    "instruments/helpers/bugs.py",
    "instruments/conditions.py",
    "instruments/gauges/abstract.py",
}


def _is_dynamic_name(node):
    """``x + "Changed"`` or ``f"{x}Changed"``: a signal name built at run time."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        right = node.right
        return isinstance(right, ast.Constant) and right.value == "Changed"
    if isinstance(node, ast.JoinedStr) and len(node.values) >= 2:
        last = node.values[-1]
        return (isinstance(last, ast.Constant) and last.value == "Changed"
                and isinstance(node.values[-2], ast.FormattedValue))
    return False


def count_sites(source):
    """Number of flag-subscription sites in one module's source."""
    count = 0
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute) and node.attr in FLAG_SIGNALS:
            count += 1
        elif isinstance(node, ast.Constant) and node.value in FLAG_SIGNALS:
            count += 1
        elif _is_dynamic_name(node):
            count += 1
    return count


def scan(root):
    """``{path relative to root: count}`` for every file with a site."""
    counts = {}
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if rel in EXCLUDED:
            continue
        n = count_sites(path.read_text(encoding="utf-8"))
        if n:
            counts[rel] = n
    return counts


def compare(counts, baseline):
    """``(rises, falls)``, each a list of readable lines."""
    rises, falls = [], []
    for rel, n in sorted(counts.items()):
        was = baseline.get(rel)
        if was is None:
            rises.append(f"{rel}: new file with {n} flag subscription site(s)")
        elif n > was:
            rises.append(f"{rel}: {was} -> {n}")
        elif n < was:
            falls.append(f"{rel}: {was} -> {n}")
    for rel, was in sorted(baseline.items()):
        if rel not in counts:
            falls.append(f"{rel}: {was} -> 0")
    return rises, falls


def load_baseline():
    data = yaml.safe_load(BASELINE.read_text(encoding="utf-8"))
    assert data["total"] == sum(data["files"].values()), "baseline total is stale"
    return data["files"]


def test_flag_subscriptions_do_not_rise():
    rises, falls = compare(scan(SRC), load_baseline())
    if falls:
        warnings.warn(
            "flag subscription count fell; lower tests/arch/flag_subscriptions.yaml "
            "to match:\n  " + "\n  ".join(falls))
    assert not rises, (
        "hand-rolled FIX flag subscriptions rose (ARCHG4).  Subscribe through a "
        "shared helper (instruments/helpers/bugs.py, instruments/conditions.py) "
        "instead; raising the baseline is an architecture change for review:\n  "
        + "\n  ".join(rises))


def test_baseline_names_real_files_and_excludes_helpers():
    baseline = load_baseline()
    assert all(n > 0 for n in baseline.values())
    assert not EXCLUDED & set(baseline)
    for rel in baseline:
        assert (SRC / rel).is_file(), rel


def test_map_loop_is_counted():
    # The map's loop builds the name (``flag + "Changed"``), which the
    # register's plain grep missed.
    assert load_baseline().get("instruments/map/__init__.py", 0) > 0


@pytest.fixture
def tree(tmp_path):
    """A copy of src/pyefis to edit, and its baseline."""
    root = tmp_path / "pyefis"
    shutil.copytree(SRC, root)
    baseline = load_baseline()
    assert compare(scan(root), baseline) == ([], []), \
        "baseline does not match dev; fix that first"
    return root, baseline


def _append(root, rel, code):
    path = root / rel
    path.write_text(path.read_text(encoding="utf-8") + code, encoding="utf-8")


def test_control_literal_connect_fails(tree):
    root, baseline = tree
    _append(root, "instruments/wind/__init__.py",
            "\n\ndef _extra(item, cb):\n    item.badChanged.connect(cb)\n")
    rises, _ = compare(scan(root), baseline)
    assert rises == ["instruments/wind/__init__.py: 6 -> 7"]


def test_control_dynamic_loop_fails(tree):
    root, baseline = tree
    _append(root, "instruments/wind/__init__.py",
            "\n\ndef _extra(item, cb):\n"
            "    for flag in ('old', 'bad', 'fail'):\n"
            "        getattr(item, flag + \"Changed\").connect(cb)\n")
    rises, _ = compare(scan(root), baseline)
    assert rises == ["instruments/wind/__init__.py: 6 -> 7"]


def test_control_fstring_and_new_file_fail(tree):
    root, baseline = tree
    (root / "instruments" / "newwidget.py").write_text(
        "def _extra(item, cb):\n"
        "    getattr(item, f\"{'old'}Changed\").connect(cb)\n", encoding="utf-8")
    rises, _ = compare(scan(root), baseline)
    assert rises == ["instruments/newwidget.py: new file with 1 flag subscription site(s)"]


def test_control_comments_and_helpers_do_not_count(tree):
    root, baseline = tree
    _append(root, "instruments/wind/__init__.py", "\n# item.badChanged.connect(cb)\n")
    _append(root, "instruments/conditions.py",
            "\n\ndef _extra(item, cb):\n    item.badChanged.connect(cb)\n")
    assert compare(scan(root), baseline) == ([], [])


def test_control_fall_is_a_notice_not_a_failure(tree):
    root, baseline = tree
    path = root / "instruments" / "wind" / "__init__.py"
    path.write_text("", encoding="utf-8")
    rises, falls = compare(scan(root), baseline)
    assert rises == [] and falls == ["instruments/wind/__init__.py: 6 -> 0"]


if __name__ == "__main__":
    counts = scan(SRC)
    print(yaml.safe_dump({"total": sum(counts.values()), "files": counts},
                         sort_keys=False), end="")
