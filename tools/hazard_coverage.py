#!/usr/bin/env python3
#  SPDX-License-Identifier: GPL-2.0-or-later
"""Coverage that requirement-tagged tests achieve on the hazard-path modules.

``docs/safety/hazard_paths.yaml`` lists the modules on the primary flight display's
data path. This reports, for those modules only, the statement and branch coverage
achieved by the tests that cite a requirement ID, beside the coverage the whole suite
achieves on the same modules. The gap between the two columns is code that runs under
test but that no requirement-based test exercises.

A test is requirement-tagged when its docstring or decorators cite a requirement ID
(``AI-ANN-001``; a test-case ID such as ``HSI-TC-001`` is a catalogue entry and does not
count). That is the same rule the test-evidence page uses, read from the same record,
so the two cannot disagree about which tests count.

No second test run: pytest already records which test executed each line
(``--cov-context=test`` in ``pyproject.toml``), so ``report`` filters the suite's own
coverage data to the tagged tests' contexts. Lines that run outside any test -- the
``def``, ``class`` and import lines executed when a module is imported at collection --
count as covered in both columns: they run whatever the tests are, and crediting them to
neither would make the gap look wider than it is.

It is a report, not a gate, until ``report_only_until`` in the YAML. ``report`` exits 0
whatever the numbers are; after that date the summary says the report-only period has
ended and that gating is the project owner's decision.

Usage (CI, after pytest and ``verification_report.py collect``):
    python tools/hazard_coverage.py report --paths docs/safety/hazard_paths.yaml \
        --coverage .coverage --record reports/verification.json --out reports/hazard_coverage.json
    python tools/hazard_coverage.py summary reports/hazard_coverage.json >> "$GITHUB_STEP_SUMMARY"
    python tools/hazard_coverage.py page reports/hazard_coverage.json --out site/hazard_coverage.html

``report`` needs ``coverage`` and ``PyYAML`` (both installed with the application);
``summary`` and ``page`` are standard library only, so the page job does not install it.
"""

import argparse
import datetime
import html
import json
import pathlib
import re
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from verification_report import CSS, STANDING_TEXT, find_leaks, sanitize  # noqa: E402

SCHEMA = "hazard-coverage/1"


# --------------------------------------------------------------------------- inputs

def load_paths(path):
    import yaml
    doc = yaml.safe_load(pathlib.Path(path).read_text(encoding="utf-8"))
    until = doc.get("report_only_until")
    if isinstance(until, datetime.date):
        until = until.isoformat()
    return {"modules": doc.get("modules") or [], "report_only_until": until or ""}


def _function_id(nodeid):
    """``tests/a.py::Cls::test_x[p1]`` -> ``tests/a.py::Cls::test_x``."""
    return nodeid.split("[", 1)[0]


def tagged_tests(record):
    """{function node id: sorted requirement IDs} for tests citing a requirement ID."""
    out = {}
    for t in record["tests"]:
        ids = [i for i in t.get("ids", []) if "-TC-" not in i]
        if ids:
            out.setdefault(_function_id(t["nodeid"]), set()).update(ids)
    return {k: sorted(v) for k, v in out.items()}


def context_function(context):
    """A pytest-cov test context (``nodeid|run``) -> its function node id, or None for the
    empty context (code run at import or collection, outside any test)."""
    if not context:
        return None
    return _function_id(context.rsplit("|", 1)[0])


# --------------------------------------------------------------------------- report

def _json_report(cov, include, contexts):
    with tempfile.TemporaryDirectory() as tmp:
        out = pathlib.Path(tmp) / "cov.json"
        cov.json_report(include=include, outfile=str(out), contexts=contexts)
        return json.loads(out.read_text(encoding="utf-8"))["files"]


def _numbers(summary):
    if summary is None:
        return None
    return {k: summary.get(k, 0) for k in ("num_statements", "covered_lines",
                                          "num_branches", "covered_branches")}


def measure(data_file, modules, tagged):
    """Per module: the suite's coverage, the tagged tests' coverage, and the requirement
    IDs whose tests executed any line in it."""
    import coverage
    cov = coverage.Coverage(data_file=data_file)
    cov.load()
    data = cov.get_data()
    include = [m["path"] for m in modules]
    everything = _json_report(cov, include, None)
    ctx_ids = {}
    for ctx in data.measured_contexts():
        fn = context_function(ctx)
        if fn in tagged:
            ctx_ids[ctx] = tagged[fn]
    # The empty context is import time (see the module docstring).
    pattern = "^(?:" + "|".join([""] + [re.escape(c) for c in sorted(ctx_ids)]) + ")$"
    by_tagged = _json_report(cov, include, [pattern])
    measured = {pathlib.PurePosixPath(f).as_posix(): f for f in data.measured_files()}
    rows = []
    for m in modules:
        path = m["path"]
        all_s = everything.get(path, {}).get("summary")
        tag_s = by_tagged.get(path, {}).get("summary")
        reached = set()
        name = next((f for p, f in measured.items() if p == path or p.endswith("/" + path)), None)
        if name:
            for ctxs in data.contexts_by_lineno(name).values():
                for c in ctxs:
                    reached.update(ctx_ids.get(c, ()))
        if tag_s is None and all_s is not None:
            # No tagged test reached the file: every statement and branch is uncovered.
            tag_s = dict(all_s, covered_lines=0, covered_branches=0)
        rows.append({
            "path": path,
            "rows": list(m.get("rows") or []),
            "why": m.get("why", ""),
            "all_tests": _numbers(all_s),
            "tagged_tests": _numbers(tag_s),
            "requirements_reaching": sorted(reached),
        })
    return rows


def _total(rows, key):
    tot = {"num_statements": 0, "covered_lines": 0, "num_branches": 0, "covered_branches": 0}
    for r in rows:
        for k in tot:
            tot[k] += (r[key] or {}).get(k, 0)
    return tot


def report(args):
    spec = load_paths(args.paths)
    record = json.loads(pathlib.Path(args.record).read_text(encoding="utf-8"))
    tagged = tagged_tests(record)
    rows = measure(args.coverage, spec["modules"], tagged)
    outcomes = {}
    for t in record["tests"]:
        if _function_id(t["nodeid"]) in tagged:
            outcomes[t["outcome"]] = outcomes.get(t["outcome"], 0) + 1
    defined = set(record.get("requirements", {}))
    cited = sorted({i for ids in tagged.values() for i in ids})
    out = {
        "schema": SCHEMA,
        "repo": record.get("repo", ""),
        "name": record.get("name", ""),
        "ref": record.get("ref", ""),
        "sha": record.get("sha", ""),
        "run_url": record.get("run_url", ""),
        "generated_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "paths_file": pathlib.PurePosixPath(args.paths).as_posix(),
        "report_only_until": spec["report_only_until"],
        "tagged_test_functions": len(tagged),
        "tagged_test_outcomes": outcomes,
        "suite_tests": record.get("total", len(record["tests"])),
        "requirements_cited": cited,
        "requirements_cited_not_defined": [i for i in cited if i not in defined],
        "modules": rows,
        "total": {"all_tests": _total(rows, "all_tests"), "tagged_tests": _total(rows, "tagged_tests")},
    }
    dest = pathlib.Path(args.out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=1, sort_keys=True), encoding="utf-8")
    return 0


# --------------------------------------------------------------------------- rendering

def pct(covered, total):
    return "n/a" if not total else f"{100.0 * covered / total:.1f}%"


def cell(n, kind):
    """``"412/1033 (39.9%)"`` for statements (``kind="lines"``) or branches."""
    if n is None:
        return "not measured"
    total = n["num_statements"] if kind == "lines" else n["num_branches"]
    covered = n["covered_lines"] if kind == "lines" else n["covered_branches"]
    return f"{covered}/{total} ({pct(covered, total)})"


def mode_line(rec, today=None):
    today = today or datetime.date.today()
    until = rec.get("report_only_until") or ""
    try:
        ended = bool(until) and today > datetime.date.fromisoformat(until)
    except ValueError:
        ended = False
    if ended:
        return (f"The report-only period ended on {until}. This report still does not gate "
                "anything; whether it gates is the project owner's decision, and it is due.")
    return (f"A report, not a gate, until {until}. Nothing fails on these numbers."
            if until else "A report, not a gate. Nothing fails on these numbers.")


def _md(text):
    return (text or "").replace("|", "\\|").replace("\n", " ")


def summary(args):
    rec = json.loads(pathlib.Path(args.record).read_text(encoding="utf-8"))
    out = [f"## Hazard-path coverage from requirement-tagged tests: {rec['name']}", "",
           mode_line(rec), "",
           f"{rec['tagged_test_functions']} test functions cite a requirement ID "
           f"(of {rec['suite_tests']} tests in the suite). Modules from `{rec['paths_file']}`.", "",
           "| Module | FHA rows | Statements, tagged tests | Branches, tagged tests "
           "| Statements, all tests | Branches, all tests | Requirements reaching it |",
           "|---|---|---|---|---|---|---|"]
    for m in rec["modules"]:
        out.append(f"| `{_md(m['path'])}` | {', '.join(m['rows'])} | {cell(m['tagged_tests'], 'lines')} | "
                   f"{cell(m['tagged_tests'], 'branches')} | {cell(m['all_tests'], 'lines')} | "
                   f"{cell(m['all_tests'], 'branches')} | "
                   f"{', '.join(f'`{i}`' for i in m['requirements_reaching']) or 'none'} |")
    t = rec["total"]
    out.append(f"| **Total** | | {cell(t['tagged_tests'], 'lines')} | {cell(t['tagged_tests'], 'branches')} | "
               f"{cell(t['all_tests'], 'lines')} | {cell(t['all_tests'], 'branches')} | |")
    if rec["requirements_cited_not_defined"]:
        out += ["", "Cited by a test but not found as a definition by the spec parser: "
                + ", ".join(f"`{i}`" for i in rec["requirements_cited_not_defined"]) + "."]
    bad = {k: v for k, v in rec["tagged_test_outcomes"].items() if k not in ("passed",)}
    if bad:
        out += ["", "Tagged tests not passing in this run: "
                + ", ".join(f"{v} {k}" for k, v in sorted(bad.items())) + "."]
    out += ["", "_" + STANDING_TEXT + "_", ""]
    sys.stdout.write("\n".join(out))
    return 0


def _e(text):
    return html.escape(str(text if text is not None else ""), quote=True)


def render_page(rec, today=None):
    gen = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sha = rec.get("sha", "")
    repo = rec.get("repo", "")

    def src_link(path):
        if repo and sha:
            return f'<a href="https://github.com/{_e(repo)}/blob/{_e(sha)}/{_e(path)}"><code>{_e(path)}</code></a>'
        return f"<code>{_e(path)}</code>"

    h = ["<!doctype html><html lang=en><head><meta charset=utf-8>",
         '<meta name=viewport content="width=device-width,initial-scale=1">',
         "<title>Hazard-path coverage from requirement-tagged tests</title>",
         f"<style>{CSS}</style></head><body><main>",
         '<nav><a href="index.html">Test evidence</a><a href="hazard_assessment.html">Hazard assessment</a></nav>',
         f"<h1>{_e(rec['name'])}: hazard-path coverage from requirement-tagged tests</h1>",
         f"<p class=muted>Generated {_e(gen)} from the CI run of "
         f"<code>{_e(rec.get('ref', ''))}</code> at <code>{_e(sha[:10])}</code>"
         + (f' (<a href="{_e(rec["run_url"])}">run</a>)' if rec.get("run_url") else "")
         + ". Nothing here is written by hand.</p>",
         f'<div class=notice id=standing-text><p>{_e(STANDING_TEXT)}</p></div>',
         f"<p><b>{_e(mode_line(rec, today))}</b></p>",
         "<p>The modules below are the primary flight display's data path, listed in "
         f"{src_link(rec['paths_file'])} with the hazard assessment rows each one carries. "
         "Each is measured twice: by the tests that cite a requirement ID, and by the whole "
         "suite. Code the whole suite runs but no requirement-tagged test runs is exercised "
         "without being traced to a requirement.</p>",
         f"<p>{rec['tagged_test_functions']} test functions cite a requirement ID, of "
         f"{rec['suite_tests']} tests in the suite.</p>",
         "<table><tr><th>Module</th><th>Hazard rows</th><th>Statements, tagged tests</th>"
         "<th>Branches, tagged tests</th><th>Statements, all tests</th><th>Branches, all tests</th>"
         "<th>Requirements whose tests reach it</th></tr>"]
    for m in rec["modules"]:
        h.append(f"<tr><td>{src_link(m['path'])}<br><span class=muted>{_e(m['why'])}</span></td>"
                 f"<td>{_e(', '.join(m['rows']))}</td>"
                 f"<td>{_e(cell(m['tagged_tests'], 'lines'))}</td><td>{_e(cell(m['tagged_tests'], 'branches'))}</td>"
                 f"<td>{_e(cell(m['all_tests'], 'lines'))}</td><td>{_e(cell(m['all_tests'], 'branches'))}</td>"
                 f"<td>{_e(', '.join(m['requirements_reaching']) or 'none')}</td></tr>")
    t = rec["total"]
    h.append(f"<tr><th>Total</th><td></td><th>{_e(cell(t['tagged_tests'], 'lines'))}</th>"
             f"<th>{_e(cell(t['tagged_tests'], 'branches'))}</th><th>{_e(cell(t['all_tests'], 'lines'))}</th>"
             f"<th>{_e(cell(t['all_tests'], 'branches'))}</th><td></td></tr></table>")
    if rec["requirements_cited_not_defined"]:
        h.append("<p>Cited by a test but not found as a definition by the spec parser: "
                 + _e(", ".join(rec["requirements_cited_not_defined"])) + ".</p>")
    h.append("</main></body></html>")
    return "\n".join(h)


def page(args):
    rec = json.loads(pathlib.Path(args.record).read_text(encoding="utf-8"))
    for m in rec["modules"]:
        m["why"] = sanitize(m.get("why", ""))
    text = render_page(rec)
    leaks = find_leaks(text)
    if leaks:
        sys.stderr.write(f"refusing to publish {args.out}: it still contains {sorted(set(leaks))[:5]}\n")
        return 2
    dest = pathlib.Path(args.out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report", help="coverage data + test record -> hazard_coverage.json")
    r.add_argument("--paths", required=True, help="docs/safety/hazard_paths.yaml")
    r.add_argument("--coverage", default=".coverage", help="coverage data file with test contexts")
    r.add_argument("--record", required=True, help="verification.json from verification_report.py collect")
    r.add_argument("--out", required=True)
    s = sub.add_parser("summary", help="hazard_coverage.json -> Markdown job summary")
    s.add_argument("record")
    p = sub.add_parser("page", help="hazard_coverage.json -> a page of the test-evidence site")
    p.add_argument("record")
    p.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    return {"report": report, "summary": summary, "page": page}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
