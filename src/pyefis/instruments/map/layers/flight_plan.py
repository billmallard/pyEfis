#  SPDX-License-Identifier: GPL-2.0-or-later
#  Moving map flight_plan layer (spec 3.6, FP6, billmallard/pyEfis#184).
#
#  No worker, no database (like RangeRingsLayer): the route block,
#  active-leg state and direct-to point already live on the FIX bus (FP4
#  fixbridge.FixBridge). What collect() does is turn the route into leg
#  geometry, once per route commit (see PA8 below), so paint() never
#  tessellates.
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
#
#  RS4 (route segments brief section 7, pyEfis #307): the segment table on
#  the bus (FPLS*) labels each airway with its ident along its first leg,
#  and FPLACTSEG widens the rest of the active segment. Both read the
#  engine's own keys; the layer never works out a segment for itself. The
#  fixes and legs drawn are the same as before RS4.
#
#  PA8 (procedures brief section 3.6, pyEfis #239): procedure legs draw as
#  the path the engine flies -- arcs, a DF's coded turn, holds, procedure
#  turns, course legs -- from flightplan.leg_paths. The missed approach
#  segment (segment kind "missed") is dashed and vector legs are a dotted
#  "to be vectored" stub. Altitude constraints of procedure legs label the
#  fix in chart notation (a bar under the number for at-or-above, over it
#  for at-or-below). The geometry is built in collect() as lon/lat
#  polylines and painted through one affine transform taken from
#  MapTransform, so a frame costs no per-vertex Python.
#
#  Guardrail 1 on the map: a route the engine rejected draws nothing.
#  After a rejected commit the slots on the bus still hold the refused
#  route (the engine keeps flying the one it had), and only the engine
#  knows which route it loaded: FPLLDSEQ is the FPLSEQ of that route. When
#  the two differ, no leg, fix or label of the slots is drawn -- only the
#  active leg, from the engine's own FROM/TO outputs. A gateway without
#  FPLLDSEQ keeps the behaviour from before the key.

import math
import time

from PyQt6.QtCore import QObject, QPointF, QRectF, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QPen, QPolygonF, QTransform

from pyavtools import fix as pyavtools_fix

from pyefis.flightplan import fixbridge as fp_fixbridge
from pyefis.flightplan import geo as fp_geo
from pyefis.flightplan import leg_paths as fp_legs
from pyefis.flightplan.waypoints import WAYPOINT_TYPES, Waypoint
from pyefis.instruments.map.layers import MapLayer, hit_distance, register_layer

PAST = QColor("#808080")
ACTIVE = QColor("#ff00ff")
FUTURE = QColor("#ffffff")

_LEG_WIDTH = 2.0
_ACTIVE_WIDTH = 3.0
#: the legs still ahead in the active segment (FPLACTSEG). Width only, in
#: the leg's own colour: magenta stays reserved for the leg being flown.
_SEGMENT_WIDTH = 3.0

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

#: segment kinds whose legs come from a coded procedure: their altitude
#: constraints label the fix. An airway leg's FPLfALT is its MEA, which is
#: not a constraint at the fix, so airways are left out.
_PROCEDURE_KINDS = frozenset({"departure", "arrival", "approach", "missed"})

#: the active leg follows its drawn path only while the engine's FROM point
#: is where that path starts; otherwise (a direct-to into the leg's fix)
#: the engine flies FROM -> TO, and that is what is drawn.
_FROM_TOL_NM = 0.1

_STYLE_PEN = {"solid": Qt.PenStyle.SolidLine, "missed": Qt.PenStyle.DashLine,
              "vector": Qt.PenStyle.DotLine}


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


def _segment_span(route, k):
    """``(first, last)`` 1-based slots of segment *k* (1-based, as on the
    bus), or ``None`` when that row does not describe the slots: out of
    range, or a slot in its span whose ``FPLfSGI`` is not *k*. The engine
    rejects such a commit (RS1), so this only guards a torn read."""
    if not 1 <= k <= len(route.segments):
        return None
    row = route.segments[k - 1]
    slots = route.waypoints
    if not 1 <= row.first <= row.last <= len(slots):
        return None
    if any(slots[i - 1].sgi != k for i in range(row.first, row.last + 1)):
        return None
    return row.first, row.last


def build_airway_labels(route, engine):
    """``[(color, ident, (lat1, lon1), (lat2, lon2)), ...]``: one label per
    airway segment, placed on its first leg along the airway (entry fix to
    the next fix). The leg flown INTO the entry fix belongs to the airway
    segment on the bus (``FPLACTSEG``), but it is a direct leg, not the
    airway, so it does not carry the ident. ``color`` is that leg's
    past/active/future colour, so the label greys out with it."""
    slots = route.waypoints
    off_route = _off_route_direct(engine)
    act_leg = int(_engine_val(engine, "FPLACTLEG", 0) or 0)
    out = []
    for k, row in enumerate(route.segments, start=1):
        if row.kind != "airway" or not row.ident:
            continue
        span = _segment_span(route, k)
        if span is None or span[1] <= span[0]:
            continue
        a, b = slots[span[0] - 1], slots[span[0]]
        to_idx = span[0] + 1
        if off_route or (act_leg and to_idx < act_leg):
            color = PAST
        elif act_leg and to_idx == act_leg:
            color = ACTIVE
        else:
            color = FUTURE
        out.append((color, row.ident, (a.lat, a.lon), (b.lat, b.lon)))
    return out


def build_segment_emphasis(route, engine):
    """``[((lat1, lon1), (lat2, lon2)), ...]``: the legs still ahead in the
    active segment, drawn wider. The segment is ``FPLACTSEG`` (0, or the
    key absent, means none) and a leg belongs to the segment of its TO slot,
    the engine's own rule. The active leg is already magenta and wide, and
    past legs stay as they are, so only future legs are listed."""
    slots = route.waypoints
    # leg i (slots[i] -> slots[i+1]) has TO-slot number i + 2.
    return [((slots[to_idx - 2].lat, slots[to_idx - 2].lon),
             (slots[to_idx - 1].lat, slots[to_idx - 1].lon))
            for to_idx in _emphasis_slots(route, engine)]


def _emphasis_slots(route, engine):
    """TO-slot numbers of the legs :func:`build_segment_emphasis` lists."""
    k = int(_engine_val(engine, "FPLACTSEG", 0) or 0)
    if k <= 0 or _off_route_direct(engine):
        return []
    span = _segment_span(route, k)
    if span is None:
        return []
    act_leg = int(_engine_val(engine, "FPLACTLEG", 0) or 0)
    return list(range(max(span[0], act_leg + 1, 2), span[1] + 1))


def build_symbols(route, engine):
    """Pure per-slot symbol data: ``[(color, lat, lon, type, label,
    ringed), ...]``. ``ringed`` marks the current TO waypoint."""
    slots = route.waypoints
    off_route = _off_route_direct(engine)
    act_leg = int(_engine_val(engine, "FPLACTLEG", 0) or 0)
    out = []
    for i, wp in enumerate(slots):
        slot_idx = i + 1
        if wp.pt in fp_legs.NO_FIX_PTS:
            continue    # a CA's point is on its course line, not a fix
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


def route_loaded(route, engine):
    """False when the slots on the bus are not the route the engine has
    loaded: ``FPLLDSEQ`` (the ``FPLSEQ`` of the loaded route) differs from
    the route's ``FPLSEQ``, which after a rejected commit it does. True when
    the gateway does not publish ``FPLLDSEQ`` (the pre-key behaviour)."""
    item = engine.get("FPLLDSEQ")
    if item is None:
        return True
    try:
        return int(item.value) == int(route.seq)
    except (TypeError, ValueError):
        return False


def segment_kinds(route):
    """The segment kind of each slot (``FPLfSGI`` into the table), in slot
    order; ``"waypoint"`` where the table does not describe the slot."""
    out = []
    for k_slot, wp in enumerate(route.waypoints, start=1):
        kind = "waypoint"
        if 1 <= wp.sgi <= len(route.segments):
            row = route.segments[wp.sgi - 1]
            if row.first <= k_slot <= row.last:
                kind = row.kind
        out.append(kind)
    return out


def _leg_color(to_idx, act_leg, off_route):
    if off_route or (act_leg and to_idx < act_leg):
        return PAST
    if act_leg and to_idx == act_leg:
        return ACTIVE
    return FUTURE


def build_leg_draws(route, engine, paths, kinds=None):
    """What :meth:`FlightPlanLayer.paint` strokes for the route's legs, in
    order: ``[(color, width, style, ref), ...]``. ``style`` is ``solid``,
    ``missed`` (a leg into a slot of the missed approach segment) or
    ``vector``. ``ref`` is ``("path", k)`` or ``("pattern", k)`` -- leg *k*'s
    path or its hold/procedure-turn pattern from *paths*
    (:func:`flightplan.leg_paths.build_leg_paths`) -- or ``("line", (a, b))``
    for a straight line between two ``(lat, lon)`` points.

    Colours follow :func:`build_legs`. The active leg is drawn on its path
    while the engine's FROM point (``FPLFRLAT``/``LON``) is where the path
    starts; after a direct-to into its fix it is the straight FROM -> TO
    line the engine flies. Legs still ahead in the active segment are wider
    (:func:`build_segment_emphasis`)."""
    off_route = _off_route_direct(engine)
    act_leg = int(_engine_val(engine, "FPLACTLEG", 0) or 0)
    fr = (_engine_val(engine, "FPLFRLAT", 0.0) or 0.0, _engine_val(engine, "FPLFRLON", 0.0) or 0.0)
    to = (_engine_val(engine, "WPLAT", 0.0) or 0.0, _engine_val(engine, "WPLON", 0.0) or 0.0)
    kinds = kinds if kinds is not None else segment_kinds(route)
    wide = set(_emphasis_slots(route, engine))
    out = []
    if act_leg == 1 and not off_route:
        out.append((ACTIVE, _ACTIVE_WIDTH, "solid", ("line", (fr, to))))
    for k, leg in enumerate(paths):
        to_idx = leg.to_slot
        color = _leg_color(to_idx, act_leg, off_route)
        missed = 0 < to_idx <= len(kinds) and kinds[to_idx - 1] == "missed"
        style = "vector" if leg.vector else "missed" if missed else "solid"
        if color == ACTIVE:
            width = _ACTIVE_WIDTH
        elif to_idx in wide:
            width = _SEGMENT_WIDTH
        else:
            width = _LEG_WIDTH
        on_path = (leg.vector or len(leg.points) > 2) and \
            fp_geo.distance_nm(fr[0], fr[1], *leg.points[0]) <= _FROM_TOL_NM
        if color == ACTIVE and not on_path:
            out.append((color, width, style, ("line", (fr, to))))
        else:
            out.append((color, width, style, ("path", k)))
        if leg.pattern:
            out.append((color, width, style, ("pattern", k)))
    return out


def parse_alt_constraint(alt):
    """``FPLfALT`` (guide notation: ``"+3500"``, ``"-3500"``, ``"@3500"``,
    ``"B2900,4000"``) as chart lines, top to bottom: ``[(text, bar_over,
    bar_under), ...]``. At-or-above has a bar under the number, at-or-below
    a bar over it, "at" both; a window stacks its ceiling over its floor.
    ``[]`` for an empty or unreadable field."""
    alt = (alt or "").strip()
    try:
        if alt[:1] == "B":
            lo, hi = sorted(int(float(v)) for v in alt[1:].split(","))
            return [(str(hi), True, False), (str(lo), False, True)]
        if alt[:1] in "+-@":
            n = str(int(float(alt[1:])))
            return [(n, alt[0] in "-@", alt[0] in "+@")]
        if alt:
            return [(str(int(float(alt))), False, False)]
    except ValueError:
        pass
    return []


def build_constraint_labels(route, engine, kinds=None):
    """``[(color, lat, lon, lines), ...]``: the altitude constraint of each
    procedure leg's fix (:data:`_PROCEDURE_KINDS`), *lines* from
    :func:`parse_alt_constraint`, coloured like the fix's symbol."""
    kinds = kinds if kinds is not None else segment_kinds(route)
    colors = {(lat, lon): color for color, lat, lon, _t, _l, _r in build_symbols(route, engine)}
    out = []
    for i, wp in enumerate(route.waypoints):
        if wp.pt in fp_legs.NO_FIX_PTS or kinds[i] not in _PROCEDURE_KINDS:
            continue
        lines = parse_alt_constraint(wp.alt)
        if lines:
            out.append((colors.get((wp.lat, wp.lon), FUTURE), wp.lat, wp.lon, lines))
    return out


def lonlat_transform(x):
    """The painter transform taking ``(lon, lat)`` in degrees to screen
    pixels, exact for *x*: MapTransform's projection is affine in lon/lat
    (an equirectangular plane about ownship, then rotation and scale), so
    three projected points fix it. MapTransform stays the one owner of the
    projection; this only lets a polyline built once be painted through it
    with no per-vertex work."""
    o = x.to_screen(x.lat0, x.lon0)
    e = x.to_screen(x.lat0, x.lon0 + 1.0)
    n = x.to_screen(x.lat0 + 1.0, x.lon0)
    ex, ey = e.x() - o.x(), e.y() - o.y()
    nx, ny = n.x() - o.x(), n.y() - o.y()
    return QTransform(ex, ey, nx, ny,
                      o.x() - x.lon0 * ex - x.lat0 * nx,
                      o.y() - x.lon0 * ey - x.lat0 * ny)


def _polyline(points):
    return QPolygonF([QPointF(lon, lat) for lat, lon in points])


class _Snapshot:
    """What collect() leaves for paint(): the route as read at the commit,
    whether the engine loaded it, and its leg geometry as lon/lat
    polylines. Replaced whole, never mutated."""

    def __init__(self, key, route, loaded, paths, kinds):
        self.key = key
        self.route = route
        self.loaded = loaded
        self.paths = paths
        self.kinds = kinds
        self.polys = [_polyline(leg.points) for leg in paths]
        self.patterns = [_polyline(leg.pattern) if leg.pattern else None for leg in paths]


class _BridgeRelay(QObject):
    """Marshals a FixBridge listener callback onto the GUI thread (see the
    module docstring): ``owner`` is the MovingMap widget, so this relay
    lives on its thread; Qt auto-queues ``changed -> owner.update`` when
    ``changed`` is emitted from a foreign thread."""

    changed = pyqtSignal()

    def __init__(self, owner, on_change=None):
        super().__init__(owner)
        self._on_change = on_change
        self.changed.connect(self._deliver)
        self.changed.connect(owner.update)

    def on_bridge_change(self):
        self.changed.emit()

    @pyqtSlot()
    def _deliver(self):
        # On the GUI thread (this relay's affinity): the layer re-collects
        # here, between frames, never inside paint().
        if self._on_change is not None:
            self._on_change()


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
        self._snapshot = None

    def configure(self, owner):
        self._owner = owner
        self._bridge = fp_fixbridge.FixBridge(pyavtools_fix)
        if self._bridge.available:
            self._relay = _BridgeRelay(owner, self._collect_now)
            self._bridge.add_listener(self._relay.on_bridge_change)
            self.collect(None)

    def _collect_now(self):
        self.collect(None)

    def _route_key(self):
        get = self._bridge._get
        try:
            ld = get("FPLLDSEQ").value
        except KeyError:
            ld = None
        magvar = self._bridge.magvar_or_none()
        return (int(get("FPLSEQ").value), int(get("FPLCOUNT").value),
                int(get("FPLSEGCNT").value), ld,
                None if magvar is None else round(magvar, 1))

    def collect(self, xform):
        """Rebuild the leg geometry when the route, the loaded-route seq or
        the variation changed; otherwise keep the snapshot. Runs on every
        bus notification, so the no-change path is a handful of reads."""
        if self._bridge is None or not self._bridge.available:
            return
        key = self._route_key()
        if self._snapshot is not None and self._snapshot.key == key:
            return
        route = self._bridge.read_route()
        engine = self._bridge.read_engine()
        if route is None or engine is None:
            return
        loaded = route_loaded(route, engine)
        paths = fp_legs.build_leg_paths(route.waypoints, key[4] or 0.0) if loaded else []
        self._snapshot = _Snapshot(key, route, loaded, paths, segment_kinds(route))

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
        snap = self._snapshot
        engine = self._bridge.read_engine()
        if snap is None or engine is None:
            return
        route = snap.route
        dto = self._bridge.read_direct_to()

        pen = QPen()
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setCosmetic(True)
        if snap.loaded:
            draws = build_leg_draws(route, engine, snap.paths, snap.kinds)
        else:
            draws = self._unloaded_draws(engine)
        lonlat = lonlat_transform(x)
        for color, width, style, (kind, ref) in draws:
            pen.setColor(color)
            pen.setWidthF(width)
            pen.setStyle(_STYLE_PEN[style])
            p.setPen(pen)
            if kind == "line":
                (la1, lo1), (la2, lo2) = ref
                p.drawLine(x.to_screen(la1, lo1), x.to_screen(la2, lo2))
                continue
            poly = snap.polys[ref] if kind == "path" else snap.patterns[ref]
            p.save()
            p.setWorldTransform(lonlat, True)
            p.drawPolyline(poly)
            p.restore()
        pen.setStyle(Qt.PenStyle.SolidLine)

        direct = build_direct_to(route, engine, dto)
        if direct is not None:
            color, (la1, lo1), (la2, lo2) = direct
            pen.setColor(color)
            pen.setWidthF(_ACTIVE_WIDTH)
            p.setPen(pen)
            p.drawLine(x.to_screen(la1, lo1), x.to_screen(la2, lo2))

        if not snap.loaded:
            if dto is not None and _off_route_direct(engine) and x.range_nm <= _SYMBOL_RANGE:
                self._paint_symbols(p, x, [build_dto_symbol(route, engine, dto)],
                                    x.range_nm <= _IDENT_RANGE)
            return

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

        self._paint_symbols(p, x, symbols, show_labels)
        if show_labels:
            self._paint_constraints(p, x, build_constraint_labels(route, engine, snap.kinds))
            self._paint_airway_labels(p, x, build_airway_labels(route, engine))

    @staticmethod
    def _unloaded_draws(engine):
        """A route the engine rejected draws nothing of its own (module
        docstring): only the leg the engine is flying, FROM -> TO from its
        outputs, when one is active and on-route."""
        act_leg = int(_engine_val(engine, "FPLACTLEG", 0) or 0)
        fr = engine.get("FPLFRLAT")
        if act_leg <= 0 or _off_route_direct(engine) or fr is None or fr.fail:
            return []
        a = (fr.value or 0.0, _engine_val(engine, "FPLFRLON", 0.0) or 0.0)
        b = (_engine_val(engine, "WPLAT", 0.0) or 0.0, _engine_val(engine, "WPLON", 0.0) or 0.0)
        return [(ACTIVE, _ACTIVE_WIDTH, "solid", ("line", (a, b)))]

    def _paint_symbols(self, p, x, symbols, show_labels):
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
    def _paint_constraints(p, x, labels):
        """Each procedure fix's altitude constraint under its ident label,
        in chart notation (:func:`parse_alt_constraint`)."""
        if not labels:
            return
        f = QFont(x.font_family)
        f.setPixelSize(max(8, int(x.w * 0.02)))
        p.setFont(f)
        fm = QFontMetricsF(f)
        r = max(5.0, min(12.0, x.w * 0.016))
        line_h = f.pixelSize() + 4
        for color, lat, lon, lines in labels:
            c = x.to_screen(lat, lon)
            if not (-r < c.x() < x.w + r and -r < c.y() < x.h + r):
                continue
            pen = QPen(color)
            pen.setWidthF(1.0)
            p.setPen(pen)
            y = c.y() + r + 1 + line_h     # below the ident label
            for text, over, under in lines:
                p.drawText(QRectF(c.x() - 60, y, 120, line_h), Qt.AlignmentFlag.AlignHCenter, text)
                half = fm.horizontalAdvance(text) / 2.0
                top = y + (line_h - fm.height()) / 2.0
                if over:
                    p.drawLine(QPointF(c.x() - half, top), QPointF(c.x() + half, top))
                if under:
                    bot = top + fm.height()
                    p.drawLine(QPointF(c.x() - half, bot), QPointF(c.x() + half, bot))
                y += line_h

    @staticmethod
    def _paint_airway_labels(p, x, labels):
        """Each airway ident along its first leg: centred on the leg,
        rotated to it and kept upright, set just above the line. Skipped
        when the leg is too short on screen to hold the text, or its
        midpoint is off screen."""
        if not labels:
            return
        f = QFont(x.font_family)
        f.setPixelSize(max(8, int(x.w * 0.02)))
        f.setBold(True)
        p.setFont(f)
        fm = QFontMetricsF(f)
        for color, ident, (la1, lo1), (la2, lo2) in labels:
            a, b = x.to_screen(la1, lo1), x.to_screen(la2, lo2)
            dx, dy = b.x() - a.x(), b.y() - a.y()
            text_w = fm.horizontalAdvance(ident)
            if math.hypot(dx, dy) < text_w + 2 * fm.height():
                continue
            mx, my = (a.x() + b.x()) / 2, (a.y() + b.y()) / 2
            if not (0 <= mx <= x.w and 0 <= my <= x.h):
                continue
            ang = math.degrees(math.atan2(dy, dx))
            if ang > 90:
                ang -= 180
            elif ang <= -90:
                ang += 180
            p.save()
            p.translate(mx, my)
            p.rotate(ang)
            p.setPen(QPen(color))
            h = fm.height()
            p.drawText(QRectF(-text_w / 2 - 2, -h - _LEG_WIDTH, text_w + 4, h),
                       Qt.AlignmentFlag.AlignCenter, ident)
            p.restore()

    def hit(self, x, px, py, tol_px):
        """FP10: the plan's waypoint symbols within *tol_px* -- the only way
        to tap a user or map waypoint, which no database layer draws."""
        if self._bridge is None or not self._bridge.available \
                or x.range_nm > _SYMBOL_RANGE:
            return []
        snap = self._snapshot
        if snap is None or not snap.loaded:
            return []
        out = []
        for s in snap.route.waypoints:
            if s.pt in fp_legs.NO_FIX_PTS:
                continue
            d = hit_distance(x, s.lat, s.lon, px, py, tol_px)
            if d is not None and s.id:
                wtype = s.type if s.type in WAYPOINT_TYPES else "fix"
                out.append((d, Waypoint(id=s.id, type=wtype, lat=s.lat, lon=s.lon)))
        return out

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
