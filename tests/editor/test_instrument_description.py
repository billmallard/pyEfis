#  Copyright (c) 2026 Bill Mallard
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.

"""The draw-only instrument description contract (INS8): the schema, the
rules and the conformance corpus, held together. See
docs/instrument_description_spec.md."""

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from pyefis.editor import instrument_description as idesc
from pyefis.screens import color_tokens

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "conformance" / "instrument_description"
MANIFEST = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
CASES = MANIFEST["descriptions"]
VALID = [c for c in CASES if c["expect"] == "valid"]
INVALID = [c for c in CASES if c["expect"] != "valid"]


def _ids(cases):
    return [Path(c["file"]).stem for c in cases]


def _rules(refusals):
    return {r.rule for r in refusals}


def test_manifest_lists_every_corpus_file():
    """INSD-COR-001: no corpus file sits outside the manifest, and the worked
    example is the first case."""
    on_disk = {p.relative_to(CORPUS).as_posix()
               for p in CORPUS.rglob("*") if p.suffix in (".yaml", ".json")
               and p.name != "manifest.json"}
    listed = {c["file"] for c in CASES} | {
        c["file"] for c in MANIFEST["display_lists"]}
    assert on_disk == listed
    assert CASES[0]["file"] == "valid/oil_pressure_dial.yaml"


def test_every_rule_has_an_invalid_case():
    """INSD-COR-002: each rule id is pinned by at least one refused file."""
    assert {c["expect"] for c in INVALID} == set(idesc.RULES)


@pytest.mark.parametrize("case", VALID, ids=_ids(VALID))
def test_valid_case_is_accepted(case):
    """INSD-VAL-001: the validator accepts every valid case, with B9 checked
    against the real registry."""
    assert idesc.validate_file(CORPUS / case["file"]) == []


@pytest.mark.parametrize("case", INVALID, ids=_ids(INVALID))
def test_invalid_case_is_refused_under_its_rule(case):
    """INSD-VAL-002: each invalid case is refused under its named rule, and
    under no other."""
    refusals = idesc.validate_file(CORPUS / case["file"])
    assert refusals, case["why"]
    assert _rules(refusals) == {case["expect"]}, [str(r) for r in refusals]


# --------------------------------------------------------------------------
# The mutation check. Removing a rule removes all of its enforcement: its
# semantic check, every schema keyword attributed to it, its closure
# vocabulary and any parse-time check it owns. Every case pinned to that rule
# must then come out wrong.
# --------------------------------------------------------------------------

_PARSE_CHECKS = {
    "B5": ("_refuse_size", "_refuse_aliases"),
    "S1": ("_refuse_duplicate_keys",),
}


def _strip_rule(schema, rule):
    """A copy of the schema without the keywords attributed to ``rule``."""
    schema = copy.deepcopy(schema)

    def visit(node):
        if not isinstance(node, dict):
            return
        for kw in [k for k in node if k in idesc._ASSERTIONS
                   and k not in ("$defs", "$ref", "properties", "items")]:
            if kw == "additionalProperties" and node[kw] is not False:
                visit(node[kw])
                continue
            if idesc._attribute(node, kw) == rule:
                del node[kw]
                continue
            if kw in ("anyOf", "oneOf"):
                for sub in node[kw]:
                    visit(sub)
            elif kw == "propertyNames":
                visit(node[kw])
        for kw in ("$defs", "properties"):
            for sub in (node.get(kw) or {}).values():
                visit(sub)
        if "items" in node:
            visit(node["items"])

    visit(schema)
    return schema


def _remove_rule(monkeypatch, rule):
    stripped = _strip_rule(idesc.load_schema(), rule)
    monkeypatch.setattr(idesc, "load_schema", lambda path=None: stripped)
    monkeypatch.setattr(idesc, "SEMANTIC_CHECKS", {
        k: v for k, v in idesc.SEMANTIC_CHECKS.items() if k != rule})
    monkeypatch.setattr(idesc, "CLOSURE_VOCABULARY", {
        k: v for k, v in idesc.CLOSURE_VOCABULARY.items() if k != rule})
    for name in _PARSE_CHECKS.get(rule, ()):
        monkeypatch.setattr(idesc, name, lambda *a: [])


@pytest.mark.parametrize("rule", sorted(idesc.RULES))
def test_removing_a_rule_turns_its_cases_red(rule, monkeypatch):
    """INSD-VAL-003: with a rule's enforcement removed, every corpus case
    pinned to it is no longer refused under that rule alone -- the corpus
    test above would go red. A rule held twice (schema and semantic pass)
    must lose both to fail; a case that survives names a check this test
    does not know about."""
    cases = [c for c in INVALID if c["expect"] == rule]
    shipped = idesc.load_shipped_types()
    _remove_rule(monkeypatch, rule)
    survivors = []
    for case in cases:
        refusals = idesc.validate_file(CORPUS / case["file"],
                                       shipped_types=shipped)
        if _rules(refusals) == {rule}:
            survivors.append(case["file"])
    assert cases and not survivors


@pytest.mark.parametrize("rule", sorted(idesc.RULES))
def test_removing_a_rule_keeps_the_valid_cases_valid(rule, monkeypatch):
    """The mutation removes enforcement only: no valid case starts failing,
    so the red above comes from the removed rule and nothing else."""
    _remove_rule(monkeypatch, rule)
    for case in VALID:
        assert idesc.validate_file(CORPUS / case["file"]) == [], case["file"]


# --------------------------------------------------------------------------
# The schema and its walker.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("path", [idesc.SCHEMA_PATH,
                                  idesc.DISPLAY_LIST_SCHEMA_PATH],
                         ids=["description", "display_list"])
def test_schema_uses_only_walker_keywords(path):
    """INSD-SCH-001: every keyword in both schemas is one the walker
    implements, so no constraint is silently skipped on the device."""
    idesc.check_schema_keywords(json.loads(path.read_text(encoding="utf-8")))


def test_walker_refuses_an_unknown_keyword():
    with pytest.raises(ValueError, match="uniqueItems"):
        idesc.check_schema_keywords(
            {"type": "object", "properties": {"a": {"uniqueItems": True}}})


def _corpus_documents():
    for case in CASES:
        doc, _ = idesc.parse((CORPUS / case["file"]).read_bytes())
        if doc is not None:
            yield case["file"], doc


def test_walker_agrees_with_jsonschema():
    """INSD-SCH-002: where the jsonschema package is installed, it reads both
    schemas as valid 2020-12 and gives the walker's verdict on every corpus
    file. (Not installed in CI; a local cross-check.)"""
    jsonschema = pytest.importorskip("jsonschema")
    v = jsonschema.Draft202012Validator
    for path in (idesc.SCHEMA_PATH, idesc.DISPLAY_LIST_SCHEMA_PATH):
        v.check_schema(json.loads(path.read_text(encoding="utf-8")))
    desc = v(idesc.load_schema())
    disagree = [f for f, doc in _corpus_documents()
                if desc.is_valid(doc) == bool(idesc.schema_errors(doc))]
    dl = v(idesc.load_schema(idesc.DISPLAY_LIST_SCHEMA_PATH))
    for case in MANIFEST["display_lists"]:
        doc = json.loads((CORPUS / case["file"]).read_text(encoding="utf-8"))
        if dl.is_valid(doc) == bool(idesc.validate_display_list(doc)):
            disagree.append(case["file"])
    assert disagree == []


def test_colour_tokens_match_the_style_contract():
    """The schema's token list is color_tokens.TOKENS, not a copy that can
    drift."""
    schema = idesc.load_schema()
    options = schema["$defs"]["option"]["oneOf"]
    colour = next(o for o in options
                  if o["properties"]["kind"].get("const") == "color")
    assert colour["properties"]["token"]["enum"] == sorted(color_tokens.TOKENS)


def test_fonts_match_the_common_font_list():
    from pyefis.editor import schema as eschema
    fonts = eschema._COMMON_OPTIONS["font_family"]["enum"]
    assert idesc.load_schema()["$defs"]["font"]["enum"] == fonts
    dl = idesc.load_schema(idesc.DISPLAY_LIST_SCHEMA_PATH)
    assert dl["$defs"]["op_text"]["properties"]["font"]["enum"] == fonts


@pytest.mark.parametrize("case", MANIFEST["display_lists"],
                         ids=_ids(MANIFEST["display_lists"]))
def test_display_list_corpus(case):
    """INSD-DL-001: the display-list schema accepts and refuses its cases."""
    doc = json.loads((CORPUS / case["file"]).read_text(encoding="utf-8"))
    errors = idesc.validate_display_list(doc)
    assert (errors == []) == (case["expect"] == "valid"), errors


# --------------------------------------------------------------------------
# B6's window and the semantic edges.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("hex_color,inside", [
    ("#ff0000", True), ("#ffaa00", True), ("#cc6600", True),
    ("#ff6080", True), ("#a0522d", True),
    ("#ffff00", False), ("#ff00ff", False), ("#00ff00", False),
    ("#ffffff", False), ("#800000", True), ("#400000", False),
    ("#ffc0c0", False),
])
def test_red_amber_window(hex_color, inside):
    """B6's literal window: hue <= 50 or >= 335, saturation >= 0.5, value
    >= 0.35. Pale pink and near-black red are outside; yellow is outside."""
    assert idesc.is_red_or_amber(hex_color) is inside


def test_state_tokens_are_inside_the_window():
    for token in idesc.RED_AMBER_TOKENS:
        assert idesc.is_red_or_amber(color_tokens.default_value(token))
    assert not idesc.is_red_or_amber(color_tokens.default_value("state.valid"))


def test_b9_shadowing_is_case_insensitive():
    text = (CORPUS / "valid" / "minimal.yaml").read_text(encoding="utf-8")
    text = text.replace("type: user.minimal_dial", "type: user.arc_gauge")
    assert _rules(idesc.validate_text(text, shipped_types={"Arc_Gauge"})) \
        == {"B9"}


def test_unquoted_off_is_refused_not_drawn_as_false():
    """YAML reads an unquoted OFF as the boolean false; a text field refuses
    it instead of drawing "False"."""
    text = (CORPUS / "valid" / "minimal.yaml").read_text(encoding="utf-8")
    text += "  - text: {x: 50, y: 80, text: OFF, size: 10}\n"
    refusals = idesc.validate_text(text, shipped_types=())
    assert _rules(refusals) == {"S1"}
    assert "draw[1].text.text" in refusals[0].path


def test_not_utf8_is_refused():
    assert _rules(idesc.validate_text(b"format: \xff\n", shipped_types=())) \
        == {"S1"}


# --------------------------------------------------------------------------
# The CLI: a file is checked without being run.
# --------------------------------------------------------------------------

def _cli(*args):
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    return subprocess.run(
        [sys.executable, "-m", "pyefis.editor.instrument_description", *args],
        capture_output=True, text=True, env=env, cwd=ROOT, timeout=120)


def test_cli_accepts_and_refuses():
    """INSD-CLI-001: exit 0 on valid files, 1 naming the rule on a refused
    one."""
    ok = _cli(str(CORPUS / "valid" / "oil_pressure_dial.yaml"))
    assert ok.returncode == 0, ok.stderr
    assert ok.stdout.strip().endswith(": OK")
    bad = _cli("--json", str(CORPUS / "invalid" / "b6_literal_red_text.yaml"))
    assert bad.returncode == 1, bad.stderr
    record = json.loads(bad.stdout)
    assert record["valid"] is False
    assert [r["rule"] for r in record["refusals"]] == ["B6"]


def test_cli_reads_shipped_types_from_schema_json(tmp_path):
    schema_json = tmp_path / "schema.json"
    schema_json.write_text(json.dumps({"instruments": {"arc_gauge": {}}}))
    res = _cli("--shipped-types-from", str(schema_json),
               str(CORPUS / "invalid" / "b9_shadows_shipped.yaml"))
    assert res.returncode == 1
    assert "REFUSED B9" in res.stdout


def test_cli_cannot_run_without_shipped_types(tmp_path):
    res = _cli("--shipped-types-from", str(tmp_path / "missing.json"),
               str(CORPUS / "valid" / "minimal.yaml"))
    assert res.returncode == 2
