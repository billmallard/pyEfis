#  SPDX-License-Identifier: GPL-2.0-or-later
"""ADS-B traffic in the synthetic vision scene (SVSTFC1, CAP-409).

The SVS draws the same ``TFC`` targets the moving map draws (P3b,
``map/layers/traffic.py``), read by the same :class:`TrafficBlock` and
classified by the same functions (``pyefis.instruments.traffic``): the
reading rules of ``docs/fix_dynamic_list_spec.md`` section 5 live there,
once. This module
only places each target in the pilot's-eye scene and builds its symbol.

Placement. A target sits where the real aircraft would be seen: its
position, at ownship altitude plus its relative altitude
(``TFCkALT - PALT``, spec 4.9), projected by the terrain's own
view-projection (``camera.py``) in the GL overlay pass. Pressure altitude
is never used as an MSL height: ``ALT`` and ``PALT`` differ by the
altimeter setting, and only their difference is on the scene's scale.
With no relative altitude (``PALT`` unusable, or the target's ``ALT``
``bad``) the target is placed at ownship level and its tag is dashed --
the co-altitude assumption TCAS makes for a non-reporting target, so an
unknown altitude never reads as "well clear".

Symbol. The map's symbol set, billboarded: a screen-facing quad per
target, laid out in pixels and mapped into the world at the target's
range, so it keeps its pixel size wherever it is on the screen. The
arrowhead points along the target's track relative to ownship heading
(heading-up, as the map draws it); with no usable track it is a diamond.
The symbol grows inside :data:`GROW_NM` and never shrinks below its
minimum size. The relative-altitude tag sits above the symbol for traffic
above, below it otherwise, with the climb/descent arrow to the right.

Never occluded. The overlay pass composites in painter's order with the
depth test off, and traffic is the last overlay drawn: a target behind a
ridge is drawn on top of it. There is no line-of-sight dimming (airport
flags have one; traffic must not) and no haze.

Display only: no threat logic. The alert colour is the source's own alert
bit (``TFCkALRT``), exactly as on the map.
"""

import logging
import math
import time

import numpy as np

from pyefis.instruments.ai.camera import DEG_PER_RAD, M_PER_DEG_LAT, M_PER_FT
from pyefis.instruments import traffic as tfc

log = logging.getLogger(__name__)

NM_M = 1852.0

#: targets farther than this (horizontal) are not drawn in the scene.
DEFAULT_RANGE_NM = 10.0

#: inside this range the symbol grows, to 2x at half of it.
GROW_NM = 2.0

#: a target nearer than this along the line of sight is not drawn: its
#: billboard would be degenerate and it is beside or behind the eye.
MIN_FWD_M = 30.0


def _rgba(qc):
    return (qc.redF(), qc.greenF(), qc.blueF(), 1.0)


NORMAL_RGBA = _rgba(tfc.NORMAL_COLOR)
ALERT_RGBA = _rgba(tfc.ALERT_COLOR)
STALE_RGBA = _rgba(tfc.STALE_COLOR)
OUTLINE_RGBA = _rgba(tfc.OUTLINE_COLOR)

#: fill colours in draw order: stale under live, alerts on top.
COLOR_ORDER = (STALE_RGBA, NORMAL_RGBA, ALERT_RGBA)


def target_color(t):
    if t.stale:
        return STALE_RGBA
    return ALERT_RGBA if t.alert else NORMAL_RGBA


def flash_on(now):
    """Phase of an alerted target's flash, from the clock: the AI has no
    per-layer timer, so the phase is a pure function of time."""
    return int(now / tfc.FLASH_S) % 2 == 0


def symbol_px(h_px):
    """Minimum symbol half-size, pixels, for a viewport *h_px* tall."""
    return max(8.0, 0.022 * h_px)


def text_px(h_px):
    """Tag cap height, pixels."""
    return max(8.0, 0.026 * h_px)


def size_scale(range_nm):
    """Range growth of the symbol: 1 beyond GROW_NM, 2 at half of it."""
    if range_nm >= GROW_NM:
        return 1.0
    return min(2.0, GROW_NM / max(range_nm, 1e-6))


class Camera:
    """The SVS camera as the traffic builder needs it: ownship position,
    attitude (heading TRUE) and the two pixel scales of camera.py. Roll
    and the lens shift are pixel-space transforms after the projection,
    so they need nothing here."""

    def __init__(self, lat, lon, alt_ft, heading_deg, pitch_deg,
                 ppd_v, ppd_h, h_px):
        self.lat, self.lon, self.alt_ft = lat, lon, alt_ft
        self.h_px = h_px
        self.ppd_v, self.ppd_h = ppd_v, ppd_h
        ch, sh = math.cos(math.radians(heading_deg)), math.sin(
            math.radians(heading_deg))
        cp, sp = math.cos(math.radians(pitch_deg)), math.sin(
            math.radians(pitch_deg))
        self.heading_deg = heading_deg
        # ENU basis of the camera (see camera.view_projection): right,
        # forward along the boresight, and screen-up.
        self.right = np.array([ch, -sh, 0.0])
        self.fwd = np.array([sh * cp, ch * cp, sp])
        self.up = np.array([-sh * sp, -ch * sp, cp])
        self.lat_cos = math.cos(math.radians(lat))


def _symbol(s, directional):
    """The map's symbol outline (tfc.symbol_polygon), y flipped to up."""
    if directional:
        return np.array([(0, s), (s * 0.75, -s * 0.75), (0, -s * 0.3),
                         (-s * 0.75, -s * 0.75)], dtype=float)
    return np.array([(0, s), (s * 0.8, 0), (0, -s), (-s * 0.8, 0)],
                    dtype=float)


def _fan(poly):
    """Triangles of a 4-point outline: (0,1,2) + (0,2,3). Right for both
    symbols, the arrowhead's notch being vertex 2."""
    return poly[[0, 1, 2, 0, 2, 3]]


def _grow(poly, d):
    """The outline pushed out by about *d* pixels from its centre."""
    c = poly.mean(axis=0)
    v = poly - c
    n = np.linalg.norm(v, axis=1, keepdims=True)
    return c + v * (1.0 + d / np.maximum(n, 1e-6))


def _segment(a, b, w):
    """Two triangles covering the segment a-b, *w* pixels wide."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    d = b - a
    ln = math.hypot(d[0], d[1])
    if ln < 1e-9:
        return np.zeros((0, 2))
    nx, ny = -d[1] / ln * w / 2.0, d[0] / ln * w / 2.0
    n = np.array([nx, ny])
    # Extend the ends by half the width: square caps, closed corners.
    ext = d / ln * w / 2.0
    a2, b2 = a - ext, b + ext
    return np.array([a2 + n, b2 + n, b2 - n, a2 + n, b2 - n, a2 - n])


def _outline(poly, w, dashed=False):
    out = []
    k = len(poly)
    for i in range(k):
        a, b = poly[i], poly[(i + 1) % k]
        if not dashed:
            out.append(_segment(a, b, w))
            continue
        # Two dashes per edge: the map's dashed stale outline.
        for f0, f1 in ((0.0, 0.35), (0.6, 0.95)):
            out.append(_segment(a + (b - a) * f0, a + (b - a) * f1, w))
    return np.concatenate(out)


def _arrow(x, half, head, d):
    """Climb (d=+1) / descent (d=-1) arrow at pixel column *x*, as lines."""
    tip, tail = (x, d * half), (x, -d * half)
    wl = (x - head, d * half - d * head)
    wr = (x + head, d * half - d * head)
    return ((tail, tip), (wl, tip), (wr, tip))


def _text_quads(tag, cx, y_top, cap, uvs):
    """Glyph quads (x, y, u, v) for *tag* centred on *cx*, its cap top at
    *y_top* (pixel frame, y up). Uses the atlas's tag glyphs (``t<ch>``:
    one baseline, advance-wide boxes, so no extra spacing); a glyph's
    width follows its box's aspect, so the tag keeps the font's
    proportions."""
    glyphs = []
    width = 0.0
    gap = 0.0
    for ch in tag:
        uv = uvs.get("t" + ch)
        if uv is None:
            continue
        u0, v0, u1, v1 = uv
        gw = cap * (u1 - u0) / max(v1 - v0, 1e-9)
        glyphs.append((gw, uv))
        width += gw + gap
    width -= gap if glyphs else 0.0
    x = cx - width / 2.0
    out = []
    for gw, (u0, v0, u1, v1) in glyphs:
        # v0 is the glyph's top row in the atlas image (image rows run
        # down, as the runway designators lay them out).
        tl = (x, y_top, u0, v0)
        tr = (x + gw, y_top, u1, v0)
        br = (x + gw, y_top - cap, u1, v1)
        bl = (x, y_top - cap, u0, v1)
        out.extend((tl, bl, br, tl, br, tr))
        x += gw + gap
    return out


class TrafficGeometry:
    """One frame of traffic, as the GL pass draws it.

    ``layers`` is in draw order, one per symbol class -- stale, then
    normal, then alerted (the map's draw order), so an alerted target and
    its tag are never covered by another target's. Each layer is
    ``(tris, text)``: ``tris`` a list of (rgba, Nx3 float64 lat, lon,
    elev_ft) for the flat overlay program, halo first; ``text`` a list of
    (rgba, Nx5 float64 lat, lon, elev_ft, u, v) for the text program,
    halo first. ``drawn`` records, per target drawn, ``(ident,
    anchor_lat, anchor_lon, anchor_elev_ft, rgba, tag)``."""

    def __init__(self):
        self.layers = []
        self.drawn = []

    @property
    def tris(self):
        return [x for tris, _text in self.layers for x in tris]

    @property
    def text(self):
        return [x for _tris, text in self.layers for x in text]

    def __bool__(self):
        return bool(self.drawn)


#: pixel-frame shapes kept per SVSTraffic; a shape is a few hundred floats.
SHAPE_CACHE_MAX = 512


#: shape arrays, in the order a class draws them: symbol halo, trend
#: arrow halo, symbol ink, arrow ink, tag halo, tag ink. Only the symbol
#: turns with the target's track.
_KINDS = 6
_ROTATES = (True, False, True, False, False, False)


def _shape(filled, directional, dashed, d, tag, above, s, cap, uvs):
    """One target's geometry in the pixel frame (x right, y up, origin at
    the target, symbol nose up), as six Nx4 (x, y, u, v) triangle-vertex
    arrays in :data:`_KINDS` order; UVs are used by the tag arrays only.
    It does not depend on the target's track or position, so it is
    cached: a frame only rotates the symbol and maps it into the world."""
    poly = _symbol(s, directional)
    if filled:
        sym = (_fan(_grow(poly, 1.5)), _fan(poly))
    else:
        sym = (_outline(poly, 4.0), _outline(poly, 2.0, dashed=dashed))
    arrow_h, arrow_i = [np.zeros((0, 2))], [np.zeros((0, 2))]
    if d:
        for a, b in _arrow(s * 1.3, s * 0.8, s * 0.35, d):
            arrow_h.append(_segment(a, b, 4.0))
            arrow_i.append(_segment(a, b, 2.0))
    y_top = s * 1.2 + cap if above else -s * 1.2
    q = np.array(_text_quads(tag, 0.0, y_top, cap, uvs),
                 dtype=float).reshape(-1, 4)
    t_halo = np.concatenate(
        [q + (dx, dy, 0.0, 0.0)
         for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1))])

    def xy0(a):
        return np.hstack([a, np.zeros((len(a), 2))])

    return (xy0(sym[0]), xy0(np.concatenate(arrow_h)), xy0(sym[1]),
            xy0(np.concatenate(arrow_i)), t_halo, q)


def _layout(entries, cls):
    """Concatenate the frame's cached shapes in draw order: pixel vertices,
    the entry each vertex belongs to, whether it turns with track, and
    each (class, kind)'s vertex span. Cached by the shapes in play, so a
    frame whose targets kept their shapes reuses it."""
    parts, owner, turns, plan = [], [], [], []
    n = i0 = 0
    for rgba in COLOR_ORDER:
        group = range(i0, i0 + len(cls[rgba]))
        i0 += len(cls[rgba])
        for kind in range(_KINDS):
            n0 = n
            for i in group:
                pts = entries[i][0][kind]
                if len(pts):
                    parts.append(pts)
                    owner.append(i)
                    turns.append(_ROTATES[kind])
                    n += len(pts)
            plan.append((n0, n))
    counts = [len(p) for p in parts]
    return (np.concatenate(parts), np.repeat(np.array(owner), counts),
            np.repeat(np.array(turns), counts), plan)


def build(targets, cam, palt_ft, magvar, now, uvs,
          range_nm=DEFAULT_RANGE_NM, cache=None):
    """Lay out every drawable target. Pure: no Qt, no GL, no bus.

    Per target only placement and a cache lookup run in Python; every
    vertex is rotated and mapped into the world in one vectorised step per
    frame, because this runs on the GUI thread inside the paint."""
    geo = TrafficGeometry()
    if cache is None:
        cache = {}
    s0 = symbol_px(cam.h_px)
    cap = text_px(cam.h_px)
    blink = flash_on(now)
    r0, r1 = cam.right[0], cam.right[1]
    f0, f1, f2 = cam.fwd
    m_lon = M_PER_DEG_LAT * cam.lat_cos
    # per class (fill colour): (shape, (e, n, u), mx, my, rot_deg)
    cls = {c: [] for c in COLOR_ORDER}

    for t in tfc.draw_order(targets):
        if not tfc.visible(t, now):
            continue
        rel = tfc.relative_alt_ft(t, palt_ft)
        e = (t.lon - cam.lon) * m_lon
        n = (t.lat - cam.lat) * M_PER_DEG_LAT
        u = (rel or 0.0) * M_PER_FT
        horiz_nm = math.hypot(e, n) / NM_M
        if horiz_nm > range_nm:
            continue
        fwd = e * f0 + n * f1 + u * f2
        if fwd < MIN_FWD_M:
            continue
        # metres per pixel at this target's depth, across and up
        mx = fwd / (DEG_PER_RAD * cam.ppd_h)
        my = fwd / (DEG_PER_RAD * cam.ppd_v)
        s = s0 * size_scale(math.hypot(horiz_nm, u / NM_M))
        color = target_color(t)
        trk = tfc.true_track(t, magvar)
        filled = not t.stale and not tfc.is_degraded(t)
        if t.alert and not t.stale and not blink:
            filled = False
        tag = tfc.alt_tag(rel)
        key = (filled, trk is not None, t.stale, tfc.trend(t), tag,
               rel is not None and rel > 0, round(s * 2.0) / 2.0, cap)
        shape = cache.get(key)
        if shape is None:
            if len(cache) >= SHAPE_CACHE_MAX:
                cache.clear()
            shape = cache[key] = _shape(*key, uvs)
        rot = 0.0 if trk is None else trk - cam.heading_deg
        cls[color].append((shape, (e, n, u), mx, my, rot))
        geo.drawn.append((t.ident, t.lat, t.lon,
                          cam.alt_ft + u / M_PER_FT, color, tag))

    # One transform for every vertex of the frame, then split per draw.
    entries = [x for rgba in COLOR_ORDER for x in cls[rgba]]
    if not entries:
        return geo
    per = np.array([(e[1][0], e[1][1], e[1][2], e[2], e[3],
                     math.cos(math.radians(e[4])),
                     math.sin(math.radians(e[4]))) for e in entries])
    sig = tuple(id(e[0]) for e in entries) + tuple(
        len(cls[rgba]) for rgba in COLOR_ORDER)
    lay = cache.get(sig)
    if lay is None:
        lay = cache[sig] = _layout(entries, cls)
    px, idx, turn, plan = lay
    v = per[idx]
    c = np.where(turn, v[:, 5], 1.0)
    sn = np.where(turn, v[:, 6], 0.0)
    n = len(px)
    # clockwise by the track relative to heading (pixel frame, y up)
    x = px[:, 0] * c + px[:, 1] * sn
    y = -px[:, 0] * sn + px[:, 1] * c
    ox, oy = x * v[:, 3], y * v[:, 4]
    world = np.empty((n, 3))
    world[:, 0] = cam.lat + (v[:, 1] + ox * r1 + oy * cam.up[1]) \
        / M_PER_DEG_LAT
    world[:, 1] = cam.lon + (v[:, 0] + ox * r0 + oy * cam.up[0]) / m_lon
    world[:, 2] = cam.alt_ft + (v[:, 2] + oy * cam.up[2]) / M_PER_FT

    for k, rgba in enumerate(COLOR_ORDER):
        if not cls[rgba]:
            continue
        sp = plan[k * _KINDS:(k + 1) * _KINDS]
        halo = (sp[0][0], sp[1][1])          # symbol + arrow halos
        ink = (sp[2][0], sp[3][1])
        tris = [(OUTLINE_RGBA, world[halo[0]:halo[1]]),
                (rgba, world[ink[0]:ink[1]])]
        text = []
        (a0, a1), (b0, b1) = sp[4], sp[5]
        if b1 > b0:
            text = [(OUTLINE_RGBA,
                     np.hstack([world[a0:a1], px[a0:a1, 2:4]])),
                    (rgba, np.hstack([world[b0:b1], px[b0:b1, 2:4]]))]
        geo.layers.append((tris, text))
    return geo


class SVSTraffic:
    """The SVS's view of the ``TFC`` block: the map's reader, plus the
    repaint wake-ups the AI frame clock needs (a write, a flash phase,
    a stale target timing out)."""

    def __init__(self, db, on_change=None, range_nm=DEFAULT_RANGE_NM):
        self.range_nm = float(range_nm)
        self._on_change = on_change
        self._wake_key = None
        self._shapes = {}
        self.block = tfc.TrafficBlock(db, self._changed)
        if not self.block.available:
            log.info("svs traffic: no TFC block on the bus; traffic inert")
            self.block = None
        self._palt = self._magvar = None
        for key, attr in (("PALT", "_palt"), ("MAGVAR", "_magvar")):
            try:
                setattr(self, attr, db.get_item(key))
            except KeyError:
                if key == "PALT" and self.block is not None:
                    log.warning("svs traffic: no PALT key; relative "
                                "altitude is dashed and targets sit at "
                                "ownship level")

    @property
    def available(self):
        return self.block is not None

    def _changed(self):
        if self._on_change is not None:
            self._on_change()

    def targets(self):
        return [] if self.block is None else self.block.targets()

    def palt_ft(self):
        return tfc.usable(self._palt)

    def magvar(self):
        return tfc.usable(self._magvar)

    def needs_repaint(self, now=None):
        """True when the drawn picture changed with no bus write: an
        alerted target's flash phase flipped, or a stale target passed
        its hide time. Cheap; called by the frame clock every tick."""
        if self.block is None:
            return False
        now = time.monotonic() if now is None else now
        shown = tuple(sorted(t.ident for t in self.targets()
                             if tfc.visible(t, now)))
        alerting = any(t.alert and not t.stale for t in self.targets())
        key = (shown, flash_on(now) if alerting else None)
        if key == self._wake_key:
            return False
        self._wake_key = key
        return True

    def geometry(self, cam, uvs, now=None):
        if self.block is None:
            return TrafficGeometry()
        now = time.monotonic() if now is None else now
        return build(self.targets(), cam, self.palt_ft(), self.magvar(),
                     now, uvs, self.range_nm, self._shapes)
