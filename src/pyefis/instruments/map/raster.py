#  SPDX-License-Identifier: GPL-2.0-or-later
#  Vectorised even-odd scanline polygon fill (MP5, briefs/map_gesture_perf_plan.md
#  section 4; pyEfis #98). Replaces the QPointF/QPolygonF/QPainterPath path for
#  water rasterization: pure numpy, no Qt import, so it is testable without a
#  QApplication.
#
#  Algorithm (brief section 4 MP5): for every ring edge (x0,y0)-(x1,y1) (rings
#  are implicitly closed -- an edge runs from the last vertex back to the
#  first), a scanline row j (pixel centre yc = j + 0.5) is crossed when
#  min(y0,y1) <= yc < max(y0,y1) -- the half-open test means a vertex lying
#  exactly on a scanline is never double-counted between its two adjacent
#  edges. The crossing column is c = clip(ceil(x - 0.5), 0, n), x
#  interpolated along the edge at yc. All rings of one call accumulate into
#  ONE (n, n+1) crossing buffer before the row-wise cumsum/parity step --
#  the even-odd rule then handles a polygon's island holes for free,
#  matching QPainterPath's OddEvenFill semantics with no special-casing and
#  no per-edge Python loop. Separate polygons go through fill_union, which
#  unions them instead of letting an overlap cancel (AER-4596).

import numpy as np


def fill_even_odd(rings, n):
    """Even-odd scanline fill of *rings* into an ``n x n`` boolean mask.

    *rings* is an iterable of ``(k, 2)`` float arrays of (x, y) pixel
    coordinates; each ring is implicitly closed. Rings with fewer than 3
    vertices are skipped. Row *j* of the returned mask corresponds to
    pixel-centre ``y = j + 0.5``; column *i* to pixel-centre ``x = i + 0.5``.
    All rings passed in one call share a single crossing accumulator, so
    the rings of ONE polygon resolve island holes without grouping. Rings
    of two polygons that overlap cancel wherever both cover a pixel -- use
    :func:`fill_union` for a set of separate polygons (AER-4596).
    """
    j, c, _ = _crossings([rings], n)
    if j is None:
        return np.zeros((n, n), dtype=bool)
    # AER-681: bincount over the flattened (row, col) index is the buffered
    # scatter-add idiom, vs. np.add.at's unbuffered (GIL-held) ufunc path.
    # Correctness-neutral swap; see the PR for why it did not move the
    # measured 160 NM regression (add.at was not the dominant cost there).
    flat = j * (n + 1) + c
    acc = np.bincount(flat, minlength=n * (n + 1)).reshape(n, n + 1)
    return (np.cumsum(acc, axis=1)[:, :n] & 1).astype(bool)


def fill_union(polygons, n):
    """Coverage of *polygons* in an ``n x n`` boolean mask: even-odd
    WITHIN each polygon (its hole rings cut holes, #44), then the polygons
    are UNIONED (AER-4596). *polygons* is an iterable of polygons, each a
    list of ``(k, 2)`` (x, y) rings in :func:`fill_even_odd`'s convention.

    One shared parity across polygons is wrong for real water data: OSM's
    split ocean cells overlap their neighbours by ~0.0005 deg past every
    whole degree, and Natural Earth lakes duplicate their OSM twins (Great
    Salt Lake, Mille Lacs), so a pixel covered twice cancels to land. Same
    rule as ``tools/build_water_masks._mask_at_nodes_cell`` (AER-4594),
    which bakes the terrain pack's water masks.

    Still one accumulator and no per-polygon Python loop over the image:
    each crossing is tagged with its polygon, the crossings are sorted by
    (polygon, row, column), and within one polygon's row they alternate
    +1 (entering) / -1 (leaving). The row-wise cumsum of those deltas is
    then the NUMBER of polygons covering each pixel -- each polygon adds 1
    exactly where its own even-odd count is odd -- and the union is
    ``count > 0``. A crossing clipped onto column 0 or n keeps its place
    in the alternation, so off-image edges stay exact."""
    j, c, pid = _crossings(polygons, n)
    if j is None:
        return np.zeros((n, n), dtype=bool)
    row_key = pid * n + j
    key = np.sort(row_key * (n + 1) + c)
    row_key = key // (n + 1)
    flat = (row_key % n) * (n + 1) + key % (n + 1)
    starts = np.flatnonzero(np.r_[True, row_key[1:] != row_key[:-1]])
    lengths = np.diff(np.r_[starts, key.shape[0]])
    rank = np.arange(key.shape[0]) - np.repeat(starts, lengths)
    entering = (rank & 1) == 0
    size = n * (n + 1)
    acc = (np.bincount(flat[entering], minlength=size)
           - np.bincount(flat[~entering], minlength=size)).reshape(n, n + 1)
    return np.cumsum(acc, axis=1)[:, :n] > 0


def _crossings(polygons, n):
    """Every scanline crossing of every ring of *polygons* inside the
    ``n``-row image: ``(row, col, polygon index)`` int64 arrays, or
    ``(None, None, None)`` when there are none. Row *j* is crossed at
    pixel-centre ``yc = j + 0.5`` when ``min(y0, y1) <= yc < max(y0, y1)``;
    the crossing column is ``clip(ceil(x - 0.5), 0, n)``."""
    x0_parts, y0_parts, x1_parts, y1_parts, pid_parts = [], [], [], [], []
    for k, rings in enumerate(polygons):
        for ring in rings:
            ring = np.asarray(ring, dtype=np.float64)
            if ring.shape[0] < 3:
                continue
            x = ring[:, 0]
            y = ring[:, 1]
            x0_parts.append(x)
            y0_parts.append(y)
            x1_parts.append(np.roll(x, -1))
            y1_parts.append(np.roll(y, -1))
            pid_parts.append(np.full(x.shape[0], k, dtype=np.int64))

    if not x0_parts:
        return None, None, None

    x0 = np.concatenate(x0_parts)
    y0 = np.concatenate(y0_parts)
    x1 = np.concatenate(x1_parts)
    y1 = np.concatenate(y1_parts)
    pid = np.concatenate(pid_parts)

    ymin = np.minimum(y0, y1)
    ymax = np.maximum(y0, y1)
    # Half-open scanline-row range this edge crosses: j in [j_lo, j_hi).
    j_lo = np.clip(np.ceil(ymin - 0.5).astype(np.int64), 0, n)
    j_hi = np.clip(np.ceil(ymax - 0.5).astype(np.int64), 0, n)
    counts = j_hi - j_lo
    keep = counts > 0
    if not keep.any():
        return None, None, None
    x0, y0, x1, y1 = x0[keep], y0[keep], x1[keep], y1[keep]
    j_lo, counts, pid = j_lo[keep], counts[keep], pid[keep]

    # Expand each surviving edge into one row per scanline it crosses --
    # np.repeat + an arange/cumsum offset trick, no per-edge Python loop.
    total = int(counts.sum())
    edge_id = np.repeat(np.arange(x0.shape[0]), counts)
    run_start = np.repeat(np.cumsum(counts) - counts, counts)
    j = j_lo[edge_id] + (np.arange(total) - run_start)
    yc = j.astype(np.float64) + 0.5

    dy = (y1 - y0)[edge_id]
    dx = (x1 - x0)[edge_id]
    x_at = x0[edge_id] + (yc - y0[edge_id]) * dx / dy
    c = np.clip(np.ceil(x_at - 0.5).astype(np.int64), 0, n)
    return j, c, pid[edge_id]
