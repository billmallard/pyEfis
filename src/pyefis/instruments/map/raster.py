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
#  interpolated along the edge at yc. All rings from all polygons accumulate
#  into ONE (n, n+1) crossing buffer before the row-wise cumsum/parity step --
#  the even-odd rule then handles island holes and disjoint/nested polygons
#  for free, matching QPainterPath's OddEvenFill semantics with no
#  special-casing and no per-edge Python loop.

import numpy as np


def fill_even_odd(rings, n):
    """Even-odd scanline fill of *rings* into an ``n x n`` boolean mask.

    *rings* is an iterable of ``(k, 2)`` float arrays of (x, y) pixel
    coordinates; each ring is implicitly closed. Rings with fewer than 3
    vertices are skipped. Row *j* of the returned mask corresponds to
    pixel-centre ``y = j + 0.5``; column *i* to pixel-centre ``x = i + 0.5``.
    All rings passed in one call share a single crossing accumulator, so
    island holes (nested rings of one polygon) and disjoint polygons both
    resolve correctly without grouping.
    """
    x0_parts, y0_parts, x1_parts, y1_parts = [], [], [], []
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

    if not x0_parts:
        return np.zeros((n, n), dtype=bool)

    x0 = np.concatenate(x0_parts)
    y0 = np.concatenate(y0_parts)
    x1 = np.concatenate(x1_parts)
    y1 = np.concatenate(y1_parts)

    ymin = np.minimum(y0, y1)
    ymax = np.maximum(y0, y1)
    # Half-open scanline-row range this edge crosses: j in [j_lo, j_hi).
    j_lo = np.clip(np.ceil(ymin - 0.5).astype(np.int64), 0, n)
    j_hi = np.clip(np.ceil(ymax - 0.5).astype(np.int64), 0, n)
    counts = j_hi - j_lo
    keep = counts > 0
    if not keep.any():
        return np.zeros((n, n), dtype=bool)
    x0, y0, x1, y1 = x0[keep], y0[keep], x1[keep], y1[keep]
    j_lo, counts = j_lo[keep], counts[keep]

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

    acc = np.zeros((n, n + 1), dtype=np.int32)
    np.add.at(acc, (j, c), 1)
    return (np.cumsum(acc, axis=1)[:, :n] & 1).astype(bool)
