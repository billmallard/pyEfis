#!/usr/bin/env python3
#  SPDX-License-Identifier: GPL-2.0-or-later
"""Static import check for the primary-flight core (rule R1), gated as a ratchet.

``docs/safety/core_modules.yaml`` names the core by path prefix. Every core module may
import only core modules, the standard library, and the third-party packages that file
lists. This walks the syntax tree of every core module -- imports at module level and
imports inside functions alike -- and reports each import that leaves that set.

It is a ratchet. The crossings that exist today are listed in the same file under
``ratchet: imports``, each with the edge id from the core brief and the backlog row that
removes it. The check fails on a crossing that is not listed, and on a listed crossing
that no longer occurs, so the allowlist can only shrink.

What it cannot see: an import made by name at run time (``importlib.import_module``
with a computed string, the brief's E5). The runtime check, tests/safety/test_core_boot.py,
covers those by booting a core-only screen and reading ``sys.modules``.

Standard library only, apart from PyYAML to read the list (a core dependency already).

Usage:
    python tools/core_imports.py check     # exit 1 on a new or stale crossing
    python tools/core_imports.py list      # every crossing found, allowlisted or not
"""

import argparse
import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CORE_LIST = ROOT / "docs" / "safety" / "core_modules.yaml"
SRC = "src"
PACKAGE = "pyefis"


# --------------------------------------------------------------------------- the list

def load_core_list(path=CORE_LIST):
    import yaml
    return yaml.safe_load(pathlib.Path(path).read_text(encoding="utf-8"))


def core_paths(doc):
    """{path prefix: group} for every entry of every group."""
    out = {}
    for group, body in (doc.get("groups") or {}).items():
        for p in body.get("paths") or []:
            out[p] = group
    return out


def core_group(relpath, doc):
    """The group a repository-relative path belongs to, or None when it is not core."""
    relpath = pathlib.PurePosixPath(relpath).as_posix()
    for prefix, group in core_paths(doc).items():
        if prefix.endswith("/") and relpath.startswith(prefix):
            return group
        if relpath == prefix:
            return group
    return None


# --------------------------------------------------------------------------- resolving

def module_file(name, root=ROOT):
    """Repository-relative path of a ``pyefis`` module, or None when no file exists."""
    parts = name.split(".")
    base = pathlib.Path(root, SRC, *parts)
    for cand in (base.with_suffix(".py"), base / "__init__.py"):
        if cand.is_file():
            return cand.relative_to(root).as_posix()
    return None


def module_name(relpath):
    """Dotted name of a repository-relative module path under src/."""
    p = pathlib.PurePosixPath(relpath).relative_to(SRC)
    parts = list(p.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _package_of(relpath):
    name = module_name(relpath)
    return name if relpath.endswith("__init__.py") else name.rpartition(".")[0]


def imports_of(relpath, root=ROOT):
    """(line, imported module name, inside a function) for every import in a file.

    ``from X import y`` yields ``X.y`` when that is a module of this package, else ``X``.
    Relative imports are resolved against the file's package.
    """
    tree = ast.parse(pathlib.Path(root, relpath).read_text(encoding="utf-8"), relpath)
    out = []

    def visit(node, in_func):
        for child in ast.iter_child_nodes(node):
            inner = in_func or isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
            if isinstance(child, ast.Import):
                for alias in child.names:
                    out.append((child.lineno, alias.name, in_func))
            elif isinstance(child, ast.ImportFrom):
                if child.level:
                    pkg = _package_of(relpath).split(".")
                    pkg = pkg[:len(pkg) - (child.level - 1)]
                    base = ".".join(pkg + ([child.module] if child.module else []))
                else:
                    base = child.module
                for alias in child.names:
                    sub = "%s.%s" % (base, alias.name)
                    if base.split(".")[0] == PACKAGE and module_file(sub, root):
                        out.append((child.lineno, sub, in_func))
                    else:
                        out.append((child.lineno, base, in_func))
            visit(child, inner)

    visit(tree, False)
    return out


def core_files(doc, root=ROOT):
    files = sorted(p.relative_to(root).as_posix()
                   for p in pathlib.Path(root, SRC, PACKAGE).rglob("*.py"))
    return [f for f in files if core_group(f, doc)]


# --------------------------------------------------------------------------- the rule

def crossings(doc, root=ROOT):
    """Every import from a core module that rule R1 forbids.

    A list of dicts: from (path), line, imports (module name), kind ("non-core pyefis",
    "third-party" or "unresolved pyefis"), in_function.
    """
    allowed_third = set(doc.get("third_party") or [])
    stdlib = set(sys.stdlib_module_names)
    found = []
    for f in core_files(doc, root):
        for line, name, in_func in imports_of(f, root):
            top = name.split(".")[0]
            if top == PACKAGE:
                target = module_file(name, root)
                if target is None:
                    kind = "unresolved pyefis"
                elif core_group(target, doc):
                    continue
                else:
                    kind = "non-core pyefis"
            elif top in stdlib or top in allowed_third:
                continue
            else:
                kind = "third-party"
            found.append({"from": f, "line": line, "imports": name, "kind": kind,
                          "in_function": in_func})
    return found


def allowlist(doc):
    """{(from path, module name): entry} from ratchet: imports."""
    out = {}
    for entry in ((doc.get("ratchet") or {}).get("imports") or []):
        for name in entry.get("imports") or []:
            out[(entry["from"], name)] = entry
    return out


def check(doc, root=ROOT):
    """(new crossings, stale allowlist keys). Both empty means the ratchet holds."""
    found = crossings(doc, root)
    allowed = allowlist(doc)
    seen = {(c["from"], c["imports"]) for c in found}
    new = [c for c in found if (c["from"], c["imports"]) not in allowed]
    stale = sorted(k for k in allowed if k not in seen)
    return new, stale


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=["check", "list"])
    ap.add_argument("--core-list", default=str(CORE_LIST))
    ap.add_argument("--root", default=str(ROOT))
    args = ap.parse_args(argv)
    root = pathlib.Path(args.root)
    doc = load_core_list(args.core_list)

    if args.command == "list":
        allowed = allowlist(doc)
        for c in crossings(doc, root):
            entry = allowed.get((c["from"], c["imports"]))
            tag = "%s, removed by %s" % (entry["edge"], entry["removed_by"]) if entry else "NOT ALLOWLISTED"
            print("%s:%d imports %s (%s%s) [%s]" % (
                c["from"], c["line"], c["imports"], c["kind"],
                ", inside a function" if c["in_function"] else "", tag))
        return 0

    new, stale = check(doc, root)
    for c in new:
        print("%s:%d: core module imports %s (%s%s), which rule R1 forbids. Route it through "
              "a FIX key or the registration seam, or, if the core list is wrong, change "
              "docs/safety/core_modules.yaml for Safety and Compliance to review."
              % (c["from"], c["line"], c["imports"], c["kind"],
                 ", inside a function" if c["in_function"] else ""))
    for frm, name in stale:
        print("%s: allowlisted import of %s no longer occurs. Delete it from ratchet: imports "
              "in docs/safety/core_modules.yaml; the allowlist only shrinks." % (frm, name))
    if new or stale:
        return 1
    print("core imports: %d core modules, every crossing allowlisted (%d)."
          % (len(core_files(doc, root)), len(allowlist(doc))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
