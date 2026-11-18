#  SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for tools/hazard_coverage.py and docs/safety/hazard_paths.yaml.

Two things are pinned. The list stays tied to the hazard assessment: every listed path
exists, every cited row is a row of fha_avionics_stack.md, and every PFD row is carried
by at least one listed module, so a new PFD row cannot land without the list noticing.
The report counts only requirement-tagged tests: a small coverage data file is built
here with one tagged and one untagged test context, and the tagged column must hold
exactly the lines the tagged test ran. No Qt."""

import datetime
import importlib.util
import json
import re
import textwrap
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("hazard_coverage", _ROOT / "tools" / "hazard_coverage.py")
hc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hc)
_vspec = importlib.util.spec_from_file_location("verification_report", _ROOT / "tools" / "verification_report.py")
vr = importlib.util.module_from_spec(_vspec)
_vspec.loader.exec_module(vr)

PATHS = _ROOT / "docs" / "safety" / "hazard_paths.yaml"
FHA = _ROOT / "docs" / "safety" / "fha_avionics_stack.md"


# ---------------------------------------------------------------- the list itself

def _fha_rows():
    rows = set()
    for line in FHA.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("|"):
            row = vr._row_id(vr._cells(line))
            if row:
                rows.add(row)
    return rows


def test_every_listed_path_exists():
    doc = yaml.safe_load(PATHS.read_text(encoding="utf-8"))
    assert doc["modules"], "the hazard-path list is empty"
    for section in ("modules", "not_listed"):
        for m in doc[section]:
            assert (_ROOT / m["path"]).exists(), f"{section}: {m['path']} does not exist"


def test_every_cited_row_is_in_the_hazard_assessment():
    rows = _fha_rows()
    assert {"PFD-1", "GW-2", "NAV-2"} <= rows, "the FHA row parser found no rows"
    doc = yaml.safe_load(PATHS.read_text(encoding="utf-8"))
    for m in doc["modules"]:
        assert m["rows"], f"{m['path']} cites no hazard row"
        assert m.get("why"), f"{m['path']} gives no reason"
        for r in m["rows"]:
            assert r in rows, f"{m['path']} cites {r}, which is not a row of {FHA.name}"


def test_every_pfd_row_is_carried_by_a_listed_module():
    """A PFD row added to the hazard assessment must be placed on a module here."""
    doc = yaml.safe_load(PATHS.read_text(encoding="utf-8"))
    carried = {r for m in doc["modules"] for r in m["rows"]}
    missing = sorted((r for r in _fha_rows() if r.startswith("PFD-")), key=lambda r: int(r[4:]))
    missing = [r for r in missing if r not in carried]
    assert not missing, f"PFD rows with no module in {PATHS.name}: {missing}"


def test_listed_and_not_listed_do_not_overlap():
    doc = yaml.safe_load(PATHS.read_text(encoding="utf-8"))
    listed = {m["path"] for m in doc["modules"]}
    assert len(listed) == len(doc["modules"]), "a module is listed twice"
    assert not listed & {m["path"] for m in doc["not_listed"]}


def test_report_only_until_is_a_date():
    spec = hc.load_paths(PATHS)
    datetime.date.fromisoformat(spec["report_only_until"])


# ---------------------------------------------------------------- which tests count

def _t(nodeid, ids, outcome="passed"):
    return {"nodeid": nodeid, "ids": ids, "outcome": outcome}


def test_tagged_tests_count_requirement_ids_only_and_fold_parameters():
    record = {"tests": [
        _t("tests/a.py::test_req[p0]", ["XX-ANN-001"]),
        _t("tests/a.py::test_req[p1]", ["XX-ANN-001", "XX-TC-001"]),
        _t("tests/a.py::Cls::test_tc_only", ["XX-TC-002"]),
        _t("tests/a.py::test_untagged", []),
    ]}
    assert hc.tagged_tests(record) == {"tests/a.py::test_req": ["XX-ANN-001"]}


@pytest.mark.parametrize("context,expected", [
    ("tests/a.py::test_x|run", "tests/a.py::test_x"),
    ("tests/a.py::Cls::test_x[1-a|b]|setup", "tests/a.py::Cls::test_x"),
    ("", None),
])
def test_context_function(context, expected):
    assert hc.context_function(context) == expected


# ---------------------------------------------------------------- the measurement

MODULE = textwrap.dedent('''
    def tagged_path(x):
        if x > 0:
            return "positive"
        return "other"


    def untagged_path():
        a = 1
        b = 2
        return a + b
''')


@pytest.fixture
def measured(tmp_path, monkeypatch):
    """A coverage data file in which ``tests/t.py::test_tagged`` ran ``tagged_path(1)``
    and ``tests/t.py::test_untagged`` ran ``untagged_path()``."""
    import coverage
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pkg").mkdir()
    src = tmp_path / "pkg" / "mod.py"
    src.write_text(MODULE)
    data_file = tmp_path / ".coverage"
    cov = coverage.Coverage(data_file=str(data_file), branch=True, config_file=False)
    cov.start()
    try:
        spec = importlib.util.spec_from_file_location("hc_measured_mod", src)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        cov.switch_context("tests/t.py::test_tagged[case]|run")
        mod.tagged_path(1)
        cov.switch_context("tests/t.py::test_untagged|run")
        mod.untagged_path()
    finally:
        cov.stop()
        cov.save()
    record = {
        "repo": "billmallard/pyEfis", "name": "pyEfis", "ref": "dev", "sha": "0" * 40,
        "run_url": "", "total": 2, "requirements": {"XX-ANN-001": {"title": "", "doc": ""}},
        "tests": [_t("tests/t.py::test_tagged[case]", ["XX-ANN-001"]),
                  _t("tests/t.py::test_untagged", [])],
    }
    (tmp_path / "rec.json").write_text(json.dumps(record))
    (tmp_path / "paths.yaml").write_text(textwrap.dedent('''
        version: 1
        report_only_until: 2026-12-19
        modules:
          - path: pkg/mod.py
            rows: [PFD-1]
            why: Test module.
    '''))
    return tmp_path


def test_report_counts_only_the_tagged_tests_lines(measured):
    rc = hc.main(["report", "--paths", "paths.yaml", "--coverage", ".coverage",
                  "--record", "rec.json", "--out", "out/hazard_coverage.json"])
    assert rc == 0
    rec = json.loads((measured / "out" / "hazard_coverage.json").read_text())
    (m,) = rec["modules"]
    # 8 statements: two defs, the if, two returns, and untagged_path's three-line body.
    assert m["all_tests"]["num_statements"] == 8
    # The whole suite ran everything except `return "other"`.
    assert m["all_tests"]["covered_lines"] == 7
    # Tagged: the two defs (import time counts in both columns), the if and
    # `return "positive"`. Not untagged_path's body, which only the untagged test ran.
    assert m["tagged_tests"]["covered_lines"] == 4
    # Branches: the if has two; the tagged test took one of them.
    assert m["tagged_tests"]["num_branches"] == 2
    assert m["tagged_tests"]["covered_branches"] == 1
    assert m["requirements_reaching"] == ["XX-ANN-001"]
    assert rec["tagged_test_functions"] == 1
    assert rec["requirements_cited_not_defined"] == []
    assert rec["total"]["tagged_tests"]["covered_lines"] == 4


def test_a_module_no_tagged_test_reaches_reports_only_import_time_lines(measured):
    rec_path = measured / "rec.json"
    rec = json.loads(rec_path.read_text())
    rec["tests"][0]["ids"] = []          # nothing is tagged now
    rec_path.write_text(json.dumps(rec))
    assert hc.main(["report", "--paths", "paths.yaml", "--coverage", ".coverage",
                    "--record", "rec.json", "--out", "out.json"]) == 0
    (m,) = json.loads((measured / "out.json").read_text())["modules"]
    assert m["tagged_tests"]["covered_lines"] == 2          # the two defs
    assert m["tagged_tests"]["covered_branches"] == 0
    assert m["tagged_tests"]["num_statements"] == m["all_tests"]["num_statements"]
    assert m["requirements_reaching"] == []


# ---------------------------------------------------------------- rendering

def _sample(until="2026-12-19"):
    n = {"num_statements": 10, "covered_lines": 4, "num_branches": 4, "covered_branches": 1}
    return {
        "schema": hc.SCHEMA, "repo": "billmallard/pyEfis", "name": "pyEfis", "ref": "dev",
        "sha": "a" * 40, "run_url": "https://github.com/billmallard/pyEfis/actions/runs/1",
        "paths_file": "docs/safety/hazard_paths.yaml", "report_only_until": until,
        "tagged_test_functions": 3, "tagged_test_outcomes": {"passed": 3}, "suite_tests": 9,
        "requirements_cited": ["XX-ANN-001"], "requirements_cited_not_defined": [],
        "modules": [{"path": "src/pyefis/fix_watchdog.py", "rows": ["GW-2"], "why": "Watchdog.",
                     "all_tests": dict(n, covered_lines=9), "tagged_tests": n,
                     "requirements_reaching": ["XX-ANN-001"]}],
        "total": {"all_tests": dict(n, covered_lines=9), "tagged_tests": n},
    }


def test_mode_line_says_when_the_report_only_period_has_ended():
    rec = _sample()
    assert "not a gate, until 2026-12-19" in hc.mode_line(rec, datetime.date(2026, 12, 19))
    ended = hc.mode_line(rec, datetime.date(2026, 12, 20))
    assert "ended on 2026-12-19" in ended and "due" in ended


def test_summary_shows_both_columns(tmp_path, capsys):
    p = tmp_path / "h.json"
    p.write_text(json.dumps(_sample()))
    assert hc.main(["summary", str(p)]) == 0
    out = capsys.readouterr().out
    assert "| `src/pyefis/fix_watchdog.py` | GW-2 | 4/10 (40.0%) | 1/4 (25.0%) | 9/10 (90.0%) |" in out


def test_page_wording_is_public_text(tmp_path):
    p = tmp_path / "h.json"
    p.write_text(json.dumps(_sample()))
    out = tmp_path / "site" / "hazard_coverage.html"
    assert hc.main(["page", str(p), "--out", str(out)]) == 0
    text = out.read_text()
    assert vr.STANDING_TEXT in text
    assert not vr.find_public_text_faults(vr.visible_text(text))
    body = re.sub(r"<div class=notice id=standing-text>.*?</div>", "", text, flags=re.S)
    words = re.sub(r"<[^>]+>", " ", body).lower()
    for word in vr.BANNED_WORDS:
        assert not re.search(rf"\b{word}\b", words), word
    assert "certif" not in words


def test_page_refuses_to_publish_a_leak(tmp_path):
    rec = _sample()
    rec["modules"][0]["path"] = "src/pyefis/x.py on 192.0.2.20"
    p = tmp_path / "h.json"
    p.write_text(json.dumps(rec))
    out = tmp_path / "hazard_coverage.html"
    assert hc.main(["page", str(p), "--out", str(out)]) == 2
    assert not out.exists()
