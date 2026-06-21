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

"""Build the configuration manager's static editor-asset bundle:

    <out>/schema.json            the enriched instrument schema (palette + props)
    <out>/palette/<type>.png     one thumbnail per instrument type

Upload the result to R2 under assets/editor/ (served by the configurator Worker
at /assets/editor/...). This is the pyEfis-side "CI -> R2 bridge": nothing Qt
runs at the edge; the browser editor consumes these static files.

Usage (from the repo root)::

    python tools/build_editor_assets.py --out work/editor_assets
"""

import argparse
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_REPO_ROOT, os.path.join(_REPO_ROOT, "src"),
           os.path.join(_REPO_ROOT, "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from pyefis.editor import schema as eschema  # noqa: E402
import render_instrument as ri  # noqa: E402


def build(out_dir, width, height):
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "schema.json"), "w", encoding="utf-8") as fh:
        fh.write(eschema.to_json() + "\n")

    palette_dir = os.path.join(out_dir, "palette")
    os.makedirs(palette_dir, exist_ok=True)

    types = sorted(eschema.build_schema()["instruments"])
    for instrument_type in types:
        kind, _path = ri.safe_render(
            instrument_type, width=width, height=height,
            out_path=os.path.join(palette_dir, f"{instrument_type}.png"))
        print(f"  {instrument_type:<34} {kind}")
    return len(types)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Build the editor schema + palette thumbnail bundle.")
    parser.add_argument(
        "--out", default=os.path.join(_REPO_ROOT, "work", "editor_assets"),
        help="output directory (default work/editor_assets)")
    parser.add_argument("--width", type=int, default=220)
    parser.add_argument("--height", type=int, default=150)
    args = parser.parse_args(argv)

    print(f"Building editor assets into {args.out} ...")
    count = build(args.out, args.width, args.height)
    print(f"\nWrote schema.json + {count} palette thumbnails. Upload to R2 "
          f"under assets/editor/.")


if __name__ == "__main__":
    main()
