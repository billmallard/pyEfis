#!/usr/bin/env python3
"""Build a terrain mip pyramid (docs/terrain_mip_pyramid.md).

For every native HGT tile under a tile tree, write anti-aliased downsampled
copies at levels 1..N into the parallel ``.mip/<L>/<NSdir>/<name>.hgt`` tree the
moving-map / SVS ``TileCache.get_mip()`` reads. Dense 2x-per-level pyramid
(level k -> factor ``2**k``, ~``30*2**k`` m pitch), matching ``terrain.py``'s mip
selection. Output is the same big-endian int16 HGT the loader already reads (the
side is inferred from file size), so no new format. Run on a workstation that
holds the tiles -- never the EFIS device.

Downsample: a **node-centred box average** -- each coarse grid node is the mean
of a ~factor-wide box of native samples centred on it. So the coarse corners stay
registered to the native corners (tiles keep abutting), and the result is
anti-aliased (no strided-subsample moire). Voids (``SRTM3_VOID``) are excluded
from each average; GLO-30 has none, so this is a safety net for SRTM3.

Usage::

    python tools/build_terrain_mips.py <tile_root> [--levels 6] [--force]
                                        [--only N35W098 N36W099 ...]
"""
import argparse
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from pyefis.instruments.ai.svs import SRTM3_VOID     # noqa: E402

MAX_LEVEL = 6           # matches the terrain.py mip clamp (min(6, ...))


def downsample(native: np.ndarray, factor: int) -> np.ndarray:
    """Anti-aliased node-centred box downsample of a square ``(n, n)`` int16
    tile by ``factor``. Returns an ``(m, m)`` big-endian int16 array with
    ``m = round((n-1)/factor) + 1``, corners registered to the native corners.
    Voids (== ``SRTM3_VOID``) are excluded per box; an all-void box stays void."""
    n = native.shape[0]
    m = int(round((n - 1) / factor)) + 1
    data = native.astype(np.float64)
    valid = (native != SRTM3_VOID).astype(np.float64)
    dv = data * valid
    # coarse node positions, corner-exact (first = 0, last = n-1)
    idx = np.rint(np.linspace(0, n - 1, m)).astype(np.int64)
    half = max(1, factor // 2)
    lo = np.clip(idx - half, 0, n)
    hi = np.clip(idx + half + 1, 0, n)      # exclusive

    def boxsum(a):
        """Node-centred box sums along axis 0: (K, X) -> (m, X)."""
        cs = np.zeros((a.shape[0] + 1, a.shape[1]), np.float64)
        np.cumsum(a, axis=0, out=cs[1:])
        return cs[hi] - cs[lo]

    # separable: box the rows, then box the columns (via transpose)
    ds = boxsum(boxsum(dv).T)               # (m_col, m_row)
    ws = boxsum(boxsum(valid).T)            # (m_col, m_row)
    with np.errstate(invalid="ignore", divide="ignore"):
        coarse = (ds / ws).T                # (m_row, m_col)
    coarse = np.where(ws.T > 0, coarse, float(SRTM3_VOID))
    return np.ascontiguousarray(np.rint(coarse)).astype(">i2")


def _iter_native(root: Path, only):
    for p in sorted(root.glob("[NS]*/*.hgt")):
        stem = p.stem.upper()
        if only and stem not in only:
            continue
        yield stem, p


def build_tile(root: Path, stem: str, path: Path, levels: int, force: bool) -> int:
    raw = np.fromfile(path, dtype=">i2")
    n = int(round(raw.size ** 0.5))
    if n * n != raw.size:
        print(f"  skip {stem}: not square ({raw.size} samples)")
        return 0
    native = raw.reshape(n, n)
    ns = path.parent.name                    # <NSdir>
    written = 0
    for level in range(1, levels + 1):
        out = root / ".mip" / str(level) / ns / f"{stem}.hgt"
        if out.exists() and not force:
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        downsample(native, 1 << level).tofile(out)
        written += 1
    return written


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build a terrain mip pyramid.")
    ap.add_argument("tile_root", help="terrain tile tree (holds <NSdir>/*.hgt)")
    ap.add_argument("--levels", type=int, default=MAX_LEVEL,
                    help=f"deepest level to build (default {MAX_LEVEL})")
    ap.add_argument("--force", action="store_true",
                    help="rebuild levels that already exist")
    ap.add_argument("--only", nargs="*", default=None,
                    help="only these tiles (e.g. N35W098)")
    args = ap.parse_args(argv)

    root = Path(args.tile_root)
    only = {s.upper() for s in args.only} if args.only else None
    tiles = list(_iter_native(root, only))
    print(f"root={root}  native tiles: {len(tiles)}  levels 1..{args.levels}")
    import time
    t0 = time.perf_counter()
    files = 0
    for i, (stem, path) in enumerate(tiles):
        files += build_tile(root, stem, path, args.levels, args.force)
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{len(tiles)} tiles...")
    footprint = 0
    mip_root = root / ".mip"
    if mip_root.exists():
        footprint = sum(f.stat().st_size for f in mip_root.rglob("*.hgt"))
    print(f"done: {len(tiles)} tiles -> {files} mip files written, "
          f"pyramid {footprint / 1e9:.2f} GB, {time.perf_counter() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
