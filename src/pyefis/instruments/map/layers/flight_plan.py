#  SPDX-License-Identifier: GPL-2.0-or-later
#  Moving map flight_plan layer (spec 3.6, FP6, billmallard/pyEfis#184).
#
#  Pure paint() -- no worker, no database (like RangeRingsLayer): the route
#  block, active-leg state and direct-to point already live on the FIX bus
#  (FP4 fixbridge.FixBridge), so there is nothing to collect.
#
#  FixBridge's listener callbacks are plain Python callables invoked
#  directly by whatever thread emits the underlying FIX ``valueWrite``
#  signal -- the fix-gateway network client thread, not the GUI thread
#  (fixbridge.py's own docstring). _BridgeRelay is a tiny QObject that
#  re-emits onto its own thread affinity: connecting a bound QObject slot
#  to another QObject's signal via ``.connect()`` lets Qt's AutoConnection
#  detect the thread mismatch and queue the call, which a raw callable in
#  FixBridge's listener list cannot do.
#
#  Great-circle legs are drawn as straight screen segments with no
#  subdivision. Verified numerically against MapTransform.to_screen: for a
#  leg near the edge of the widest shipped range (160 NM), the chord-vs-
#  geodesic pixel deviation is ~0.1 px at a 40 NM leg, ~0.4 px at 80 NM, and
#  only crosses 1 px past ~110 NM -- comfortably above a typical enroute leg.

import math
import time

from PyQt6.QtCore import QObject, QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QPen, QPolygonF

from pyavtools import fix as pyavtools_fix

from pyefis.flightplan import fixbridge as fp_fixbridge
from pyefis.flightplan import geo as fp_geo
from pyefis.instruments.map.layers import MapLayer, register_layer

PAST = QColor("#808080")
ACTIVE = QColor("#ff00ff")
FUTURE = QColor("#ffffff")

_LEG_WIDTH = 2.0
_ACTIVE_WIDTH = 3.0

#: declutter (spec 3.6): labels off above this range, symbols stay.
_IDENT_RANGE = 80.0
#: nothing draws above this range except the legs.
_SYMBOL_RANGE = 160.0

# Appendix A codes (matches instruments/flight_plan/__init__.py's
# _STATE_BADGES / _APR_TEXT mapping).
_STATE_DIRECT = 2
_STATE_SUSP = 3
_APR_LNAV = 2

_ROLE_SUFFIX = {"iaf": "IAF", "faf": "FAF", "map": "MAP", "mahp": "MAHP"}

#: length of the dashed extended-final-course line drawn past the MAP while
#: suspended. Not spec'd to an exact distance -- the look is Bill's call
#: after the first bench screenshot (CLAUDE.md convention); this is a
#: reasonable default that stays visible without dominating the plan.
_EXTENSION_NM = 5.0


def _engine_val(engine, key, default=None):
    item = engine.get(key)
    return default if item is None else item.value


def _off_route_direct(engine):
    state = int(_engine_val(engine, "FPLSTATE", 0) or 0)
    act_leg = int(_engine_val(engine, "FPLACTLEG", 0) or 0)
    return state == _STATE_DIRECT and act_leg == 0


def build_legs(route, engine):
    """Pure geometry/color computation for the plan's slot-to-slot legs --
    testable without Qt. Returns ``[(color, (lat1, lon1), (lat2, lon2)), ...]``
    in slot order (plus a leading synthetic entry when ``FPLACTLEG`` = 1 --
    see below). The direct-to line is a separate item (see
    :func:`build_direct_to`).

    ``FPLACTLEG`` (Appendix A) is the 1-based slot number of the active
    leg's TO waypoint, i.e. leg index ``i`` (0-based, slots[i] -> slots[i+1])
    has TO-waypoint slot number ``i + 2``. ``FPLACTLEG`` = 1 is a real engine
    state (a freshly activated plan, or ``ACT 1``) with no prior route slot
    at all -- the FROM point is the aircraft's live position, not
    ``slots[-1]`` -- so it can't be represented by any ``slots[i]``/
    ``slots[i+1]`` pair; every real route leg is still ahead in that case."""
    slots = route.waypoints
    off_route = _off_route_direct(engine)
    act_leg = int(_engine_val(engine, "FPLACTLEG", 0) or 0)
    fr_lat = _engine_val(engine, "FPLFRLAT", 0.0) or 0.0
    fr_lon = _engine_val(engine, "FPLFRLON", 0.0) or 0.0
    to_lat = _engine_val(engine, "WPLAT", 0.0) or 0.0
    to_lon = _engine_val(engine, "WPLON", 0.0) or 0.0
    legs = []
    if act_leg == 1 and not off_route:
        legs.append((ACTIVE, (fr_lat, fr_lon), (to_lat, to_lon)))
    for i in range(len(slots) - 1):
        a, b = slots[i], slots[i + 1]
        to_idx = i + 2   # 1-based slot number of this leg's TO waypoint (b)
        if off_route:
            legs.append((PAST, (a.lat, a.lon), (b.lat, b.lon)))
        elif act_leg and to_idx == act_leg:
            # The FROM point is FPLFRLAT/LON, not slot[i] -- a direct-to
            # activation point differs from the previous route slot.
            legs.append((ACTIVE, (fr_lat, fr_lon), (to_lat, to_lon)))
        elif act_leg and to_idx < act_leg:
            legs.append((PAST, (a.lat, a.lon), (b.lat, b.lon)))
        else:
            legs.append((FUTURE, (a.lat, a.lon), (b.lat, b.lon)))
    return legs


def build_direct_to(route, engine, dto):
    """The magenta direct-to line for the off-route case (``FPLSTATE`` =
    DIRECT, ``FPLACTLEG`` = 0): activation point -> ``DTO*``. ``None`` when
    not applicable (on-route, or no DTO point)."""
    if dto is None or not _off_route_direct(engine):
        return None
    fr_lat = _engine_val(engine, "FPLFRLAT", 0.0) or 0.0
    fr_lon = _engine_val(engine, "FPLFRLON", 0.0) or 0.0
    return (ACTIVE, (fr_lat, fr_lon), (dto.lat, dto.lon))


def build_symbols(route, engine):
    """Pure per-slot symbol data: ``[(color, lat, lon, type, label,
    ringed), ...]``. ``ringed`` marks the current TO waypoint."""
    slots = route.waypoints
    off_route = _off_route_direct(engine)
    act_leg = int(_engine_val(engine, "FPLACTLEG", 0) or 0)
    out = []
    for i, wp in enumerate(slots):
        slot_idx = i + 1
        if off_route:
            color, ringed = PAST, False
        elif act_leg and slot_idx == act_leg:
            color, ringed = ACTIVE, True
        elif act_leg and slot_idx < act_leg:
            color, ringed = PAST, False
        else:
            color, ringed = FUTURE, False
        label = wp.id
        suffix = _ROLE_SUFFIX.get(wp.role, "")
        if suffix:
            label = f"{label} {suffix}"
        out.append((color, wp.lat, wp.lon, wp.type, label, ringed))
    return out


def build_dto_symbol(route, engine, dto):
    """The DTO point's own symbol (off-route case only), ringed magenta
    like an in-plan TO waypoint. ``None`` when not applicable."""
    if dto is None or not _off_route_direct(engine):
        return None
    return (ACTIVE, dto.lat, dto.lon, dto.type, dto.id or "", True)


def build_extension(route, engine):
    """The dashed extended-final-approach-course segment past the MAP,
    drawn only while suspended there (``FPLSTATE`` = SUSP, ``FPLAPR`` =
    LNAV). Returns ``((lat1, lon1), (lat2, lon2))`` or ``None``. The
    extension course is ``FPLCRS`` (the engine's current desired track) if
    published, else the bearing of the leg into the MAP."""
    state = int(_engine_val(engine, "FPLSTATE", 0) or 0)
    apr = int(_engine_val(engine, "FPLAPR", 0) or 0)
    if state != _STATE_SUSP or apr != _APR_LNAV:
        return None
    slots = route.waypoints
    idx = next((k for k, s in enumerate(slots) if s.role == "map"), None)
    if idx is None:
        return None
    map_wp = slots[idx]
    crs = _engine_val(engine, "FPLCRS", None)
    if not crs and idx > 0:
        crs = fp_geo.initial_bearing(slots[idx - 1].lat, slots[idx - 1].lon,
                                      map_wp.lat, map_wp.lon)
    if not crs:
        return None
    end = fp_geo.destination_point(map_wp.lat, map_wp.lon, float(crs), _EXTENSION_NM)
    return ((map_wp.lat, map_wp.lon), end)


class _BridgeRelay(QObject):
    """Marshals a FixBridge listener callback onto the GUI thread (see the
    module docstring): ``owner`` is the MovingMap widget, so this relay
    lives on its thread; Qt auto-queues ``changed -> owner.update`` when
    ``changed`` is emitted from a foreign thread."""

    changed = pyqtSignal()

    def __init__(self, owner):
        super().__init__(owner)
        self.changed.connect(owner.update)

    def on_bridge_change(self):
        self.changed.emit()


@register_layer
class FlightPlanLayer(MapLayer):
    id = "flight_plan"
    label = "Flight plan"
    z = 45
    default_on = True

    def __init__(self):
        super().__init__()
        self._owner = None
        self._bridge = None
        self._relay = None

    def configure(self, owner):
        self._owner = owner
        self._bridge = fp_fixbridge.FixBridge(pyavtools_fix)
        if self._bridge.available:
            self._relay = _BridgeRelay(owner)
            self._bridge.add_listener(self._relay.on_bridge_change)

    def paint(self, p, x):
        t0 = time.perf_counter()
        try:
            self._paint(p, x)
        finally:
            perf = getattr(self._owner, "perf", None)
            if perf is not None:
                perf.layer(self.id).record_render_ms((time.perf_counter() - t0) * 1000.0)

    def _paint(self, p, x):
        if self._bridge is None or not self._bridge.available:
            return
        route = self._bridge.read_route()
        engine = self._bridge.read_engine()
        if route is None or engine is None:
            return
        dto = self._bridge.read_direct_to()

        pen = QPen()
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        for color, (la1, lo1), (la2, lo2) in build_legs(route, engine):
            pen.setColor(color)
            pen.setWidthF(_ACTIVE_WIDTH if color == ACTIVE else _LEG_WIDTH)
            p.setPen(pen)
            p.drawLine(x.to_screen(la1, lo1), x.to_screen(la2, lo2))

        direct = build_direct_to(route, engine, dto)
        if direct is not None:
            color, (la1, lo1), (la2, lo2) = direct
            pen.setColor(color)
            pen.setWidthF(_ACTIVE_WIDTH)
            p.setPen(pen)
            p.drawLine(x.to_screen(la1, lo1), x.to_screen(la2, lo2))

        ext = build_extension(route, engine)
        if ext is not None:
            (la1, lo1), (la2, lo2) = ext
            epen = QPen(ACTIVE)
            epen.setWidthF(_ACTIVE_WIDTH)
            epen.setStyle(Qt.PenStyle.DashLine)
            p.setPen(epen)
            p.drawLine(x.to_screen(la1, lo1), x.to_screen(la2, lo2))

        if x.range_nm > _SYMBOL_RANGE:
            return
        show_labels = x.range_nm <= _IDENT_RANGE
        symbols = build_symbols(route, engine)
        dsym = build_dto_symbol(route, engine, dto)
        if dsym is not None:
            symbols.append(dsym)

        f = QFont(x.font_family)
        f.setPixelSize(max(8, int(x.w * 0.02)))
        p.setFont(f)
        r = max(5.0, min(12.0, x.w * 0.016))
        for color, lat, lon, wtype, label, ringed in symbols:
            c = x.to_screen(lat, lon)
            if not (-r < c.x() < x.w + r and -r < c.y() < x.h + r):
                continue
            self._draw_symbol(p, c, r, wtype, color)
            if ringed:
                ring_pen = QPen(ACTIVE)
                ring_pen.setWidthF(max(1.2, r * 0.18))
                p.setPen(ring_pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(c, r * 1.5, r * 1.5)
            if show_labels and label:
                p.setPen(QPen(color))
                p.drawText(QRectF(c.x() - 60, c.y() + r + 1, 120, f.pixelSize() + 4),
                           Qt.AlignmentFlag.AlignHCenter, label)

    @staticmethod
    def _draw_symbol(p, c, r, wtype, color):
        """Glyph by waypoint type, reusing the airports.py/navaids.py
        shape vocabulary (circle/hexagon/stippled-disc/triangle) but
        colored by route status (past/active/future) rather than navdata
        source, since this is showing plan status, not a navaid database."""
        pen = QPen(color)
        pen.setWidthF(max(1.2, r * 0.18))
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        if wtype == "vor":
            hexa = QPolygonF([
                QPointF(c.x() + r * math.cos(math.radians(a)),
                        c.y() + r * math.sin(math.radians(a)))
                for a in range(0, 360, 60)])
            p.drawPolygon(hexa)
            p.setBrush(QBrush(color))
            p.drawEllipse(c, r * 0.14, r * 0.14)
        elif wtype == "ndb":
            for ring, npts in ((r * 0.55, 8), (r, 12)):
                for i in range(npts):
                    ang = 2 * math.pi * i / npts
                    p.drawEllipse(QPointF(c.x() + ring * math.cos(ang),
                                          c.y() + ring * math.sin(ang)),
                                  r * 0.07, r * 0.07)
            p.setBrush(QBrush(color))
            p.drawEllipse(c, r * 0.14, r * 0.14)
        elif wtype == "fix":
            p.drawPolygon(QPolygonF([
                QPointF(c.x(), c.y() - r),
                QPointF(c.x() + r * 0.87, c.y() + r * 0.5),
                QPointF(c.x() - r * 0.87, c.y() + r * 0.5)]))
        elif wtype == "user":
            p.setBrush(QBrush(color))
            p.drawPolygon(QPolygonF([
                QPointF(c.x(), c.y() - r), QPointF(c.x() + r, c.y()),
                QPointF(c.x(), c.y() + r), QPointF(c.x() - r, c.y())]))
        elif wtype == "map":
            p.setBrush(QBrush(color))
            p.drawRect(QRectF(c.x() - r * 0.8, c.y() - r * 0.8, r * 1.6, r * 1.6))
        else:  # airport / unknown
            p.drawEllipse(c, r, r)
