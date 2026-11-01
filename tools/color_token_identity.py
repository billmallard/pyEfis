#!/usr/bin/env python3
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

"""Before/after render diff for the colour-token identity refactor (S1).

Renders every instrument that carries a token-mapped colour prop through
``tools/render_instrument.py`` from two trees -- a BASE checkout (before the
tokens) and this checkout -- and compares the pixels. Each render runs in its
own process so one widget's Qt state cannot leak into the next.

Scenarios (instrument options / preferences):

  stock     no colour options, no theme           -- what ships
  literal   every mapped colour option set to its default literal
  token     every mapped colour option set to its token name   (head only)
  theme     no colour options, a colors: block at the built-in token values
            forcing level 4 on every mutable mapped prop       (head only)

The verdict compares base/stock against head/{stock,token,theme} and
base/literal against head/{literal,token}; every pair must be pixel-identical.
Each instrument renders over a black and a sky screen, in the EXERCISE variants
below. A sensitivity pass then renders each mapped prop alone at a loud literal
and reports whether it changed any pixel: an identity verdict only covers the
props reported "visible". GL widgets and config-driven ones (button) render as
placeholders and are covered by the unit tests, not by pixels.

Writes every render, report.txt and montage.png to --out. Exit 1 on any
difference.

    python tools/color_token_identity.py --base ../pyefis-base --out /tmp/ct
"""

import argparse
import json
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Options and FIX seeds that make each mapped colour actually reach the pixels
# (a bound key so value_text draws a value, a border and an opaque fill, ...).
# The sensitivity pass proves each prop is visible under these; a prop that is
# not is reported, because an identity check over invisible pixels proves
# nothing about it. Variants exist where one render cannot show every prop
# (the HSI's needle colour only shows when no NAVSRC drives the CDI colour).
EXERCISE = {
    "value_text": [({"dbkey": "IAS", "prefix_text": "IAS", "border_width": 3,
                     "bg_opacity": 100}, {})],
    "horizontal_situation_indicator": [
        # Bearing 1 from an unknown source (bearing_color), bearing 2 from GPS.
        ({"bearing1_enabled": True, "bearing2_enabled": True},
         {"BRG1": 120.0, "BRG2": 40.0, "BRG1SRC": 9, "BRG2SRC": 2,
          "CDIV": 1, "GSV": 1}),
        # No source colouring: the CDI/GSI fall back to needle_color.
        ({"source_auto_color": False}, {"CDIV": 1, "GSV": 1}),
    ],
    "atitude_indicator": [({"horizon_heading_marks": True}, {})],
    "checklist": [({"checklists": [{
        "id": "before-takeoff", "title": "Before Takeoff",
        "category": "normal",
        "sections": [{"title": "Runup", "items": [
            {"text": "Throttle", "response": "1700 RPM"},
            {"text": "Magnetos", "response": "CHECK"}]}]}]}, {})],
}

# The screen background each scenario renders over: black and a lit sky, so a
# surface colour that matches black is still seen against something.
SCREENS = ("(0,0,0)", "(150,190,235)")


def _mapped(root):
    """{type: {prop: (default, token)}} for token-mapped colour props, read from
    THIS tree's registry (the base tree has no tokens)."""
    sys.path[:0] = [root, os.path.join(root, "src")]
    import tests.mock_db.client as c
    import tests.mock_db.scheduler as s
    sys.modules["pyavtools.fix.client"] = c
    sys.modules["pyavtools.scheduler"] = s
    from pyefis.screens import screenbuilder_factory as f
    out = {}
    for t, spec in f.REGISTRY.items():
        props = {p.name: (p.default, p.token) for p in spec.properties
                 if p.kind == "color" and getattr(p, "token", "")}
        if props:
            out[t] = props
    return out


def _render_one(args):
    """Child process: render one instrument from --tree."""
    root = args.tree
    sys.path[:0] = [os.path.join(root, "tools"), root, os.path.join(root, "src")]
    import render_instrument as ri
    if args.prefs:
        from tests.screenshots import gui
        prefs = json.loads(args.prefs)
        real = gui.initialize
        gui.initialize = lambda config, path, _p, fullscreen=True: real(
            config, path, prefs, fullscreen=fullscreen)
    kind, _ = ri.render_instrument(
        args.render, options=json.loads(args.options),
        seed=json.loads(args.seed), width=args.width, height=args.height,
        out_path=args.o, screen_color=args.screen_color)
    import pyefis
    # Prove which tree rendered: the base must not import the head's pyefis.
    if not os.path.abspath(pyefis.__file__).startswith(os.path.abspath(root)):
        kind = f"wrong-tree:{pyefis.__file__}"
    print(kind)


def _child(tree, inst, options, prefs, out, size, seed, screen):
    cmd = [sys.executable, os.path.abspath(__file__), "--render", inst,
           "--tree", tree, "--options", json.dumps(options), "-o", out,
           "--width", str(size[0]), "--height", str(size[1]),
           "--seed", json.dumps(seed), "--screen-color", screen]
    if prefs is not None:
        cmd += ["--prefs", json.dumps(prefs)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    lines = r.stdout.strip().splitlines()
    return lines[-1] if lines else f"error: {r.stderr.strip()[-300:]}"


def _same_pixels(a, b):
    from PyQt6.QtGui import QImage
    ia = QImage(a).convertToFormat(QImage.Format.Format_ARGB32)
    ib = QImage(b).convertToFormat(QImage.Format.Format_ARGB32)
    if ia.isNull() or ib.isNull() or ia.size() != ib.size():
        return False, -1
    pa = ia.constBits().asstring(ia.sizeInBytes())
    pb = ib.constBits().asstring(ib.sizeInBytes())
    diff = sum(1 for i in range(0, len(pa), 4) if pa[i:i + 4] != pb[i:i + 4])
    return diff == 0, diff


def _montage(out_dir, mapped, size):
    """One row per pixel-rendered instrument (variant 0, sky screen): base
    stock | head stock | head token | head theme | head with its first visible
    prop set loud -- the last column shows the diff can see a change."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter
    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])  # noqa: F841
    w, h = size[0] // 2, size[1] // 2
    label_h = 18
    cols = ["base/stock", "head/stock", "head/token", "head/theme", "control"]
    rows = []
    for inst, props in sorted(mapped.items()):
        tag = f"{inst}__v0s1"
        base = os.path.join(out_dir, f"{tag}__base_stock.png")
        if QImage(base).pixelColor(1, 1) == QColor("#20242b"):  # placeholder
            continue
        loud = next((n for n in props if not _same_pixels(
            base, os.path.join(out_dir, f"{tag}__head_loud-{n}.png"))[0]), None)
        if loud is None:
            continue
        rows.append((inst, [base] + [os.path.join(out_dir, f"{tag}__head_{s}.png")
                                     for s in ("stock", "token", "theme")]
                     + [os.path.join(out_dir, f"{tag}__head_loud-{loud}.png")],
                     loud))
    img = QImage(w * len(cols), (h + label_h) * len(rows) + label_h,
                 QImage.Format.Format_RGB32)
    img.fill(QColor(32, 32, 32))
    p = QPainter(img)
    p.setPen(QColor(255, 255, 255))
    p.setFont(QFont("DejaVu Sans", 9))
    for c, name in enumerate(cols):
        p.drawText(c * w + 4, 13, name)
    for r, (inst, paths, loud) in enumerate(rows):
        y = label_h + r * (h + label_h)
        p.drawText(4, y + 13, f"{inst}   (control: {loud} = #ff0123)")
        for c, path in enumerate(paths):
            p.drawImage(c * w, y + label_h, QImage(path).scaled(
                w, h, Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.FastTransformation))
    p.end()
    img.save(os.path.join(out_dir, "montage.png"))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", help="checkout of the tree before the tokens")
    ap.add_argument("--out", default="color_token_identity")
    ap.add_argument("--size", default="400x400")
    ap.add_argument("--only", help="comma-separated instrument types")
    # child-process mode
    ap.add_argument("--render")
    ap.add_argument("--tree")
    ap.add_argument("--options", default="{}")
    ap.add_argument("--prefs")
    ap.add_argument("--seed", default="{}")
    ap.add_argument("--screen-color", default="(0,0,0)")
    ap.add_argument("-o")
    ap.add_argument("--width", type=int, default=400)
    ap.add_argument("--height", type=int, default=400)
    args = ap.parse_args(argv)
    if args.render:
        return _render_one(args)

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    size = tuple(int(v) for v in args.size.split("x"))
    mapped = _mapped(_HERE)
    if args.only:
        mapped = {k: v for k, v in mapped.items() if k in args.only.split(",")}
    from pyefis.screens import color_tokens as ct
    theme = {"style": {"basic": True}, "gauges": {}, "styles": {"colors": {
        "basic": {t: v for t, (v, _) in ct.TOKENS.items()
                  if v is not None and not ct.is_immutable(t)}}}}
    os.makedirs(args.out, exist_ok=True)
    pairs = [("stock", "stock"), ("stock", "token"), ("stock", "theme"),
             ("literal", "literal"), ("literal", "token")]

    report = []
    ok = True

    def out(line):
        report.append(line)
        print(line, flush=True)

    loud = "#ff0123"
    for inst, props in sorted(mapped.items()):
        for vi, (exopts, seed) in enumerate(EXERCISE.get(inst, [({}, {})])):
            for si, screen in enumerate(SCREENS):
                tag = f"{inst}__v{vi}s{si}"
                literal = {n: d for n, (d, _) in props.items()}
                token = {n: t for n, (_, t) in props.items()}
                jobs = {("base", "stock"): ({}, None),
                        ("base", "literal"): (literal, None),
                        ("head", "stock"): ({}, None),
                        ("head", "literal"): (literal, None),
                        ("head", "token"): (token, None),
                        ("head", "theme"): ({}, theme)}
                for name in props:
                    jobs[("head", f"loud-{name}")] = ({name: loud}, None)
                paths, kinds = {}, {}
                for (label, scen), (opts, prefs) in jobs.items():
                    tree = args.base if label == "base" else _HERE
                    path = os.path.join(args.out, f"{tag}__{label}_{scen}.png")
                    kinds[(label, scen)] = _child(
                        tree, inst, opts | exopts, prefs, path, size, seed,
                        screen)
                    paths[(label, scen)] = path
                where = f"{inst} variant {vi} screen {screen}"
                for bs, hs in pairs:
                    same, ndiff = _same_pixels(paths[("base", bs)],
                                               paths[("head", hs)])
                    kk = f"{kinds[('base', bs)]}/{kinds[('head', hs)]}"
                    out(f"{where}: base/{bs} vs head/{hs} "
                        f"{'IDENTICAL' if same else f'DIFFERS ({ndiff} px)'}"
                        f"  [{kk}]")
                    ok &= same and "wrong-tree" not in kk
                for name in props:
                    same, ndiff = _same_pixels(paths[("base", "stock")],
                                               paths[("head", f"loud-{name}")])
                    out(f"{where}: sensitivity {name} "
                        f"{'NOT VISIBLE' if same else f'visible ({ndiff} px)'}")
    _montage(args.out, mapped, size)
    with open(os.path.join(args.out, "report.txt"), "w") as fh:
        fh.write("\n".join(report) + "\n")
    print("ALL IDENTICAL" if ok else "DIFFERENCES FOUND")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
