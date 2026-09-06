"""
Pure-numpy road ribbon extrusion for the SVS highways overlay (RD1,
issue #161, brief ``svs_roads_visual_plan.md`` section 3.1).

Turns decimated OSM polylines into true-scale casing/fill triangle
lists instead of 1 px ``GL_LINES`` hairlines: subdivide long segments
so the ribbon follows terrain, extrude each vertex to a mitred
left/right pair in a local ENU (east/north metres) frame centred on
the aircraft, and floor the half-width in screen space so distant
ribbons never drop below ``min_px``.

Every function here operates on the WHOLE concatenated vertex array at
once (segment-boundary masks distinguish one polyline from the next) —
no per-vertex Python loop, per the #74 GIL discipline. The only
Python-level loops left are O(polyline count), not O(vertex count),
and only run in the (rare) vertex-budget trim path.

No GL, no SVSRenderer dependency — importable and testable standalone.
"""

from __future__ import annotations

import numpy as np

# Metres per degree of latitude — matches camera.M_PER_DEG_LAT, the
# constant the rest of the SVS ENU pipeline (svs_gl.py's _to_enu) uses,
# so ribbon geometry lines up with the terrain/water/runway meshes.
M_PER_DEG_LAT = 111139.0

# Class widths in metres, per OSM way (== per carriageway — dual
# carriageways are two separate one-way ways in OSM, so this is correct
# per-way, not per-freeway). Brief section 3.1.
DEFAULT_WIDTH_M = {
    "motorway": 16.0,
    "trunk": 13.0,
    "primary": 11.0,
    "secondary": 8.0,
    "motorway_link": 7.0,
    "trunk_link": 7.0,
    "primary_link": 6.0,
    "secondary_link": 6.0,
}
DEFAULT_UNKNOWN_WIDTH_M = 7.0

DEFAULT_CASING_M = 2.5
DEFAULT_MIN_PX = 1.5
DEFAULT_SUBDIVIDE_M = 150.0
DEFAULT_SUBDIVIDE_NM = 4.0
DEFAULT_LIFT_FT = 2.0
DEFAULT_MAX_VERTICES = 400_000

_EPS = 1e-9


def hex_to_rgba01(hex_str: str, default=(1.0, 1.0, 1.0, 1.0)):
    """``"#rrggbb"`` (or ``"rrggbb"``) -> an ``(r, g, b, a)`` float tuple
    in [0, 1], alpha fixed at 1.0. Malformed input falls back to
    *default* rather than raising (construct-never-raises)."""
    s = str(hex_str).strip().lstrip("#")
    if len(s) != 6:
        return default
    try:
        r = int(s[0:2], 16) / 255.0
        g = int(s[2:4], 16) / 255.0
        b = int(s[4:6], 16) / 255.0
    except ValueError:
        return default
    return (r, g, b, 1.0)


def width_for_class(fclass: str, width_m: dict | None = None) -> float:
    table = width_m if width_m is not None else DEFAULT_WIDTH_M
    return float(table.get(fclass, DEFAULT_UNKNOWN_WIDTH_M))


def _polyline_offsets(lengths: np.ndarray) -> np.ndarray:
    offsets = np.zeros(lengths.shape[0] + 1, dtype=np.int64)
    np.cumsum(lengths, out=offsets[1:])
    return offsets


def _enu(pts: np.ndarray, ac_lat: float, ac_lon: float, lat_cos: float):
    """(lat, lon) -> (east_m, north_m) relative to the aircraft."""
    e = (pts[:, 1] - ac_lon) * M_PER_DEG_LAT * lat_cos
    n = (pts[:, 0] - ac_lat) * M_PER_DEG_LAT
    return np.stack([e, n], axis=1)


def _enu_to_latlon(enu: np.ndarray, ac_lat: float, ac_lon: float,
                    lat_cos: float):
    lon = ac_lon + enu[:, 0] / (M_PER_DEG_LAT * lat_cos)
    lat = ac_lat + enu[:, 1] / M_PER_DEG_LAT
    return lat, lon


def subdivide_polylines(lines, ac_lat: float, ac_lon: float,
                        subdivide_m: float = DEFAULT_SUBDIVIDE_M,
                        subdivide_nm: float = DEFAULT_SUBDIVIDE_NM):
    """Subdivide segments longer than *subdivide_m* whose midpoint is
    within *subdivide_nm* of the aircraft, so the ribbon follows
    rolling terrain instead of floating/sinking on a long chord.
    Segments beyond *subdivide_nm* (or already short) pass through
    unchanged.

    *lines* is a list of ``(k_i, 2)`` float64 ``(lat, lon)`` arrays,
    each ``k_i >= 2``.

    Returns ``(new_pts, new_offsets)``: a single concatenated
    ``(N, 2)`` array and an ``(len(lines) + 1,)`` int64 offsets array
    (``new_pts[new_offsets[p]:new_offsets[p + 1]]`` is polyline *p*'s
    — now denser — vertex sequence). The polyline count and order are
    unchanged, so a caller's parallel per-polyline metadata (fclass,
    …) still lines up against the offsets.

    Vectorised over the whole concatenated array in one pass — no
    per-polyline Python loop for the actual subdivision math (only the
    O(len(lines)) bookkeeping to concatenate the input, which is
    inherent to gathering a list of arrays)."""
    lengths = np.array([v.shape[0] for v in lines], dtype=np.int64)
    offsets = _polyline_offsets(lengths)
    pts = np.concatenate(lines, axis=0).astype(np.float64)
    n = pts.shape[0]

    is_last_vertex = np.zeros(n, dtype=bool)
    is_last_vertex[offsets[1:] - 1] = True

    lat_cos = float(np.cos(np.radians(ac_lat)))
    enu = _enu(pts, ac_lat, ac_lon, lat_cos)

    # One segment per vertex that isn't the last vertex of its polyline.
    seg_start = np.nonzero(~is_last_vertex)[0]
    seg_end = seg_start + 1
    n_seg = seg_start.shape[0]
    if n_seg == 0:
        return pts, offsets

    seg_poly_id = np.repeat(np.arange(lengths.shape[0]),
                            np.maximum(lengths - 1, 0))
    is_last_seg = is_last_vertex[seg_end]

    d = enu[seg_end] - enu[seg_start]
    seg_len_m = np.hypot(d[:, 0], d[:, 1])
    mid_e = (enu[seg_start, 0] + enu[seg_end, 0]) * 0.5
    mid_n = (enu[seg_start, 1] + enu[seg_end, 1]) * 0.5
    mid_dist_nm = np.hypot(mid_e, mid_n) / 1852.0
    near = mid_dist_nm <= subdivide_nm

    count = np.where(
        near,
        np.maximum(1, np.ceil(seg_len_m / max(subdivide_m, _EPS))),
        1.0,
    ).astype(np.int64)
    count_out = count + is_last_seg.astype(np.int64)

    total_pts = int(count_out.sum())
    rep_seg = np.repeat(np.arange(n_seg), count_out)
    cum = np.cumsum(count_out)
    run_start = cum - count_out
    local_i = np.arange(total_pts) - np.repeat(run_start, count_out)
    t = local_i / np.repeat(count, count_out).astype(np.float64)

    p0 = pts[seg_start[rep_seg]]
    p1 = pts[seg_end[rep_seg]]
    new_pts = p0 + (p1 - p0) * t[:, None]

    new_lengths = np.bincount(seg_poly_id, weights=count_out,
                              minlength=lengths.shape[0]).astype(np.int64)
    new_offsets = _polyline_offsets(new_lengths)
    return new_pts, new_offsets


def trim_to_vertex_budget(lengths: np.ndarray, fclasses, is_far: np.ndarray,
                          max_output_vertices: int) -> np.ndarray:
    """Return a per-polyline boolean keep-mask so the extruded output
    (``6 * (length - 1)`` vertices per polyline, per array) stays under
    *max_output_vertices*. Never drops near-tier polylines. Drops
    far-tier ``*_link`` polylines first (largest contributor first),
    then far-tier ``trunk``; motorway is never dropped (brief section
    3.1 vertex budget)."""
    lengths = np.asarray(lengths, dtype=np.int64)
    is_far = np.asarray(is_far, dtype=bool)
    keep = np.ones(lengths.shape[0], dtype=bool)
    out_verts = 6 * np.maximum(lengths - 1, 0)
    total = int(out_verts.sum())
    if total <= max_output_vertices:
        return keep

    fclasses_arr = np.asarray(list(fclasses), dtype=object)
    is_link = np.array([str(f).endswith("_link") for f in fclasses_arr])
    is_trunk = fclasses_arr == "trunk"

    for group_mask in (is_far & is_link, is_far & is_trunk & ~is_link):
        idx = np.nonzero(group_mask)[0]
        if idx.size == 0:
            continue
        idx = idx[np.argsort(-out_verts[idx])]
        for i in idx:
            if total <= max_output_vertices:
                return keep
            keep[i] = False
            total -= int(out_verts[i])
    return keep


def apply_keep_mask(pts: np.ndarray, offsets: np.ndarray, fclasses,
                    keep_mask: np.ndarray):
    """Rebuild the concatenated array + offsets after dropping the
    polylines ``keep_mask`` marks False. Only runs on the (rare)
    over-budget path, and is O(polyline count), not O(vertex count)."""
    lengths = np.diff(offsets)
    starts = offsets[:-1]
    kept = np.nonzero(keep_mask)[0]
    pieces = [pts[starts[i]:starts[i] + lengths[i]] for i in kept]
    new_pts = (np.concatenate(pieces, axis=0) if pieces
               else np.zeros((0, 2), dtype=pts.dtype))
    new_lengths = lengths[kept]
    new_offsets = _polyline_offsets(new_lengths)
    new_fclasses = [fclasses[i] for i in kept]
    return new_pts, new_offsets, new_fclasses


def extrude_ribbons(pts: np.ndarray, offsets: np.ndarray, fclasses,
                    elev_ft: np.ndarray, visible: np.ndarray,
                    ac_lat: float, ac_lon: float, pixels_per_deg: float,
                    width_m: dict | None = None,
                    casing_m: float = DEFAULT_CASING_M,
                    min_px: float = DEFAULT_MIN_PX,
                    lift_ft: float = DEFAULT_LIFT_FT,
                    out_dtype=np.float32):
    """Extrude every polyline into mitred casing + fill triangle lists.

    ``pts`` is the ``(N, 2)`` concatenated ``(lat, lon)`` vertex array
    (already subdivided), ``offsets`` its ``(P + 1,)`` polyline
    boundaries, ``fclasses`` the ``P``-length OSM class per polyline,
    ``elev_ft``/``visible`` the per-vertex sampled terrain elevation
    and LOS visibility (same shape as ``pts[:, 0]``).

    Returns ``(casing_tris, fill_tris)`` — each ``None`` or a
    ``(6 * n_visible_segments, 3)`` float32 array of
    ``(lat, lon, elev_ft)``, two triangles per visible segment, ready
    for ``_draw_overlay_cached(..., GL_TRIANGLES, ...)``. A segment is
    visible only when BOTH endpoints are (LOS match with the legacy
    GL_LINES path); a masked vertex ends the ribbon cleanly because
    each segment is its own independent quad.

    One vectorised pass over the whole array — the mitre join at each
    vertex is the normalised sum of its two adjacent segment normals
    (single-segment normal at polyline ends), scaled by
    ``1 / max(cos(theta / 2), 0.5)`` so a hairpin (near-180-degree
    reversal) clamps to at most 2x width instead of spiking to
    infinity. No per-vertex Python loop."""
    n = pts.shape[0]
    if n == 0:
        return None, None
    lengths = np.diff(offsets)
    lat_cos = float(np.cos(np.radians(ac_lat)))
    enu = _enu(pts, ac_lat, ac_lon, lat_cos)

    is_first = np.zeros(n, dtype=bool)
    is_first[offsets[:-1]] = True
    is_last = np.zeros(n, dtype=bool)
    is_last[offsets[1:] - 1] = True

    idx = np.arange(n)
    nxt = np.where(is_last, idx, idx + 1)
    prv = np.where(is_first, idx, idx - 1)

    d_fwd = enu[nxt] - enu[idx]
    d_fwd = np.where(is_last[:, None], 0.0, d_fwd)
    d_bwd = enu[idx] - enu[prv]
    d_bwd = np.where(is_first[:, None], 0.0, d_bwd)

    def _unit(v):
        norm = np.hypot(v[:, 0], v[:, 1])
        safe = np.where(norm > _EPS, norm, 1.0)
        u = v / safe[:, None]
        return np.where((norm > _EPS)[:, None], u, 0.0), norm

    fwd_u, fwd_len = _unit(d_fwd)
    bwd_u, bwd_len = _unit(d_bwd)
    n_fwd = np.stack([-fwd_u[:, 1], fwd_u[:, 0]], axis=1)
    n_bwd = np.stack([-bwd_u[:, 1], bwd_u[:, 0]], axis=1)

    # Mitre direction: normalised sum of the two adjacent normals. When
    # the sum degenerates (a near-180-degree reversal — the two normals
    # nearly cancel) fall back to n_fwd; the SCALE below (computed via
    # the numerically-stable half-angle identity, not this direction)
    # is what actually clamps the hairpin, so the fallback direction
    # only has to be finite, not exact.
    raw = n_fwd + n_bwd
    raw_norm = np.hypot(raw[:, 0], raw[:, 1])
    mitre_dir = np.where(
        (raw_norm > _EPS)[:, None],
        raw / np.where(raw_norm > _EPS, raw_norm, 1.0)[:, None],
        n_fwd)

    # cos(theta) between the two adjacent normals (== angle between the
    # two segment directions, since both normals share one rotation).
    # cos(theta / 2) via the half-angle identity is well-defined even
    # exactly at theta = 180 degrees (cos_theta = -1 -> cos_half = 0),
    # unlike deriving it from the (there ill-conditioned) mitre_dir.
    cos_theta = np.clip(np.sum(n_fwd * n_bwd, axis=1), -1.0, 1.0)
    cos_half = np.sqrt(np.clip((1.0 + cos_theta) / 2.0, 0.0, 1.0))
    scale = 1.0 / np.maximum(cos_half, 0.5)

    mitre_dir = np.where(is_first[:, None], n_fwd, mitre_dir)
    mitre_dir = np.where(is_last[:, None], n_bwd, mitre_dir)
    scale = np.where(is_first | is_last, 1.0, scale)
    nrm_v = mitre_dir * scale[:, None]

    poly_id = np.repeat(np.arange(lengths.shape[0]), lengths)
    width_lookup = width_m if width_m is not None else DEFAULT_WIDTH_M
    poly_width_m = np.array(
        [width_for_class(f, width_lookup) for f in fclasses],
        dtype=np.float64)
    hw_class = np.repeat(poly_width_m, lengths) / 2.0

    dist_m = np.hypot(enu[:, 0], enu[:, 1])
    ppd = max(float(pixels_per_deg), _EPS)

    def _floor_hw(min_px_):
        ang = np.radians(min_px_ / ppd)
        return dist_m * np.tan(ang) / 2.0

    hw_fill = np.maximum(hw_class, _floor_hw(min_px))
    hw_casing = np.maximum(hw_class + casing_m, _floor_hw(min_px + 1.0))

    elev = elev_ft.astype(np.float64) + float(lift_ft)
    visible = np.asarray(visible, dtype=bool)

    seg_start = idx[~is_last]
    seg_end = seg_start + 1
    seg_ok = visible[seg_start] & visible[seg_end]
    n_segments = int(seg_ok.sum())
    if n_segments == 0:
        return None, None
    i0 = seg_start[seg_ok]
    i1 = seg_end[seg_ok]

    def _tris(hw):
        offset_vec = nrm_v * hw[:, None]
        left_enu = enu + offset_vec
        right_enu = enu - offset_vec
        left_lat, left_lon = _enu_to_latlon(left_enu, ac_lat, ac_lon,
                                            lat_cos)
        right_lat, right_lon = _enu_to_latlon(right_enu, ac_lat, ac_lon,
                                              lat_cos)
        # Float64 through the ENU round-trip so the mitre/width math is
        # exact to well under 1e-3 m; the final cast to out_dtype (float32
        # in production, matching every other _draw_overlay_cached input)
        # only loses precision in absolute world position, not relative
        # ribbon width — that would need ~1e-5 deg (~1 m) of quantisation
        # noise per corner, which a screen-space ribbon never resolves.
        left = np.stack([left_lat, left_lon, elev], axis=1).astype(out_dtype)
        right = np.stack([right_lat, right_lon, elev],
                         axis=1).astype(out_dtype)
        tri = np.empty((n_segments * 6, 3), dtype=out_dtype)
        tri[0::6] = left[i0]
        tri[1::6] = right[i0]
        tri[2::6] = left[i1]
        tri[3::6] = right[i0]
        tri[4::6] = right[i1]
        tri[5::6] = left[i1]
        return tri

    return _tris(hw_casing), _tris(hw_fill)
