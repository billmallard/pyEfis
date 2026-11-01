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


#: ``map_style`` values (G12, #135). ``standard`` is the terrain map as it
#: has always drawn; ``nav_only`` turns terrain relief off and repaints the
#: nav layers for a plain background (docs/moving_map_spec.md section 5.6).
MAP_STYLES = ("standard", "nav_only")

#: Per-style palette, read by every layer through :func:`palette`. Colours
#: are (r, g, b, a). STANDARD reproduces the pre-G12 constants exactly --
#: a screen with no ``map_style`` must render byte-identical to before.
#: A layer added later (airspace, CAP-204) adds its keys to BOTH tables;
#: tests/instruments/test_map_nav_only.py fails if the tables' keys differ.
STANDARD_PALETTE = {
    "background": (16, 24, 32, 255),
    "water": (60, 110, 160, 255),
    "range_ring": (255, 255, 255, 140),
    "range_ring_label": (255, 255, 255, 140),
    "airport": (197, 36, 125, 255),
    "navaid": (70, 110, 200, 255),
    "fix": (40, 60, 130, 255),
    "fix_width": 1.2,
    "airway": (90, 130, 210, 170),
    "route_past": (128, 128, 128, 255),
    "road_default": "#c0c0c0",
    "river_default": "#4a6d8c",
}

#: Tuned against a black background (the panel's own darkest state, so
#: sunlight reflection sets the floor either way, and every symbol gets the
#: full luminance range). Symbols >= 3:1 against both the background and
#: the water fill, labels >= 4.5:1; range rings and roads are reference
#: lines kept recessive (>= 3:1 against the background only). Water is a
#: dark fill so symbols stay readable on top of it. Labels, runway fill,
#: the active/future flight-plan legs and ownship already pass and are
#: unchanged; the past leg is lifted to clear 3:1 over the water fill. Computed
#: ratios are a bound, not the device check (PR body, G12).
NAV_ONLY_PALETTE = {
    "background": (0, 0, 0, 255),
    "water": (24, 56, 104, 255),
    "range_ring": (120, 120, 120, 255),
    "range_ring_label": (170, 170, 170, 255),
    "airport": (255, 100, 190, 255),
    "navaid": (130, 175, 255, 255),
    "fix": (120, 160, 230, 255),
    "fix_width": 1.5,
    "airway": (100, 140, 220, 255),
    "route_past": (144, 144, 144, 255),
    "road_default": "#808080",
    "river_default": "#4088a8",
}

_PALETTES = {"standard": STANDARD_PALETTE, "nav_only": NAV_ONLY_PALETTE}


def map_style(owner):
    """The owner's ``map_style``, normalised; anything unknown (or no
    owner) is ``standard``, so a typo never blanks the terrain."""
    style = str(getattr(owner, "map_style", "standard") or "standard")
    style = style.strip().lower()
    return style if style in _PALETTES else "standard"


def palette(owner):
    """The palette table for *owner*'s ``map_style``."""
    return _PALETTES[map_style(owner)]


def qcolor(rgba):
    return QColor(*rgba)


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


def parse_ring_fractions(text, default=(0.5, 1.0)):
    """``range_ring_fractions`` (comma list, the ``range_ladder`` idiom) ->
    sorted unique fractions of range_nm in (0, 2]. A ring past 2x range is
    off every screen, so it is dropped rather than drawn. Unparseable or
    empty input falls back to *default* (half + full, the ND convention)
    instead of losing the rings."""
    out = set()
    for part in str(text if text is not None else "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            v = float(part)
        except ValueError:
            return tuple(default)
        if 0.0 < v <= 2.0:
            out.add(v)
    return tuple(sorted(out)) or tuple(default)


@register_layer
class RangeRingsLayer(MapLayer):
    """Concentric rings around ownship at configured fractions of range
    (default half and full range), with distance labels. Options (G13,
    billmallard/pyEfis#136) are read off the map widget in configure();
    a layer that was never configured paints exactly the original
    half/full rings.

    The current range itself is NOT carried by the ring labels: the status
    chip top-left (MovingMap.paintEvent) always prints it, so turning the
    labels off never hides the range."""

    id = "range_rings"
    label = "Range rings"
    z = 20
    default_on = True

    #: label rect offset from its anchor point on the ring, and its width.
    _LABEL_DX = 4.0
    _LABEL_W = 80.0

    def __init__(self):
        super().__init__()
        self.fractions = (0.5, 1.0)
        self.labels = True
        self.label_angle = 0.0       # screen clock angle, 0 = top, 90 = right
        self.color = "#ffffff"
        self.opacity = 55            # percent; 55% of 255 rounds to alpha 140
        self.width_px = 0.0          # 0 = auto, scales with the map width
        self.label_size = 0          # 0 = auto, scales with the map width

    def configure(self, owner):
        self.fractions = parse_ring_fractions(
            getattr(owner, "range_ring_fractions", "0.5,1"))
        self.labels = bool(getattr(owner, "range_ring_labels", True))
        self.label_angle = self._num(owner, "range_ring_label_angle", 0.0) % 360.0
        self.color = str(getattr(owner, "range_ring_color", "") or "#ffffff")
        self.opacity = max(0.0, min(100.0, self._num(owner, "range_ring_opacity", 55)))
        self.width_px = max(0.0, self._num(owner, "range_ring_width", 0.0))
        self.label_size = max(0, int(self._num(owner, "range_ring_label_size", 0)))

    @staticmethod
    def _num(owner, name, default):
        try:
            return float(getattr(owner, name, default))
        except (TypeError, ValueError):
            return float(default)

    def ring_radii_px(self, x):
        """Ring radii in screen px for transform *x*, innermost first."""
        return [x.nm_to_px(x.range_nm * f) for f in self.fractions]

    def pen_color(self):
        c = QColor(self.color)
        if not c.isValid():
            c = QColor(255, 255, 255)
        c.setAlpha(int(round(self.opacity * 2.55)))
        return c

    def colors(self, x):
        """(ring, label) colours. The configured ``range_ring_color`` /
        ``range_ring_opacity`` style the standard map; any other style's
        palette owns its ring colours (nav_only keeps its tuned greys)."""
        pal = getattr(x, "palette", STANDARD_PALETTE)
        if pal is STANDARD_PALETTE:
            c = self.pen_color()
            return c, QColor(c)
        return qcolor(pal["range_ring"]), qcolor(pal["range_ring_label"])

    def pen_width(self, x):
        return self.width_px if self.width_px > 0 else max(1.0, x.w * 0.002)

    def label_pixel_size(self, x):
        return self.label_size if self.label_size > 0 else max(8, int(x.w * 0.025))

    def label_anchor(self, x, r_px):
        """Point on the ring at ``label_angle`` (screen clock, clockwise from
        straight up). The label rect's top-left sits ``_LABEL_DX`` right of
        it -- at angle 0 that is the original top-of-ring position."""
        a = math.radians(self.label_angle)
        return QPointF(x.cx + r_px * math.sin(a), x.cy - r_px * math.cos(a))

    def label_rect(self, x, r_px):
        ax = self.label_anchor(x, r_px)
        return QRectF(ax.x() + self._LABEL_DX, ax.y(), self._LABEL_W,
                      self.label_pixel_size(x) + 6)

    def paint(self, p, x):
        ring_c, label_c = self.colors(x)
        pen = QPen(ring_c)
        pen.setWidthF(self.pen_width(x))
        label_pen = QPen(pen)
        label_pen.setColor(label_c)
        p.setBrush(Qt.BrushStyle.NoBrush)
        f = QFont(x.font_family)
        f.setPixelSize(self.label_pixel_size(x))
        p.setFont(f)
        for frac, r_px in zip(self.fractions, self.ring_radii_px(x)):
            p.setPen(pen)
            p.drawEllipse(QPointF(x.cx, x.cy), r_px, r_px)
            if self.labels:
                p.setPen(label_pen)
                p.drawText(self.label_rect(x, r_px), Qt.AlignmentFlag.AlignLeft,
                           format_range_nm(x.range_nm * frac))
