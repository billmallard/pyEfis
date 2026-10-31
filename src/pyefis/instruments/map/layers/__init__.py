#  SPDX-License-Identifier: GPL-2.0-or-later
#  Moving map layer-provider model (docs/moving_map_spec.md section 4).
#  Phase A ships the base contract + registry + the range-rings layer
#  (the provider-model proof). Terrain/airports/navaids follow in
#  phases B-D.

import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPen

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
        pen = QPen(self.pen_color())
        pen.setWidthF(self.pen_width(x))
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        f = QFont(x.font_family)
        f.setPixelSize(self.label_pixel_size(x))
        p.setFont(f)
        for frac, r_px in zip(self.fractions, self.ring_radii_px(x)):
            p.drawEllipse(QPointF(x.cx, x.cy), r_px, r_px)
            if self.labels:
                p.drawText(self.label_rect(x, r_px), Qt.AlignmentFlag.AlignLeft,
                           format_range_nm(x.range_nm * frac))
