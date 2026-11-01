#  SPDX-License-Identifier: GPL-2.0-or-later
#  Moving map layer-provider model (docs/moving_map_spec.md section 4).
#  Phase A ships the base contract + registry + the range-rings layer
#  (the provider-model proof). Terrain/airports/navaids follow in
#  phases B-D.

import math
import threading

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (QColor, QFont, QPainter, QPainterPath, QPen,
                         QPolygonF, QTransform)

from pyefis.instruments.ai.camera import M_PER_DEG_LAT

#: id -> layer class. Out-of-tree layers register here too.
LAYER_REGISTRY = {}

#: geometric ratio between adjacent range buckets (MP1, brief section 4):
#: a render key built from round(range_nm, N) posts a new worker job on
#: almost every gesture event during a continuous pinch/wheel zoom, even
#: though the window is barely different -- the worker never gets to
#: publish before the key moves on again. Bucketing on log(range)/log(base)
#: instead means a window key survives a +-6% range change (half the 12%
#: bucket width); the paint-side blit rescales the stale image to fit.
_RANGE_BUCKET_BASE = 1.12


def range_bucket(range_nm):
    """Geometric range-bucket index for a layer's window/snapshot key."""
    return round(math.log(max(1e-6, float(range_nm))) / math.log(_RANGE_BUCKET_BASE))


def format_range_nm(nm):
    """Round a continuous NM value to something readable for DISPLAY only
    (the range chip, ring labels) -- "14 NM" instead of "13.7234" (#202).
    range_nm itself stays continuous throughout a pinch (Bill, AER-1216
    2026-09-15: zoom must feel continuous); only what gets printed rounds."""
    nm = max(0.0, float(nm))
    if nm < 10.0:
        return ("%.1f" % nm).rstrip("0").rstrip(".")
    return str(int(round(nm)))


def register_layer(cls):
    LAYER_REGISTRY[cls.id] = cls
    return cls


# --- window-image history (MP13, pyEfis #203) -------------------------------
# The image layers (terrain, roads, rivers) render a NORTH-UP window image on
# a worker and paint() rotate-blits it. By MP1 design nothing renders mid-
# gesture, so a pinch-out blits the last image scaled DOWN; it only spans
# 1.25x the viewport half-diagonal, so past ~25% the dark fill shows until
# the settle render lands. Each layer therefore keeps its last few published
# images, and while the current one does not cover the viewport, the widest
# compatible earlier image is painted behind it instead of the dark fill.

#: images kept per layer (brief map_gesture_perf_plan.md MP13: "3 deep").
#: Memory bound: an image is at most 1024 x 1024 x 4 bytes = 4 MiB, so a
#: layer holds at most 12 MiB, the current image included.
RENDER_HISTORY_DEPTH = 3


def _entry_side_m(entry):
    """Ground side length, metres, of a square window image entry
    ``(QImage, key, (centre lat, centre lon, metres per px))``."""
    return entry[0].width() * entry[2][2]


def _entry_contains(entry, lat, lon):
    """True if ``(lat, lon)`` lies inside *entry*'s north-up footprint."""
    clat, clon, _mpp = entry[2]
    half = _entry_side_m(entry) / 2.0
    dn = (lat - clat) * M_PER_DEG_LAT
    de = (lon - clon) * M_PER_DEG_LAT * math.cos(math.radians(clat))
    return abs(dn) <= half and abs(de) <= half


class RenderHistory:
    """The last few published window images of one layer, newest last.

    Entries are the layer's own ``(QImage, key, meta)`` tuples, shared by
    reference (no copy). A key is ``(lat snap, lon snap, range bucket,
    *rest)``; two entries are compatible -- may stand in for each other --
    only when ``key[3:]`` matches (same widget size, terrain mode, caution
    altitude band), since only position and range are allowed to differ.

    Eviction on :meth:`add`, in order: an entry of the same range bucket
    (replaced by the newer pose), incompatible entries, entries whose
    footprint no longer contains the new image's centre (flown away from),
    then the oldest entry that is not the widest. The widest is protected
    because it is the one a pinch-out needs; a run of close-in renders must
    not push it out."""

    def __init__(self, depth=RENDER_HISTORY_DEPTH):
        self.depth = max(1, int(depth))
        self._entries = []
        self._lock = threading.Lock()

    def __len__(self):
        with self._lock:
            return len(self._entries)

    def entries(self):
        with self._lock:
            return list(self._entries)

    def clear(self):
        with self._lock:
            self._entries = []

    def add(self, entry):
        key = entry[1]
        clat, clon = entry[2][0], entry[2][1]
        with self._lock:
            keep = [e for e in self._entries
                    if e[1][2] != key[2] and e[1][3:] == key[3:]]
            while len(keep) + 1 > self.depth:
                stale = [e for e in keep
                         if not _entry_contains(e, clat, clon)]
                if stale:
                    keep.remove(stale[0])       # oldest flown-away first
                    continue
                widest = max(keep, key=_entry_side_m)
                rest = [e for e in keep if e is not widest]
                keep.remove(rest[0] if rest else widest)
            keep.append(entry)
            self._entries = keep

    def widest(self, key):
        """The widest entry compatible with *key*, or None."""
        with self._lock:
            ok = [e for e in self._entries if e[1][3:] == key[3:]]
        return max(ok, key=_entry_side_m) if ok else None


def _window_transform(x, entry):
    """Painter transform carrying *entry*'s image-centred pixel frame onto
    the screen at *x*, and the image's half side in those pixels."""
    clat, clon, mpp = entry[2]
    c = x.to_screen(clat, clon)
    t = QTransform()
    t.translate(c.x(), c.y())
    if x.rot:
        # to_screen applies R(+rot) to world EN vectors; carrying a
        # NORTH-UP image onto that screen needs the painter rotated by
        # -rot (QPainter.rotate is clockwise, y-down) -- #90.
        t.rotate(-math.degrees(x.rot))
    s = mpp * x._px_per_m                    # screen px per image px
    return t, entry[0].width() * s / 2.0


def window_covers_viewport(x, entry):
    """True if *entry*'s image, blitted at *x*, covers the whole viewport."""
    t, half = _window_transform(x, entry)
    inv, ok = t.inverted()
    if not ok:
        return False
    for px, py in ((0.0, 0.0), (x.w, 0.0), (0.0, x.h), (x.w, x.h)):
        q = inv.map(QPointF(px, py))
        if abs(q.x()) > half or abs(q.y()) > half:
            return False
    return True


def blit_window_image(p, x, entry, smooth=False):
    """Rotate-blit a north-up window image *entry* registered to *x*."""
    t, half = _window_transform(x, entry)
    p.save()
    p.setTransform(t, True)
    if smooth:
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.drawImage(QRectF(-half, -half, 2.0 * half, 2.0 * half), entry[0])
    p.restore()


def paint_window_images(p, x, current, history, key, smooth=False):
    """Paint a layer's current window image, backed by the widest earlier
    image from *history* where the current one leaves the viewport bare.

    With the current image on its exact *key*, or covering the viewport,
    this is a plain blit. Otherwise (a pinch-out blitting a stale image
    scaled down) the widest compatible history entry, if it is wider than
    the current image, is drawn first, clipped OUT of the current image's
    footprint -- a transparent overlay (roads) must not draw its features
    twice where the two images overlap, and the opaque terrain image is
    spared the overdraw."""
    if current is None:
        return
    if current[1] != key and not window_covers_viewport(x, current):
        back = history.widest(key)
        if back is not None and _entry_side_m(back) > _entry_side_m(current):
            t, half = _window_transform(x, current)
            hole = QPainterPath()
            hole.addPolygon(t.map(QPolygonF(QRectF(-half, -half,
                                                   2.0 * half, 2.0 * half))))
            area = QPainterPath()
            area.addRect(QRectF(0.0, 0.0, x.w, x.h))
            p.save()
            p.setClipPath(area.subtracted(hole), Qt.ClipOperation.IntersectClip)
            blit_window_image(p, x, back, smooth)
            p.restore()
    blit_window_image(p, x, current, smooth)


class MapLayer:
    """One toggleable information layer.

    Contract (spec section 4): ``collect()`` runs on a worker thread,
    serialised with the SVS collectors; it must leave an immutable
    snapshot for ``paint()``, which runs on the GUI thread and may only
    blit/draw prepared data. Phase A layers are cheap enough to skip
    collect entirely.
    """

    id = "base"
    label = "Layer"
    z = 0
    default_on = True

    def __init__(self):
        self.enabled = self.default_on

    def configure(self, config):
        pass

    def collect(self, xform):
        pass

    def paint(self, painter, xform):
        raise NotImplementedError

    def on_toggle(self, on):
        self.enabled = on

    def is_settled(self, xform):
        """MP6 (settle latency, brief section 4): True once this layer's
        cached render matches *xform*'s key, so it would blit exact
        content rather than a stale scaled image. Default True for
        layers with no async render (e.g. range rings) -- they never
        block the settle measurement."""
        return True

    def hit(self, xform, x, y, tol_px):
        """FP10 (billmallard/pyEfis#186): the objects this layer painted
        within *tol_px* screen pixels of ``(x, y)``, as
        ``(distance_px, flightplan.waypoints.Waypoint)`` pairs. Only what
        the last ``paint()`` would actually show is hittable -- the same
        range gates, the same snapshot, nothing off screen -- and like
        ``paint()`` it never queries a database. Default: nothing."""
        return []


def hit_distance(xform, lat, lon, x, y, tol_px):
    """Screen distance from ``(x, y)`` to the projected ``(lat, lon)``, or
    None if it is farther than *tol_px* (inclusive: exactly *tol_px* hits)."""
    c = xform.to_screen(lat, lon)
    d = math.hypot(c.x() - x, c.y() - y)
    return d if d <= tol_px else None


@register_layer
class RangeRingsLayer(MapLayer):
    """Concentric rings at half and full range around ownship, with
    distance labels -- trivial by design: it proves the provider
    seam end to end (registry, config, toggle, paint contract)."""

    id = "range_rings"
    label = "Range rings"
    z = 20
    default_on = True

    def paint(self, p, x):
        pen = QPen(QColor(255, 255, 255, 140))
        pen.setWidthF(max(1.0, x.w * 0.002))
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        f = QFont(x.font_family)
        f.setPixelSize(max(8, int(x.w * 0.025)))
        p.setFont(f)
        for frac in (0.5, 1.0):
            r_px = x.nm_to_px(x.range_nm * frac)
            p.drawEllipse(QPointF(x.cx, x.cy), r_px, r_px)
            lbl = format_range_nm(x.range_nm * frac)
            p.drawText(QRectF(x.cx + 4, x.cy - r_px, 80, f.pixelSize() + 6),
                       Qt.AlignmentFlag.AlignLeft, lbl)
