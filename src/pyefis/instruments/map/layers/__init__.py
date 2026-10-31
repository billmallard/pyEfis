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
    "road_default": "#c0c0c0",
    "river_default": "#4a6d8c",
}

#: Tuned against a black background (the panel's own darkest state, so
#: sunlight reflection sets the floor either way, and every symbol gets the
#: full luminance range). Symbols >= 3:1 against both the background and
#: the water fill, labels >= 4.5:1; range rings and roads are reference
#: lines kept recessive (>= 3:1 against the background only). Water is a
#: dark fill so symbols stay readable on top of it. Labels, runway fill,
#: flight-plan legs and ownship already pass and are unchanged. Computed
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
        pal = getattr(x, "palette", STANDARD_PALETTE)
        pen = QPen(qcolor(pal["range_ring"]))
        pen.setWidthF(max(1.0, x.w * 0.002))
        label_pen = QPen(pen)
        label_pen.setColor(qcolor(pal["range_ring_label"]))
        p.setBrush(Qt.BrushStyle.NoBrush)
        f = QFont(x.font_family)
        f.setPixelSize(max(8, int(x.w * 0.025)))
        p.setFont(f)
        for frac in (0.5, 1.0):
            r_px = x.nm_to_px(x.range_nm * frac)
            p.setPen(pen)
            p.drawEllipse(QPointF(x.cx, x.cy), r_px, r_px)
            lbl = format_range_nm(x.range_nm * frac)
            p.setPen(label_pen)
            p.drawText(QRectF(x.cx + 4, x.cy - r_px, 80, f.pixelSize() + 6),
                       Qt.AlignmentFlag.AlignLeft, lbl)
