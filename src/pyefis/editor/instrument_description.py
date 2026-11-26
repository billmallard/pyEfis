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

"""Validator for the draw-only instrument description (INS8).

A description file (``format: makerplane.instrument/1``) is checked without
being run: a JSON Schema pass over ``instrument_description.schema.json`` and
a semantic pass for what a schema cannot say. Every refusal names one rule id
from :data:`RULES`; ``docs/instrument_description_spec.md`` is the prose half
of the contract and ``conformance/instrument_description/`` holds the corpus
both evaluators build to.

This module draws nothing and evaluates nothing (INS9 and INS10 do). It is
Qt-free, apart from B9's shadowing check, which reads the shipped type names
from ``screenbuilder_factory.REGISTRY`` unless they are passed in.

The schema pass is a small walker over the JSON Schema 2020-12 keywords the
schema uses, so the device needs no new dependency. It refuses a schema that
uses any other keyword, so it can never silently ignore a constraint; the
tests cross-check it against the ``jsonschema`` package where that is
installed.

CLI::

    python -m pyefis.editor.instrument_description FILE [FILE ...]
    python -m pyefis.editor.instrument_description --json FILE
    python -m pyefis.editor.instrument_description --shipped-types-from schema.json FILE
"""

import argparse
import colorsys
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

from pyefis.screens import color_tokens

HERE = Path(__file__).resolve().parent
SCHEMA_PATH = HERE / "instrument_description.schema.json"
DISPLAY_LIST_SCHEMA_PATH = HERE / "instrument_display_list.schema.json"

FORMAT = "makerplane.instrument/1"

# The rule ids. A refusal always names exactly one. S1 is the shape check, not
# a safety rule; B1 to B9 are the safety boundary (study section 5).
RULES = {
    "S1": "well-formed: a required field, a type or a value outside its set",
    "B1": "no expressions: every string is a literal, a token, a closed "
          "source name or a declared option",
    "B2": "no command: no action, event, write or knob vocabulary",
    "B3": "no input but declared keys: every input is a fixkey option",
    "B4": "no external resources: no URL, include, image or font file",
    "B5": "bounded cost: element, point, text and grouping limits",
    "B6": "red and amber come only from the key",
    "B7": "quality is not authorable: on_fail only adds static elements",
    "B8": "text is text: a literal string, never markup",
    "B9": "versioned: known format and family, a user. type that shadows "
          "no shipped one",
}

MAX_FILE_BYTES = 64 * 1024
MAX_ELEMENTS = 256
MAX_GROUP_DEPTH = 4

# Field names an author might reach for that belong to a banned vocabulary.
# The schema refuses every unknown field anyway (additionalProperties: false);
# this only decides which rule the refusal names.
CLOSURE_VOCABULARY = {
    "B2": frozenset({
        "action", "actions", "adjust", "binding", "bindings", "click",
        "command", "commands", "emit", "event", "events", "hotspot",
        "hotspots", "key_event", "on_click", "on_press", "on_release",
        "on_touch", "output", "press", "property_assign", "publish", "send",
        "set", "set_key", "swap", "touch", "write", "writes"}),
    "B4": frozenset({
        "bitmap", "file", "font_file", "font_url", "href", "image", "images",
        "import", "imports", "include", "includes", "path", "raster", "src",
        "svg", "uri", "url", "$ref"}),
    "B7": frozenset({
        "bad", "fail", "fail_look", "flags", "hide_fail", "ignore_quality",
        "old", "on_bad", "on_never", "on_old", "on_stale", "on_valid",
        "quality", "show_fail", "stale", "suppress_fail", "valid"}),
}

# Options a described instrument may not declare. The knob options enrol the
# instrument as an input target (B2); the common font options are the screen
# builder's own (S1).
_COMMON_OPTION_NAMES = frozenset({"font_family", "font_percent"})

STATIC_KINDS = ("circle", "rect", "line", "polyline", "polygon", "arc",
                "text")
VALUE_BOUND_KINDS = ("pointer", "fill_bar", "readout")
SCALE_BOUND_KINDS = ("bands", "ticks", "tick_labels") + VALUE_BOUND_KINDS
COLOR_FIELDS = ("fill", "stroke")
BAND = "band"
RED_AMBER_TOKENS = frozenset({"state.warning", "state.caution"})


class RegistryUnavailable(RuntimeError):
    """B9's shadowing check needs the shipped type names and could not load
    them (``screenbuilder_factory`` imports PyQt6)."""


@dataclass(frozen=True)
class Refusal:
    rule: str
    path: str
    message: str

    def __str__(self):
        where = self.path or "(file)"
        return f"{self.rule} {where}: {self.message}"


def _fmt_path(parts):
    out = ""
    for p in parts:
        out += f"[{p}]" if isinstance(p, int) else (f".{p}" if out else p)
    return out


# --------------------------------------------------------------------------
# The schema walker: the JSON Schema 2020-12 keywords the schema uses, and no
# others.
# --------------------------------------------------------------------------

_ANNOTATIONS = frozenset({"$schema", "$id", "$comment", "title",
                          "description", "x-rule"})
_ASSERTIONS = frozenset({
    "$defs", "$ref", "type", "enum", "const", "minLength", "maxLength",
    "pattern", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
    "items", "minItems", "maxItems", "properties", "required",
    "additionalProperties", "propertyNames", "minProperties",
    "maxProperties", "anyOf", "oneOf"})
SUPPORTED_KEYWORDS = _ANNOTATIONS | _ASSERTIONS
_BOUND_KEYWORDS = frozenset({"maxItems", "maxLength", "maxProperties"})


def check_schema_keywords(schema):
    """Raise ValueError naming any keyword the walker does not implement, so
    a constraint added to the schema can never be ignored here."""
    def visit(node, path):
        if isinstance(node, bool):
            return
        if not isinstance(node, dict):
            raise ValueError(f"{path}: a schema must be an object or boolean")
        unknown = sorted(set(node) - SUPPORTED_KEYWORDS)
        if unknown:
            raise ValueError(f"{path}: unsupported keyword(s) {unknown}")
        for key in ("properties", "$defs"):
            for name, sub in (node.get(key) or {}).items():
                visit(sub, f"{path}/{key}/{name}")
        for key in ("items", "additionalProperties", "propertyNames"):
            if key in node:
                visit(node[key], f"{path}/{key}")
        for key in ("anyOf", "oneOf"):
            for i, sub in enumerate(node.get(key) or []):
                visit(sub, f"{path}/{key}/{i}")
    visit(schema, "#")


def _is_type(value, name):
    if name == "object":
        return isinstance(value, dict)
    if name == "array":
        return isinstance(value, list)
    if name == "string":
        return isinstance(value, str)
    if name == "boolean":
        return isinstance(value, bool)
    if name == "null":
        return value is None
    if isinstance(value, bool):
        return False
    if name == "integer":
        return isinstance(value, int) or (
            isinstance(value, float) and value.is_integer())
    if name == "number":
        return isinstance(value, (int, float))
    raise ValueError(f"unknown schema type {name!r}")


def _equal(a, b):
    # JSON equality: True is not 1.
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    return a == b


class _Walker:
    def __init__(self, schema):
        check_schema_keywords(schema)
        self.root = schema

    def _resolve(self, ref):
        if not ref.startswith("#/"):
            raise ValueError(f"only local $ref is supported, got {ref!r}")
        node = self.root
        for part in ref[2:].split("/"):
            node = node[part]
        return node

    def errors(self, instance):
        out = []
        self._walk(self.root, instance, [], out)
        return out

    def _fail(self, out, node, keyword, path, message, key=None):
        out.append(Refusal(_attribute(node, keyword, key), _fmt_path(path),
                           message))

    def _walk(self, node, inst, path, out):
        if node is True:
            return
        if node is False:
            self._fail(out, {}, "false", path, "no value is allowed here")
            return
        if "$ref" in node:
            self._walk(self._resolve(node["$ref"]), inst, path, out)
        if "type" in node:
            types = node["type"] if isinstance(node["type"], list) \
                else [node["type"]]
            if not any(_is_type(inst, t) for t in types):
                self._fail(out, node, "type", path,
                           f"expected {'/'.join(types)}, got {inst!r}")
                return
        if "const" in node and not _equal(inst, node["const"]):
            self._fail(out, node, "const", path,
                       f"must be {node['const']!r}, got {inst!r}")
        if "enum" in node and not any(_equal(inst, e) for e in node["enum"]):
            self._fail(out, node, "enum", path,
                       f"{inst!r} is not one of {node['enum']}")
        if isinstance(inst, str):
            self._string(node, inst, path, out)
        elif _is_type(inst, "number"):
            self._number(node, inst, path, out)
        elif isinstance(inst, list):
            self._array(node, inst, path, out)
        elif isinstance(inst, dict):
            self._object(node, inst, path, out)
        for key in ("anyOf", "oneOf"):
            if key in node:
                self._combinator(node, key, inst, path, out)

    def _string(self, node, inst, path, out):
        if "minLength" in node and len(inst) < node["minLength"]:
            self._fail(out, node, "minLength", path,
                       f"shorter than {node['minLength']} characters")
        if "maxLength" in node and len(inst) > node["maxLength"]:
            self._fail(out, node, "maxLength", path,
                       f"{len(inst)} characters, at most {node['maxLength']}")
        if "pattern" in node and not re.search(node["pattern"], inst):
            self._fail(out, node, "pattern", path,
                       f"{inst!r} does not match {node['pattern']}")

    def _number(self, node, inst, path, out):
        for key, bad, word in (
                ("minimum", lambda v, b: v < b, "below"),
                ("maximum", lambda v, b: v > b, "above"),
                ("exclusiveMinimum", lambda v, b: v <= b, "at or below"),
                ("exclusiveMaximum", lambda v, b: v >= b, "at or above")):
            if key in node and bad(inst, node[key]):
                self._fail(out, node, key, path,
                           f"{inst!r} is {word} {node[key]}")

    def _array(self, node, inst, path, out):
        if "minItems" in node and len(inst) < node["minItems"]:
            self._fail(out, node, "minItems", path,
                       f"{len(inst)} items, at least {node['minItems']}")
        if "maxItems" in node and len(inst) > node["maxItems"]:
            self._fail(out, node, "maxItems", path,
                       f"{len(inst)} items, at most {node['maxItems']}")
        if "items" in node:
            for i, item in enumerate(inst):
                self._walk(node["items"], item, path + [i], out)

    def _object(self, node, inst, path, out):
        for name in node.get("required", ()):
            if name not in inst:
                self._fail(out, node, "required", path,
                           f"missing required field {name!r}")
        n = len(inst)
        if "minProperties" in node and n < node["minProperties"]:
            self._fail(out, node, "minProperties", path,
                       f"{n} fields, at least {node['minProperties']}")
        if "maxProperties" in node and n > node["maxProperties"]:
            self._fail(out, node, "maxProperties", path,
                       f"{n} fields, at most {node['maxProperties']}")
        props = node.get("properties", {})
        for key, value in inst.items():
            if not isinstance(key, str):
                self._fail(out, {}, "keytype", path,
                           f"field name {key!r} is not a string (an unquoted "
                           f"yes/no/on/off reads as a boolean)")
                continue
            if "propertyNames" in node:
                self._walk(node["propertyNames"], key, path + [key], out)
            if key in props:
                self._walk(props[key], value, path + [key], out)
            elif "additionalProperties" in node:
                extra = node["additionalProperties"]
                if extra is False:
                    self._fail(out, node, "additionalProperties", path,
                               f"unknown field {key!r}", key=key)
                else:
                    self._walk(extra, value, path + [key], out)

    def _combinator(self, node, key, inst, path, out):
        branches = node[key]
        results = []
        for branch in branches:
            errs = []
            self._walk(branch, inst, path, errs)
            results.append(errs)
        passing = sum(1 for errs in results if not errs)
        if (key == "anyOf" and passing) or (key == "oneOf" and passing == 1):
            return
        # A branch picked by its `kind` const reports its own errors, so a
        # bad option says what is wrong with it rather than "no branch".
        kinds = [((b.get("properties") or {}).get("kind") or {}).get("const")
                 for b in branches]
        if isinstance(inst, dict) and all(k is not None for k in kinds):
            for errs, kind in zip(results, kinds):
                if _equal(inst.get("kind"), kind):
                    out.extend(errs)
                    return
            self._fail(out, node, key, path + ["kind"],
                       f"kind {inst.get('kind')!r} is not one of {kinds}")
            return
        if key == "oneOf" and passing > 1:
            message = f"{inst!r} matches more than one alternative"
        else:
            message = f"{inst!r} matches none of the allowed alternatives"
        self._fail(out, node, key, path, message)


def _attribute(node, keyword, key=None):
    """The rule a schema error is refused under. Static: it depends only on
    the schema node, the keyword and, for an unknown field, the field's name,
    so every rule's schema-held checks can be listed (and removed) by reading
    the schema."""
    if keyword == "additionalProperties":
        for rule, words in CLOSURE_VOCABULARY.items():
            if key in words:
                return rule
    xr = node.get("x-rule")
    if isinstance(xr, str):
        return xr
    if isinstance(xr, dict) and keyword in xr:
        return xr[keyword]
    if keyword in _BOUND_KEYWORDS:
        return "B5"
    if keyword == "additionalProperties":
        # The closure is what keeps an expression field out (B1).
        return "B1"
    return "S1"


_SCHEMAS = {}


def load_schema(path=SCHEMA_PATH):
    path = Path(path)
    if path not in _SCHEMAS:
        _SCHEMAS[path] = json.loads(path.read_text(encoding="utf-8"))
    return _SCHEMAS[path]


# --------------------------------------------------------------------------
# Parsing: plain YAML (or JSON) only.
# --------------------------------------------------------------------------

def parse(text):
    """Parse a description. Returns ``(document, refusals)``; the document is
    None when the text cannot be read as one plain mapping."""
    raw = text.encode("utf-8") if isinstance(text, str) else text
    refusals = _refuse_size(raw)
    if refusals:
        return None, refusals
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return None, [Refusal("S1", "", f"not UTF-8: {exc}")]
    try:
        events = list(yaml.parse(text, Loader=yaml.SafeLoader))
        refusals = _refuse_aliases(events)
        if refusals:
            return None, refusals
        nodes = list(yaml.compose_all(text, Loader=yaml.SafeLoader))
    except yaml.YAMLError as exc:
        return None, [Refusal("S1", "", f"not readable YAML: {exc}")]
    if len(nodes) != 1:
        return None, [Refusal("S1", "", "a file holds exactly one document")]
    refusals = _refuse_duplicate_keys(nodes[0])
    if refusals:
        return None, refusals
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return None, [Refusal("S1", "", f"not plain YAML: {exc}")]
    if not isinstance(doc, dict):
        return None, [Refusal("S1", "", "the file must be a mapping")]
    return doc, []


def _refuse_size(raw):
    if len(raw) > MAX_FILE_BYTES:
        return [Refusal("B5", "", f"{len(raw)} bytes, at most "
                        f"{MAX_FILE_BYTES}")]
    return []


def _refuse_aliases(events):
    # An alias can multiply a document's size without bound.
    if any(isinstance(e, yaml.AliasEvent) for e in events):
        return [Refusal("B5", "", "YAML aliases are not allowed")]
    return []


def _refuse_duplicate_keys(node):
    return [Refusal("S1", "", f"duplicate field {d!r} (line {line})")
            for d, line in _duplicate_keys(node)]


def _duplicate_keys(node):
    found = []
    stack = [node]
    while stack:
        n = stack.pop()
        if isinstance(n, yaml.MappingNode):
            seen = set()
            for k, v in n.value:
                if isinstance(k, yaml.ScalarNode):
                    if k.value in seen:
                        found.append((k.value, k.start_mark.line + 1))
                    seen.add(k.value)
                stack.extend((k, v))
        elif isinstance(n, yaml.SequenceNode):
            stack.extend(n.value)
    return found


# --------------------------------------------------------------------------
# The semantic pass. Each check reads defensively: it runs even when the
# schema pass has already refused the file, so every refusal is reported.
# --------------------------------------------------------------------------

def _options(doc):
    out = {}
    opts = doc.get("options")
    if isinstance(opts, list):
        for i, o in enumerate(opts):
            if isinstance(o, dict) and isinstance(o.get("name"), str):
                out.setdefault(o["name"], (i, o))
    return out


def _option_kind(doc, name):
    entry = _options(doc).get(name)
    return entry[1].get("kind") if entry else None


def _elements(doc):
    """Yield ``(path, kind, body, layer, group_depth)`` for every well-formed
    element of ``draw`` and ``on_fail``, groups included, children after
    their group."""
    def visit(seq, path, layer, depth):
        if not isinstance(seq, list):
            return
        for i, el in enumerate(seq):
            if not (isinstance(el, dict) and len(el) == 1):
                continue
            kind, body = next(iter(el.items()))
            if not isinstance(body, dict):
                continue
            here = path + [i, kind]
            inner = depth + 1 if kind == "group" else depth
            yield here, kind, body, layer, inner
            if kind == "group":
                yield from visit(body.get("draw"), here + ["draw"], layer,
                                 inner)
    yield from visit(doc.get("draw"), ["draw"], "draw", 0)
    yield from visit(doc.get("on_fail"), ["on_fail"], "on_fail", 0)


def _check_s1(doc, ctx):
    names = [o.get("name") for o in doc.get("options") or []
             if isinstance(o, dict)]
    for name in sorted({n for n in names if names.count(n) > 1},
                       key=str):
        yield Refusal("S1", "options", f"option {name!r} declared twice")
    for name, (i, _o) in _options(doc).items():
        if name in _COMMON_OPTION_NAMES:
            yield Refusal("S1", _fmt_path(["options", i, "name"]),
                          f"{name!r} is the screen builder's common option; "
                          f"a description may not redeclare it")
    scale = doc.get("scale") if isinstance(doc.get("scale"), dict) else {}
    kind = "angle" if "angle" in scale else ("axis" if "axis" in scale
                                             else None)
    rng = scale.get("range") if isinstance(scale.get("range"), dict) else {}
    if rng.get("from") == rng.get("to") and "from" in rng:
        yield Refusal("S1", "scale.range", "from and to are the same")
    if isinstance(scale.get("angle"), dict) \
            and scale["angle"].get("sweep") == 0:
        yield Refusal("S1", "scale.angle.sweep", "a sweep of 0 draws nothing")
    if kind is None:
        return
    for path, el_kind, body, _layer, _depth in _elements(doc):
        where = _fmt_path(path)
        if el_kind in ("bands", "ticks", "tick_labels"):
            want = "r" if kind == "angle" else "offset"
            other = "offset" if kind == "angle" else "r"
            if want not in body or other in body:
                yield Refusal("S1", where, f"on an {kind} scale, place it "
                              f"with {want!r} and not {other!r}")
        elif el_kind == "pointer" and kind == "angle" and "pivot" not in body:
            yield Refusal("S1", where, "a pointer on an angle scale needs "
                          "a pivot")
        elif el_kind == "fill_bar" and kind != "axis":
            yield Refusal("S1", where, "fill_bar needs an axis scale")


def _check_b1(doc, ctx):
    """Every option reference names a declared option of the right kind, and
    every dotted colour name is a token."""
    for path, kind, body, layer, _depth in _elements(doc):
        ref = body.get("visible_if")
        if isinstance(ref, str) and _option_kind(doc, ref) != "boolean":
            yield Refusal("B1", _fmt_path(path + ["visible_if"]),
                          f"{ref!r} is not a declared boolean option")
        for field in COLOR_FIELDS:
            value = body.get(field)
            if not isinstance(value, str) or value.startswith("#") \
                    or value == BAND:
                continue
            if "." in value:
                if value not in color_tokens.TOKENS:
                    yield Refusal("B1", _fmt_path(path + [field]),
                                  f"{value!r} is not a colour token")
            elif _option_kind(doc, value) != "color":
                yield Refusal("B1", _fmt_path(path + [field]),
                              f"{value!r} is not a declared colour option")
    for name, (i, o) in _options(doc).items():
        default = o.get("default")
        if o.get("kind") == "color" and isinstance(default, str) \
                and not default.startswith("#") \
                and default not in color_tokens.TOKENS:
            yield Refusal("B1", _fmt_path(["options", i, "default"]),
                          f"{default!r} is not a colour token")


def _check_b2(doc, ctx):
    for name, (i, _o) in _options(doc).items():
        if name.startswith("encoder_") or name == "touch_edit":
            yield Refusal("B2", _fmt_path(["options", i, "name"]),
                          f"{name!r} makes the instrument a knob or touch "
                          f"target; a description only draws")


def _check_b3(doc, ctx):
    inputs = doc.get("inputs") if isinstance(doc.get("inputs"), dict) else {}
    for name, body in inputs.items():
        opt = body.get("option") if isinstance(body, dict) else None
        if isinstance(opt, str) and _option_kind(doc, opt) != "fixkey":
            yield Refusal("B3", _fmt_path(["inputs", name, "option"]),
                          f"{opt!r} is not a declared fixkey option")
    scale = doc.get("scale") if isinstance(doc.get("scale"), dict) else {}
    used = [(["scale", "input"], scale.get("input"))]
    for path, kind, body, _layer, _depth in _elements(doc):
        if kind in VALUE_BOUND_KINDS and "input" in body:
            used.append((path + ["input"], body["input"]))
    for path, name in used:
        if isinstance(name, str) and name not in inputs:
            yield Refusal("B3", _fmt_path(path),
                          f"{name!r} is not a declared input")


def _check_b5(doc, ctx):
    count = 0
    for path, kind, _body, _layer, depth in _elements(doc):
        count += 1
        if kind == "group" and depth > MAX_GROUP_DEPTH:
            yield Refusal("B5", _fmt_path(path), f"groups nest {depth} deep, "
                          f"at most {MAX_GROUP_DEPTH}")
    if count > MAX_ELEMENTS:
        yield Refusal("B5", "draw", f"{count} elements in all, at most "
                      f"{MAX_ELEMENTS}")


def is_red_or_amber(hex_color):
    """True for a literal colour in the red-to-amber hue window: hue at or
    below 50 degrees or at or above 335, saturation at least 0.5 and value at
    least 0.35. #ffaa00 (state.caution) and #ff0000 are in; #ffff00 (yellow,
    hue 60) and #ff00ff are out."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    hue, sat, val = colorsys.rgb_to_hsv(r, g, b)
    hue *= 360
    return sat >= 0.5 and val >= 0.35 and (hue <= 50 or hue >= 335)


def _red_or_amber_reason(doc, value):
    """Why a colour value reads red or amber, or None."""
    if not isinstance(value, str):
        return None
    if value.startswith("#"):
        return f"{value} is red or amber" if re.fullmatch(
            "#[0-9a-fA-F]{6}", value) and is_red_or_amber(value) else None
    if value in RED_AMBER_TOKENS:
        return f"{value} is red or amber"
    if value in color_tokens.TOKENS:
        return None
    entry = _options(doc).get(value)
    if not entry or entry[1].get("kind") != "color":
        return None
    opt = entry[1]
    for field in ("default", "token"):
        inner = opt.get(field)
        if inner in RED_AMBER_TOKENS:
            return f"option {value!r} {field} {inner} is red or amber"
        if isinstance(inner, str) and inner.startswith("#") and re.fullmatch(
                "#[0-9a-fA-F]{6}", inner) and is_red_or_amber(inner):
            return f"option {value!r} {field} {inner} is red or amber"
    return None


def _check_b6(doc, ctx):
    """Red and amber only where the key's limits, annunciate or quality put
    them: the interpreter's bands, `band` on a value-bound element, and the
    on_fail layer."""
    for path, kind, body, layer, _depth in _elements(doc):
        for field in COLOR_FIELDS:
            value = body.get(field)
            where = _fmt_path(path + [field])
            if value == BAND:
                if kind not in VALUE_BOUND_KINDS:
                    yield Refusal("B6", where, "the band colour is the "
                                  "value's colour; only a pointer, fill_bar "
                                  "or readout may use it")
                continue
            if layer == "on_fail":
                continue
            reason = _red_or_amber_reason(doc, value)
            if reason:
                yield Refusal("B6", where, f"{reason}; outside on_fail, red "
                              f"and amber come only from the key's limits "
                              f"(bands, or fill: band)")


def _check_b9(doc, ctx):
    t = doc.get("type")
    if not (isinstance(t, str) and t.startswith("user.")):
        return
    local = t[len("user."):].lower()
    shipped = {s.lower() for s in ctx.shipped_types()}
    if local in shipped:
        yield Refusal("B9", "type", f"{t!r} shadows the shipped type "
                      f"{local!r}")


# Each rule's semantic checks. A rule with none here is held by the schema
# alone (its keywords carry `x-rule`, or it owns a CLOSURE_VOCABULARY entry).
SEMANTIC_CHECKS = {
    "S1": _check_s1,
    "B1": _check_b1,
    "B2": _check_b2,
    "B3": _check_b3,
    "B5": _check_b5,
    "B6": _check_b6,
    "B9": _check_b9,
}


class _Context:
    def __init__(self, shipped):
        self._shipped = shipped

    def shipped_types(self):
        if self._shipped is None:
            self._shipped = load_shipped_types()
        return self._shipped


def load_shipped_types():
    """The shipped instrument type names, from REGISTRY."""
    try:
        from pyefis.screens.screenbuilder_factory import REGISTRY
    except ImportError as exc:  # PyQt6 absent
        raise RegistryUnavailable(
            f"cannot load screenbuilder_factory.REGISTRY ({exc}); pass the "
            f"shipped type names, or --shipped-types-from schema.json") \
            from exc
    return frozenset(REGISTRY)


def shipped_types_from_schema_json(path):
    """The shipped type names from an exported editor ``schema.json``."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return frozenset(data["instruments"])


def schema_errors(doc, schema=None):
    """The schema pass alone, as refusals."""
    return _Walker(load_schema() if schema is None else schema).errors(doc)


def validate(doc, *, shipped_types=None, rules=None):
    """All refusals for one parsed description, in rule order. An empty list
    means the file is valid. ``rules`` restricts the run to those rule ids;
    the mutation check uses it to remove one rule at a time."""
    active = set(RULES) if rules is None else set(rules)
    found = [r for r in schema_errors(doc) if r.rule in active]
    ctx = _Context(None if shipped_types is None else frozenset(shipped_types))
    for rule, check in SEMANTIC_CHECKS.items():
        if rule in active:
            found.extend(check(doc, ctx))
    order = list(RULES)
    return sorted(dict.fromkeys(found),
                  key=lambda r: (order.index(r.rule), r.path))


def validate_text(text, *, shipped_types=None, rules=None):
    doc, refusals = parse(text)
    active = set(RULES) if rules is None else set(rules)
    refusals = [r for r in refusals if r.rule in active]
    if doc is None:
        return refusals
    return refusals + validate(doc, shipped_types=shipped_types, rules=rules)


def validate_file(path, *, shipped_types=None, rules=None):
    return validate_text(Path(path).read_bytes(), shipped_types=shipped_types,
                         rules=rules)


def validate_display_list(doc):
    """Schema errors for one display list (the evaluator's output)."""
    return [str(e) for e in
            _Walker(load_schema(DISPLAY_LIST_SCHEMA_PATH)).errors(doc)]


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m pyefis.editor.instrument_description",
        description="Check instrument description files without running "
                    "them. Exit 0 when every file is valid, 1 when any is "
                    "refused, 2 when the check itself cannot run.")
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--json", action="store_true",
                        help="print one JSON object per file")
    parser.add_argument("--shipped-types-from", type=Path, metavar="SCHEMA",
                        help="read B9's shipped type names from an exported "
                             "editor schema.json instead of REGISTRY")
    args = parser.parse_args(argv)
    try:
        shipped = (shipped_types_from_schema_json(args.shipped_types_from)
                   if args.shipped_types_from else load_shipped_types())
    except (RegistryUnavailable, OSError, KeyError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    status = 0
    for path in args.files:
        try:
            refusals = validate_file(path, shipped_types=shipped)
        except OSError as exc:
            print(f"error: {path}: {exc}", file=sys.stderr)
            return 2
        if refusals:
            status = 1
        if args.json:
            print(json.dumps({
                "file": str(path), "valid": not refusals,
                "refusals": [{"rule": r.rule, "path": r.path,
                              "message": r.message} for r in refusals]}))
        elif refusals:
            for r in refusals:
                print(f"{path}: REFUSED {r}")
        else:
            print(f"{path}: OK")
    return status


if __name__ == "__main__":
    sys.exit(main())
