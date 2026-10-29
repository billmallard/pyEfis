#  SPDX-License-Identifier: GPL-2.0-or-later
#  Moving map instrument -- Phase A skeleton (docs/moving_map_spec.md).
#  Top-down view: MapTransform owns ALL world->screen math, layers from
#  the provider registry paint in z order, ownship rides a configurable
#  screen anchor. Plain QWidget/QPainter: renders offscreen, no GL.

import math
import time

from PyQt6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QPinchGesture, QWidget

import pyavtools.fix as fix

from pyefis import hmi
from pyefis.flightplan import fixbridge as fp_fixbridge
from pyefis.flightplan import geo as fp_geo
from pyefis.flightplan import model as fp_model
from pyefis.flightplan.waypoints import Waypoint
from pyefis.instruments.ai.camera import M_PER_DEG_LAT
from pyefis.instruments.map import layers as map_layers
from pyefis.instruments.map.perf import MapPerfStats
from pyefis.instruments.live_binding import LiveBind, LiveBindingMixin

NM_M = 1852.0

#: desktop-parity drag: degrees of map rotation per pixel of a modifier-drag.
_ROTATE_DEG_PER_PX = 0.5
#: a press/release with less than this much travel is a tap (-> select,
#: FP10), not a drag.
_TAP_PX = 4.0
#: gesture-settle debounce (MP1): render is deferred until this long after
#: the last gesture/wheel/drag event, so a continuous pinch/wheel/drag
#: coalesces into one worker render instead of one per event.
_SETTLE_MS = 150
#: FP10 (billmallard/pyEfis#186): a tap selects a painted object whose symbol
#: centre is within this many px (inclusive) -- touch-sized, ~3 mm on the
#: bench panels.
HIT_TOL_PX = 12.0
#: ident and type of a bare map point sent direct-to or inserted (guide 3-46).
MAPWPT_ID = "MAPWPT"
#: stacked-object chooser shows at most this many rows.
_CHOOSER_MAX = 6
#: how long a banner result ("DIRECT TO RZS", a rejection) stays on screen.
_TOAST_MS = 3000


def _wrap180(deg):
    """Normalise degrees to the half-open range (-180, 180]."""
    d = (float(deg) + 180.0) % 360.0 - 180.0
    return 180.0 if d == -180.0 else d


def _leg_distance_nm(a, b, lat, lon):
    """Distance from ``(lat, lon)`` to the great-circle leg a->b, clamped to
    the leg's ends: off either end it is the distance to that end.
    ``along_track_distance_nm`` is unsigned (an acos), so "behind the start"
    is tested separately: the point bears more than 90 deg off the leg."""
    to_a = fp_geo.distance_nm(lat, lon, a.lat, a.lon)
    leg = fp_geo.distance_nm(a.lat, a.lon, b.lat, b.lon)
    if leg <= 0.0 or to_a <= 0.0:
        return to_a
    off = math.radians(fp_geo.initial_bearing(a.lat, a.lon, lat, lon)
                       - fp_geo.initial_bearing(a.lat, a.lon, b.lat, b.lon))
    if math.cos(off) <= 0.0:
        return to_a
    try:
        atd = fp_geo.along_track_distance_nm(lat, lon, a.lat, a.lon, b.lat, b.lon)
    except ValueError:      # acos a hair past 1.0: the point is on the leg line
        atd = to_a
    if atd >= leg:
        return fp_geo.distance_nm(lat, lon, b.lat, b.lon)
    return abs(fp_geo.cross_track_nm(lat, lon, a.lat, a.lon, b.lat, b.lon))


def insert_index(waypoints, lat, lon):
    """FP10 banner Insert: the flat index to ``insert_before`` so the new
    waypoint splits the plan leg nearest ``(lat, lon)``, or None to append
    (a plan with no leg yet: empty, or one waypoint). Ties go to the earlier
    leg. A point beyond the last waypoint is nearest the last leg's end, so
    it lands before the destination, not after it -- extending the plan is
    the FPL page's Add Waypoint."""
    if len(waypoints) < 2:
        return None
    best_k, best_d = None, None
    for k in range(1, len(waypoints)):
        d = _leg_distance_nm(waypoints[k - 1], waypoints[k], lat, lon)
        if best_d is None or d < best_d:
            best_k, best_d = k, d
    return best_k


class MapTransform:
    """World (lat/lon) -> screen (px). Local azimuthal-equidistant about
    the ownship position; rotation = track when track_up. The ONE owner
    of projection math -- layers never do their own (spec section 3)."""

    def __init__(self, lat, lon, range_nm, rot_deg, w, h, anchor_frac,
                 font_family="DejaVu Sans Condensed"):
        self.lat0, self.lon0 = lat, lon
        self.range_nm = range_nm
        self.rot = math.radians(rot_deg)
        self.w, self.h = w, h
        self.cx = w / 2.0
        self.cy = h * (1.0 - anchor_frac)   # ownship anchor (% up from bottom)
        self.font_family = font_family
        # range_nm = ownship anchor -> top edge
        self._px_per_m = max(1.0, self.cy) / max(1.0, range_nm * NM_M)
        self._coslat = math.cos(math.radians(lat))
        # MP1: True while a gesture is live or its settle timer is running
        # (MovingMap.defer_render). Layers skip _request/collect while set
        # and keep blitting the last image scaled -- the settle debounce
        # that stops a pinch from churning the worker on every event.
        self.defer_render = False

    def nm_to_px(self, nm):
        return nm * NM_M * self._px_per_m

    def to_screen(self, lat, lon):
        de = (lon - self.lon0) * M_PER_DEG_LAT * self._coslat
        dn = (lat - self.lat0) * M_PER_DEG_LAT
        if self.rot:
            c, s = math.cos(self.rot), math.sin(self.rot)
            de, dn = de * c - dn * s, de * s + dn * c
        return QPointF(self.cx + de * self._px_per_m,
                       self.cy - dn * self._px_per_m)

    def to_world(self, x, y):
        """Inverse of :meth:`to_screen`: screen px -> ``(lat, lon)`` (FP10
        map pointer)."""
        de = (x - self.cx) / self._px_per_m
        dn = (self.cy - y) / self._px_per_m
        if self.rot:
            c, s = math.cos(self.rot), math.sin(self.rot)
            de, dn = de * c + dn * s, -de * s + dn * c
        return (self.lat0 + dn / M_PER_DEG_LAT,
                self.lon0 + de / (M_PER_DEG_LAT * self._coslat))


class MovingMap(LiveBindingMixin, QWidget):
    #: FP10: an FPLCMD rejection reason, queued from the FIX thread to the GUI.
    _ack_toast = pyqtSignal(str)

    def __init__(self, parent=None, font_family="DejaVu Sans Condensed"):
        super(MovingMap, self).__init__(parent)
        self.setStyleSheet("background: transparent; border: 0px")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # Touch input: pinch to zoom the range (two-finger drag to pan is Phase
        # 2). A single PinchGesture reports both scaleFactor and centerPoint, so
        # one handler covers both. Grab it unconditionally; the handler honours
        # the touch_gestures option (set later by the screenbuilder).
        self.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        self.grabGesture(Qt.GestureType.PinchGesture)
        self.font_family = font_family
        # Options (screenbuilder setattrs; defaults per the spec):
        self._range_nm = 10.0
        self.range_ladder = "2,5,10,20,40,80,160"
        self.orientation = "track_up"          # or "north_up"
        self.touch_gestures = True             # pinch-zoom / two-finger pan+rotate
        self.gesture_timeout = 30.0            # s before a pan/rotate re-locks
        # Pinch dead-band (#202/AER-1216): a zoom-only pinch must not also pan
        # or rotate the view. Rotation/pan each engage only after the
        # gesture's CUMULATIVE motion since it started crosses one of these
        # thresholds; below both, the pinch is zoom-only. Proposed defaults,
        # not measured -- judged on the glass per the bench process, same as
        # MP10c's 20 NM.
        self.pinch_rotate_threshold_deg = 15.0
        self.pinch_pan_threshold_px = 20.0
        self.ownship_position = 50             # percent up from bottom
        self.symbol_color = "yellow"
        self.layer_range_rings = True
        self.layer_terrain = True
        self.tile_path = ""                    # GLO-30/SRTM HGT tree
        self.terrain_mode = "relief"           # or "caution"
        self.water_db_path = ""                # water.sqlite (#91)
        self.water_max_vertices = 512          # per-polygon raster cap
        # MP5 (#98): numpy even-odd scanline fill is the default; "qt"
        # keeps the legacy QPointF/QPolygonF/drawPath path for one
        # release of A/B (brief map_gesture_perf_plan.md section 4).
        self.water_raster = "numpy"            # or "qt"
        # MP10c (#98): above this NOMINAL range the crisp WaterDB polygon
        # overlay is skipped in favour of the terrain pack's own .wmask
        # channel (one gather, already folded into the sampled elevation's
        # water flag) -- when the pack has no mask at the chosen level,
        # polygons still draw regardless of range (reader fallback). 20 NM
        # is a proposal from the brief's measurements, Bill-approved
        # 2026-09-06; if it reads coarse on the touchscreen the A/B is a
        # step of this item, not a reopened decision.
        self.water_polygon_max_nm = 20.0
        self.layer_roads = True
        self.highway_db_path = ""              # highways.sqlite (SVS pack)
        self.road_color = "#c0c0c0"
        self.layer_rivers = True
        self.river_db_path = ""                # rivers.sqlite (highways schema, #92)
        self.river_color = "#4a6d8c"
        self.layer_airports = True
        self.nasr_db_path = ""                 # NASR airports.sqlite
        self.layer_navaids = True
        self.layer_fixes = False
        self.layer_airways = False
        self.navaid_db_path = ""               # navaids.sqlite (Phase D)
        self.layer_flight_plan = True          # route/active-leg/direct-to (FP6)
        # Control-binding keys (control_bindings.md): when an <x>_key option
        # names a FIX key, a control (button/knob) drives that setting at
        # runtime. Empty = the setting stays a static config option.
        self.range_key = ""
        self.orientation_key = ""
        self._layers = []
        self._layers_built = False

        # --- decoupled view state (#99 pan / #111 rotate) --------------------
        # Manual view-centre offset from ownship (east/north metres) and a
        # manual rotation offset (degrees); all zero = locked to ownship. One
        # shared single-shot timer re-locks the view gesture_timeout seconds
        # after the last pan/rotate touch (full re-lock, decision C).
        self._pan_e = 0.0
        self._pan_n = 0.0
        self._rot_offset = 0.0
        self._drag_last = None          # desktop drag anchor (QPointF)
        self._drag_total = 0.0          # cumulative drag px (tap vs drag)
        self._revert_timer = QTimer(self)
        self._revert_timer.setSingleShot(True)
        self._revert_timer.timeout.connect(self.recenter)

        # --- gesture-phase gating + settle debounce (MP1) --------------------
        # A continuous pinch/wheel/drag turns every input event into a new
        # render key; the worker never gets to publish before the key moves
        # on again (brief map_gesture_perf_plan.md section 2, R2). While
        # _gesture_active or the settle timer is running, defer_render is
        # True and every layer skips _request/collect, blitting the stale
        # scaled image instead; the timer firing repaints once, after the
        # gesture settles, so exactly one render lands.
        self._gesture_active = False

        # --- pinch dead-band state (#202/AER-1216) ---------------------------
        # True from a PinchGesture's Started state through Finished/Canceled;
        # used both to gate the rotate/pan dead-band below and to suppress a
        # synthesized mouse drag arriving from the same two-finger touch (a
        # drag racing the pinch's own pan_by would double it -- unverified on
        # real hardware, see #202). accum_* track cumulative gesture motion
        # since the last reset (see _reset_pinch_deadband); *_engaged latches
        # True for the rest of the gesture once its threshold is crossed, so
        # a component that has engaged never re-arms mid-pinch.
        self._pinch_active = False
        self._pinch_rot_accum_deg = 0.0
        self._pinch_rot_engaged = False
        self._pinch_pan_accum_dx = 0.0
        self._pinch_pan_accum_dy = 0.0
        self._pinch_pan_engaged = False
        # range_nm as of this pinch's Started event (AER-1216 follow-up):
        # zoom is re-derived from this fixed baseline and Qt's cumulative
        # totalScaleFactor() on every event, rather than compounded onto
        # the already-zoomed range_nm via the per-event scaleFactor() delta
        # -- see _pinch_zoom for the (once-confused) distinction.
        self._pinch_zoom_baseline_nm = None

        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.timeout.connect(self.update)
        self._ack_toast.connect(self.show_toast)

        self._lat = self._lon = 0.0
        self._track = 0.0
        self._alt_ft = 0.0
        self._old = {}

        # --- map pointer + banner (FP10, billmallard/pyEfis#186) -------------
        # _pointer is None, or {"lat", "lon", "objects": [Waypoint],
        # "target": Waypoint | None, "choosing": bool, "elev_ft"}: target None
        # is a bare map point (MAPWPT). _ui_targets are this frame's banner /
        # chooser / CTR-chip tap rects, recorded during paint (the
        # flight_plan instrument's per-frame tap-target pattern).
        self._pointer = None
        self._ui_targets = []
        self._fp_bridge = None
        self._toast = ""
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self._clear_toast)
        # Frame clock (#89, mirrors the AI's P4 pattern): inputs only
        # store values; the clock repaints at a bounded rate and only
        # when the pose moved enough to change pixels. X-Plane/GPS can
        # deliver LAT/LONG/TRACKM/ALT at tens of Hz each -- routing
        # every update through QWidget.update() repainted the whole
        # map (rotated terrain blit included) at the data rate.
        self._frame_rate = 10.0
        # MP3: gesture-driven view changes (zoom_by/pan_by/rotate_by) also
        # route through this clock instead of calling update() per event --
        # a touch panel or a fast pinch can deliver 60-120 events/s, and the
        # gesture callers just flip this flag; the tick below repaints it at
        # most once per clock period. The clock itself runs faster
        # (gesture_frame_rate) while a gesture is live so panning/rotating
        # still feels responsive.
        self._gesture_frame_rate = 30.0
        self._frame_dirty = False
        self._frame_last_pose = None
        self._frame_timer = QTimer(self)
        self._frame_timer.timeout.connect(self._frame_tick)
        self._frame_timer.start(int(round(1000.0 / self._frame_rate)))

        # --- MP6 perf instrumentation (map_gesture_perf_plan.md section 4) --
        # MapPerfStats is always created (a few counters, cheap); the
        # GUI-thread probe timer only runs while map_perf_log or
        # map_perf_overlay is on (both default False -- no behaviour change
        # unless a screen opts in).
        self.perf = MapPerfStats()
        self._map_perf_log = False
        self._map_perf_overlay = False
        self._perf_last_gesture_ns = None
        self._perf_settle_pending = False

        for key, attr in (("LAT", "_lat"), ("LONG", "_lon"),
                          ("TRACKM", "_track"), ("ALT", "_alt_ft")):
            try:
                item = fix.db.get_item(key)
                item.valueChanged[float].connect(
                    lambda v, a=attr: setattr(self, a, v))
                item.oldChanged[bool].connect(
                    lambda o, k=key: (self._old.__setitem__(k, o),
                                      self.update()))
                setattr(self, attr, item.value)
                self._old[key] = item.old
            except KeyError:
                # Graceful missing-key pattern: run with what exists.
                self._old[key] = True

    # --- frame clock (#89) --------------------------------------------------
    @property
    def frame_rate(self):
        return self._frame_rate

    @frame_rate.setter
    def frame_rate(self, fps):
        """Screenbuilder option: map repaint clock in Hz (clamped 1-30)."""
        self._frame_rate = max(1.0, min(30.0, float(fps)))
        if not self._gesture_active:
            self._frame_timer.start(int(round(1000.0 / self._frame_rate)))

    @property
    def gesture_frame_rate(self):
        return self._gesture_frame_rate

    @gesture_frame_rate.setter
    def gesture_frame_rate(self, fps):
        """Screenbuilder option (MP3): frame-clock rate in Hz while a
        gesture is active (clamped 10-60); ``frame_rate`` applies the rest
        of the time."""
        self._gesture_frame_rate = max(10.0, min(60.0, float(fps)))
        if self._gesture_active:
            self._frame_timer.start(int(round(1000.0 / self._gesture_frame_rate)))

    # --- range: one write path (#202 requirement 3) --------------------------
    @property
    def range_nm(self):
        return self._range_nm

    @range_nm.setter
    def range_nm(self, nm):
        """The single range-write path: zoom_by, range_up/range_down and the
        future zoom rail (#205) all set range through this setter, which
        also pushes the nearest ladder index to range_key (MAPRANGE) when
        one is bound -- so a button/knob pressed after a free pinch always
        steps from the range actually on screen instead of a stale
        pre-gesture index. range_nm itself stays exactly what the caller
        set (Bill, AER-1216 2026-09-15: a pinch must feel continuous, so a
        bound range_key must not write itself back onto range_nm -- see
        LiveBindingMixin._live_writeback)."""
        try:
            self._range_nm = float(nm)
        except (TypeError, ValueError):
            return
        b, item = self._live_bind_and_item("range_nm")
        if item is None:
            return
        idx = self._current_index(b)
        if idx is None:
            return
        self._live_writeback("range_nm", item, idx)

    def _set_gesture_active(self, active):
        """(De)activate the gesture phase and switch the frame clock
        between ``gesture_frame_rate`` (a gesture is live) and
        ``frame_rate`` (MP3) -- the clock is what actually repaints while
        zoom_by/pan_by/rotate_by only mark a frame dirty.

        AER-1216 follow-up (Bill, 2026-09-16 -- "the screen redraw is so
        slow the visual feedback doesn't match what command it's
        receiving"): ``_gesture_phase`` calls this on EVERY GestureUpdated
        event, not just the transition into/out of a gesture. QTimer.start()
        on an already-running timer resets its countdown to a full interval
        (Qt semantics), so calling it unconditionally here meant a real
        pinch -- which reports events faster than the ~33 ms gesture tick --
        perpetually restarted the clock before it could ever fire: input
        was applied instantly but the screen only repainted during a gap
        between touch events wider than one tick. Only touch the timer on
        an actual active/inactive transition; once running at the right
        rate it free-runs on its own."""
        if active == self._gesture_active:
            return
        self._gesture_active = active
        hz = self._gesture_frame_rate if active else self._frame_rate
        self._frame_timer.start(int(round(1000.0 / hz)))

    # --- MP6 perf instrumentation -------------------------------------------
    @property
    def map_perf_log(self):
        return self._map_perf_log

    @map_perf_log.setter
    def map_perf_log(self, on):
        """Screenbuilder option: print a MapPerfStats summary every 2s
        (mirrors ``svs_perf_log``). Default False."""
        self._map_perf_log = bool(on)
        self._sync_perf_probe()

    @property
    def map_perf_overlay(self):
        return self._map_perf_overlay

    @map_perf_overlay.setter
    def map_perf_overlay(self, on):
        """Screenbuilder option: draw a small on-screen stats chip (dev
        only). Default False."""
        self._map_perf_overlay = bool(on)
        self._sync_perf_probe()

    def _sync_perf_probe(self):
        """The GUI-thread responsiveness probe (brief section 4) only
        needs to run while its numbers are actually consumed -- start/stop
        it as map_perf_log/map_perf_overlay are (de)activated so a screen
        that never opts in pays nothing."""
        want = bool(self._map_perf_log or self._map_perf_overlay)
        if want and not self.perf.probe.running:
            self.perf.probe.start(self)
        elif not want and self.perf.probe.running:
            self.perf.probe.stop()

    def _perf_mark_gesture_event(self):
        """Settle latency (brief section 4) = last gesture/pan/zoom/rotate
        event -> first paint where every enabled layer's cached render
        matches the current transform. Called from the same three entry
        points MP3 routes through the frame clock."""
        self._perf_last_gesture_ns = time.perf_counter_ns()
        self._perf_settle_pending = True

    @property
    def defer_render(self):
        """True while a gesture is live or its settle timer is still
        running -- layers read this off the MapTransform (below) rather
        than reaching back into the widget."""
        return self._gesture_active or self._settle_timer.isActive()

    def _frame_tick(self):
        """Repaint at most at the clock rate, and only when the pose
        changed enough to move pixels: position by ~half a screen px,
        track by 0.25 deg (rotation), altitude by 100 ft (caution tint),
        or a gesture call (zoom_by/pan_by/rotate_by, MP3) marked a frame
        dirty. Explicit UI actions (range, orientation, layer toggles)
        and async layer completions still call update() directly."""
        if not self.isVisible():
            return
        m_per_px = (float(self.range_nm) * NM_M) / max(1.0, self.height() / 2.0)
        q = max(1e-7, (0.5 * m_per_px) / M_PER_DEG_LAT)  # deg per half-px
        pose = (round(self._lat / q), round(self._lon / q),
                round(self._track * 4.0), round(self._alt_ft / 100.0),
                self.orientation, float(self.range_nm),
                round(self._pan_e), round(self._pan_n),
                round(self._rot_offset * 4.0))
        if pose == self._frame_last_pose and not self._frame_dirty:
            return
        self._frame_last_pose = pose
        self._frame_dirty = False
        self.update()

    # --- layer plumbing ---------------------------------------------------
    def _build_layers(self):
        from pyefis.instruments.map.layers import airports  # noqa: F401
        from pyefis.instruments.map.layers import flight_plan  # noqa: F401
        from pyefis.instruments.map.layers import navaids  # noqa: F401
        from pyefis.instruments.map.layers import rivers  # noqa: F401
        from pyefis.instruments.map.layers import roads  # noqa: F401
        from pyefis.instruments.map.layers import terrain  # noqa: F401
        self._layers = []
        for lid, cls in sorted(map_layers.LAYER_REGISTRY.items(),
                               key=lambda kv: kv[1].z):
            layer = cls()
            layer.enabled = bool(getattr(self, "layer_" + lid,
                                         cls.default_on))
            layer.configure(self)
            self._layers.append(layer)
        self._layers_built = True

    def set_layer(self, layer_id, on=None):
        """HMI hook: toggle (or set) a layer at runtime."""
        for layer in self._layers:
            if layer.id == layer_id:
                layer.on_toggle((not layer.enabled) if on is None else on)
                self.update()
                return True
        return False

    # --- HMI hooks (bound to buttons/encoder in screen YAML later) --------
    def _ladder(self):
        try:
            vals = [float(v) for v in str(self.range_ladder).split(",") if v]
            return vals or [10.0]
        except ValueError:
            return [10.0]

    def range_up(self):
        lad = self._ladder()
        self.range_nm = next((v for v in lad if v > self.range_nm), lad[-1])
        self.update()

    def range_down(self):
        lad = self._ladder()
        self.range_nm = next((v for v in reversed(lad)
                              if v < self.range_nm), lad[0])
        self.update()

    def _live_binding_specs(self):
        """Runtime control bindings (control_bindings.md). Each fires only if its
        ``<x>_key`` option names a FIX key; otherwise the setting stays static.
        range = index over the ladder, orientation = enum index -- both plain
        attributes the frame timer already polls, so applying them from the
        (non-GUI) FIX thread is safe.

        Layer bindings (e.g. terrain via set_layer) are DEFERRED: toggling a live
        layer is a Qt call that must run on the GUI thread, which needs marshaling
        the FIX callback across threads. See control_bindings.md / #96."""
        return [
            LiveBind("range_nm", "index_ladder", "range_key",
                     ladder_option="range_ladder"),
            LiveBind("orientation", "enum", "orientation_key",
                     enum=("track_up", "north_up")),
        ]

    def toggle_orientation(self):
        self.orientation = ("north_up" if self.orientation == "track_up"
                            else "track_up")
        self.update()

    # --- touch / pointer zoom ---------------------------------------------
    def _range_bounds(self):
        lad = self._ladder()
        return min(lad), max(lad)

    def zoom_by(self, factor):
        """Scale the view continuously by ``factor`` (>1 = zoom IN = smaller
        ``range_nm``) applied as a DELTA against the current range_nm --
        correct for wheel-up (each notch is its own independent step) and
        the future zoom rail (#205). Pinch does NOT use this: it needs the
        gesture's cumulative-since-start scale (Qt's ``totalScaleFactor()``,
        NOT ``scaleFactor()`` -- see _pinch_zoom for the distinction, which
        AER-1216 got backwards once already), re-derived from a fixed
        per-gesture baseline rather than compounded per event.
        Clamped to the range-ladder span; ``range_up``/``range_down`` still
        do the discrete button/knob stepping. Returns the new range.

        MP3: marks a frame dirty instead of calling update() directly -- a
        fast wheel can call this tens of times a second; the frame clock
        (_frame_tick) is what actually repaints, at most once per clock
        period."""
        try:
            factor = float(factor)
        except (TypeError, ValueError):
            return self.range_nm
        if factor <= 0.0:
            return self.range_nm
        lo, hi = self._range_bounds()
        self.range_nm = max(lo, min(hi, float(self.range_nm) / factor))
        self._frame_dirty = True
        self._perf_mark_gesture_event()
        return self.range_nm

    # --- decoupled pan / rotate (#99 / #111) ------------------------------
    @property
    def is_offset(self):
        """True while the view is manually panned or rotated off ownship."""
        return bool(self._pan_e or self._pan_n or self._rot_offset)

    def _restart_revert_timer(self):
        """(Re)start the single shared last-touch timer; ``gesture_timeout``=0
        disables auto-revert (the view stays where left until a double-tap,
        the CTR chip or an HMI recenter)."""
        try:
            secs = float(self.gesture_timeout)
        except (TypeError, ValueError):
            secs = 30.0
        if secs > 0.0:
            self._revert_timer.start(int(secs * 1000.0))
        elif self._revert_timer.isActive():
            self._revert_timer.stop()

    def pan_by(self, dx, dy):
        """Shift the manual view-centre offset by a screen-space drag of
        ``(dx, dy)`` pixels (two-finger drag / left-drag), decoupling the view
        from ownship. The screen delta is un-rotated into world ENU (#99's
        track-up rule) and stored as an east/north metre offset, so the panned
        point stays geographically fixed as the aircraft turns. Content follows
        the finger. (Re)starts the auto-revert timer. Returns ``(pan_e,
        pan_n)``."""
        try:
            dx = float(dx)
            dy = float(dy)
        except (TypeError, ValueError):
            return (self._pan_e, self._pan_n)
        if dx == 0.0 and dy == 0.0:
            return (self._pan_e, self._pan_n)
        anchor = max(0.0, min(100.0, float(self.ownship_position))) / 100.0
        cy = max(1.0, (self.height() or 1) * (1.0 - anchor))
        px = cy / max(1.0, float(self.range_nm) * NM_M)     # screen px / metre
        track = self._track if self.orientation == "track_up" else 0.0
        rot = math.radians(track + self._rot_offset)
        c, s = math.cos(rot), math.sin(rot)
        # View centre moves opposite the finger drag, un-rotated to world ENU.
        self._pan_e += (-dx * c + dy * s) / px
        self._pan_n += (dx * s + dy * c) / px
        self._restart_revert_timer()
        self._frame_dirty = True   # MP3: repaint via the frame clock
        self._perf_mark_gesture_event()
        return (self._pan_e, self._pan_n)

    def rotate_by(self, deg):
        """Rotate the map by a manual offset on top of the configured
        orientation (two-finger rotate / modifier-drag). (Re)starts the
        auto-revert timer. Returns the new rotation offset in degrees."""
        try:
            deg = float(deg)
        except (TypeError, ValueError):
            return self._rot_offset
        if deg == 0.0:
            return self._rot_offset
        self._rot_offset = _wrap180(self._rot_offset + deg)
        self._restart_revert_timer()
        self._frame_dirty = True   # MP3: repaint via the frame clock
        self._perf_mark_gesture_event()
        return self._rot_offset

    def recenter(self):
        """Re-lock the view to ownship: clear the pan offset AND the rotation
        offset (full re-lock, decision C) and stop the auto-revert timer. Safe
        to call any time -- a double-tap, the CTR chip, an HMI action, or the
        timer firing."""
        changed = self.is_offset
        self._pan_e = self._pan_n = 0.0
        self._rot_offset = 0.0
        if self._revert_timer.isActive():
            self._revert_timer.stop()
        if changed:
            self.update()

    # --- map pointer, hit-test and banner (FP10, billmallard/pyEfis#186) ---
    def hit_test(self, x, y, tol_px=HIT_TOL_PX):
        """Every painted object within *tol_px* of screen ``(x, y)``, nearest
        first, one entry per ``(ident, type)`` (an airport the flight_plan
        layer also draws is listed once). Only enabled layers answer, and
        each answers only for what it paints."""
        if not self._layers_built:
            return []
        xf = self._transform()
        found = {}
        for layer in self._layers:
            if not layer.enabled:
                continue
            try:
                hits = layer.hit(xf, x, y, tol_px)
            except Exception:
                import logging
                logging.getLogger(__name__).exception(
                    "map %s hit-test failed", layer.id)
                continue
            for d, wp in hits:
                key = (wp.id, wp.type)
                if key not in found or d < found[key][0]:
                    found[key] = (d, wp)
        return [wp for _d, wp in sorted(found.values(), key=lambda t: t[0])]

    @property
    def pointer(self):
        """The live map pointer state (see ``__init__``), or None."""
        return self._pointer

    def _terrain_elevation_ft(self, lat, lon):
        for layer in self._layers:
            if layer.enabled and hasattr(layer, "elevation_ft"):
                return layer.elevation_ft(lat, lon)
        return None

    def place_pointer(self, x, y):
        """A tap at screen ``(x, y)`` with no pointer up: one object in reach
        -> its banner; several -> the stacked chooser; none -> a bare map
        point there."""
        objs = self.hit_test(x, y)
        if objs and len(objs) == 1:
            lat, lon = objs[0].lat, objs[0].lon
        else:
            lat, lon = self._transform().to_world(x, y)
        self._pointer = {"lat": lat, "lon": lon, "objects": objs,
                         "target": objs[0] if len(objs) == 1 else None,
                         "choosing": len(objs) > 1, "elev_ft": None}
        if len(objs) <= 1:
            self._pointer["elev_ft"] = self._terrain_elevation_ft(lat, lon)
        self.update()
        return self._pointer

    def choose(self, wp):
        """Stacked chooser pick: the banner now acts on *wp*."""
        if self._pointer is None:
            return
        self._pointer.update(target=wp, choosing=False, lat=wp.lat, lon=wp.lon,
                             elev_ft=self._terrain_elevation_ft(wp.lat, wp.lon))
        self.update()

    def clear_pointer(self):
        if self._pointer is not None:
            self._pointer = None
            self.update()

    def pointer_waypoint(self):
        """What the banner acts on: the chosen object, or a ``MAPWPT`` map
        point (type ``map``) at the pointer."""
        p = self._pointer
        if p is None or p["choosing"]:
            return None
        if p["target"] is not None:
            return p["target"]
        return Waypoint(id=MAPWPT_ID, type="map", lat=p["lat"], lon=p["lon"])

    def _flightplan_bridge(self):
        """Lazily built: the map only needs the bus on a banner action."""
        if self._fp_bridge is None:
            self._fp_bridge = fp_fixbridge.FixBridge(fix)
        return self._fp_bridge if self._fp_bridge.available else None

    def show_toast(self, text):
        self._toast = str(text or "")
        if self._toast:
            self._toast_timer.start(_TOAST_MS)
        self.update()

    def _clear_toast(self):
        self._toast = ""
        self.update()

    def _ack_handler(self, done_text):
        """An ``FPLCMDACK`` callback that toasts *done_text* on success and
        the engine's ``FPLMSG`` on rejection -- the banner reports what the
        engine did, not what was asked. The ack arrives on the FIX client
        thread; the signal queues the toast onto the GUI thread."""
        def on_ack(_seq, ok, msg):
            self._ack_toast.emit(done_text if ok else "REJECTED: %s" % (msg or "?"))
        return on_ack

    def banner_direct_to(self):
        """Stage ``DTO*`` for the object (or ``MAPWPT`` at the pointer) and
        issue ``DTO``. A plan waypoint is matched to its slot by the engine
        (Appendix C: ident and position within 0.001 deg)."""
        wp = self.pointer_waypoint()
        if wp is None:
            return
        bridge = self._flightplan_bridge()
        if bridge is None:
            self.show_toast("NO FLIGHT PLAN")
            return
        bridge.stage_direct_to(wp)
        bridge.command("DTO", on_ack=self._ack_handler("DIRECT TO %s" % wp.id))
        self.clear_pointer()

    def banner_insert(self):
        """Insert into the plan on the bus at the leg nearest the pointer
        (append when it has no leg yet) and publish -- every flight_plan
        instrument re-reads it on ``FPLSEQ``."""
        wp = self.pointer_waypoint()
        if wp is None:
            return
        bridge = self._flightplan_bridge()
        if bridge is None:
            self.show_toast("NO FLIGHT PLAN")
            return
        plan = bridge.read_plan()
        new = fp_model.Waypoint(id=wp.id, type=wp.type, lat=wp.lat, lon=wp.lon,
                                name=wp.name or "")
        p = self._pointer
        idx = insert_index(plan.waypoints, p["lat"], p["lon"])
        try:
            if idx is None:
                plan.insert_after(plan.count - 1, new)
            else:
                plan.insert_before(idx, new)
        except fp_model.FlightPlanError as e:
            self.show_toast(str(e))
            return
        bridge.publish(plan)
        self.clear_pointer()
        self.show_toast("INSERTED %s" % wp.id)

    def banner_create_wpt(self):
        """Open the flight_plan instrument's user-waypoint form, prefilled
        with the pointer position."""
        p = self._pointer
        if p is None:
            return
        if hmi.actions is not None:
            hmi.actions.flightplanCreateWaypoint.emit((p["lat"], p["lon"]))
        self.clear_pointer()

    def banner_info(self):
        """WPT Info for the object (or the map point) on the flight_plan
        instrument."""
        wp = self.pointer_waypoint()
        if wp is None:
            return
        if hmi.actions is not None:
            hmi.actions.flightplanWptInfo.emit(wp)
        self.clear_pointer()

    def _on_tap(self, x, y):
        """A tap (press/release under ``_TAP_PX`` of travel): a banner,
        chooser or CTR-chip control under the finger runs; otherwise a live
        pointer is cleared (a second tap away), else a pointer is placed."""
        for rect, cb in reversed(self._ui_targets):
            if rect.contains(QPointF(x, y)):
                cb()
                return
        if self._pointer is not None:
            self.clear_pointer()
            return
        self.place_pointer(x, y)

    def _gesture_phase(self, state):
        """(Re)arm the settle debounce off a QGesture's state (MP1). Fake
        gesture objects in tests that don't implement ``state()`` are
        treated as phase-less: they exercise the touch math without
        engaging the gating.

        #202/AER-1216: also brackets ``_pinch_active`` (Started..Finished/
        Canceled), resetting the rotate/pan dead-band on a fresh gesture.
        Range does NOT snap when the gesture ends (Bill, 2026-09-15: pinch
        zoom must feel continuous end to end) -- range_nm stays exactly
        where the fingers left it; only its on-screen display rounds."""
        GS = Qt.GestureState
        if state in (GS.GestureStarted, GS.GestureUpdated):
            if not self._pinch_active:
                self._reset_pinch_deadband()
                self._drag_last = None   # a pinch kills any in-flight synthesized drag
            self._pinch_active = True
            self._set_gesture_active(True)
        elif state in (GS.GestureFinished, GS.GestureCanceled):
            self._pinch_active = False
            self._set_gesture_active(False)
            self._settle_timer.start(_SETTLE_MS)

    def _reset_pinch_deadband(self):
        """New pinch: clear the cumulative rotate/pan motion and un-latch
        both components (#202), and capture the range_nm this pinch's zoom
        will be computed from (see _pinch_zoom)."""
        self._pinch_rot_accum_deg = 0.0
        self._pinch_rot_engaged = False
        self._pinch_pan_accum_dx = 0.0
        self._pinch_pan_accum_dy = 0.0
        self._pinch_pan_engaged = False
        self._pinch_zoom_baseline_nm = self.range_nm

    def _pinch_rotate_threshold_deg(self):
        try:
            return max(0.0, float(self.pinch_rotate_threshold_deg))
        except (TypeError, ValueError):
            return 15.0

    def _pinch_pan_threshold_px(self):
        try:
            return max(0.0, float(self.pinch_pan_threshold_px))
        except (TypeError, ValueError):
            return 20.0

    def _pinch_rotate(self, deg):
        """Dead-band gate on cumulative twist since this pinch started
        (#202): below ``pinch_rotate_threshold_deg`` a pinch must not rotate
        the view at all, so a couple of degrees of finger wobble during a
        zoom-only pinch raises no CTR chip. Once the accumulated twist
        crosses the threshold, the WHOLE accumulated rotation is applied in
        one step (so no motion is lost at the crossing) and the component
        latches engaged for the rest of the gesture."""
        self._pinch_rot_accum_deg += deg
        if self._pinch_rot_engaged:
            self.rotate_by(deg)
            return
        if abs(self._pinch_rot_accum_deg) >= self._pinch_rotate_threshold_deg():
            self._pinch_rot_engaged = True
            self.rotate_by(self._pinch_rot_accum_deg)

    def _pinch_pan(self, dx, dy):
        """Same dead-band shape as :meth:`_pinch_rotate`, gated on the
        centroid's cumulative displacement from where this pinch started
        (#202) rather than any single event's delta -- a slow drift must
        still engage once it adds up, even though no one event crosses the
        threshold on its own."""
        self._pinch_pan_accum_dx += dx
        self._pinch_pan_accum_dy += dy
        if self._pinch_pan_engaged:
            self.pan_by(dx, dy)
            return
        dist = math.hypot(self._pinch_pan_accum_dx, self._pinch_pan_accum_dy)
        if dist >= self._pinch_pan_threshold_px():
            self._pinch_pan_engaged = True
            self.pan_by(self._pinch_pan_accum_dx, self._pinch_pan_accum_dy)

    def _pinch_zoom(self, total_scale_factor):
        """AER-1216 follow-up correction: the FIRST attempt at this fix
        (37a6e99) misread Qt's own semantics and fed this ``g.scaleFactor()``
        -- confirmed backwards against Qt's actual recognizer source
        (qtbase qstandardgestures.cpp): ``d->scaleFactor = line.length() /
        lastLine.length()`` is the DELTA since the *last* event, while
        ``d->totalScaleFactor = d->totalScaleFactor * d->scaleFactor`` is the
        cumulative product since the gesture STARTED -- i.e. scaleFactor()
        and totalScaleFactor() have exactly the opposite meaning from what
        37a6e99 assumed. Feeding the tiny near-1.0 per-event delta into this
        baseline-relative formula made a real pinch's zoom nearly inert --
        confirmed by driving a synthesized 2x pinch through this formula
        with only the per-event delta available: range_nm moved from 10.0
        to 9.99, not 5.0. The caller MUST pass ``g.totalScaleFactor()``.
        Re-deriving range_nm from this pinch's
        fixed start-of-gesture baseline on every event -- instead of calling
        zoom_by() per event, which would compound the per-event deltas onto
        the ALREADY-zoomed range_nm -- is mathematically equivalent (total
        scale is exactly the product of the per-event deltas) but immune to
        floating-point drift over a long, finely-sampled gesture."""
        try:
            factor = float(total_scale_factor)
        except (TypeError, ValueError):
            return
        if factor <= 0.0 or self._pinch_zoom_baseline_nm is None:
            return
        lo, hi = self._range_bounds()
        self.range_nm = max(lo, min(hi, self._pinch_zoom_baseline_nm / factor))
        self._frame_dirty = True
        self._perf_mark_gesture_event()

    def event(self, e):
        if (e.type() == QEvent.Type.Gesture
                and getattr(self, "touch_gestures", True)):
            g = e.gesture(Qt.GestureType.PinchGesture)
            if g is not None:
                state_fn = getattr(g, "state", None)
                if state_fn is not None:
                    self._gesture_phase(state_fn())
                flags = g.changeFlags()
                CF = QPinchGesture.ChangeFlag
                if flags & CF.ScaleFactorChanged:
                    self._pinch_zoom(g.totalScaleFactor())
                if flags & CF.CenterPointChanged:
                    d = g.centerPoint() - g.lastCenterPoint()
                    self._pinch_pan(d.x(), d.y())
                if flags & CF.RotationAngleChanged:
                    # Negate: a positive _rot_offset rotates the map content
                    # counter-clockwise (see MapTransform.to_screen), so the raw
                    # pinch delta must be inverted for the map to FOLLOW the
                    # fingers -- clockwise twist -> clockwise map (#114).
                    self._pinch_rotate(-(g.rotationAngle() - g.lastRotationAngle()))
                return True
        return super().event(e)

    # --- desktop parity: drag = pan, modifier-drag = rotate, tap = select
    def mousePressEvent(self, e):
        if self._pinch_active:
            # A synthesized mouse press from the same two fingers driving an
            # active pinch must not also start a competing drag (#202,
            # unverified on real touch hardware).
            return
        if (getattr(self, "touch_gestures", True)
                and e.button() == Qt.MouseButton.LeftButton):
            self._drag_last = e.position()
            self._drag_total = 0.0
            self._set_gesture_active(True)   # brackets the drag path (MP1)
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag_last is None or not getattr(self, "touch_gestures", True):
            super().mouseMoveEvent(e)
            return
        pos = e.position()
        d = pos - self._drag_last
        self._drag_last = pos
        self._drag_total += math.hypot(d.x(), d.y())
        if e.modifiers() & (Qt.KeyboardModifier.ShiftModifier
                            | Qt.KeyboardModifier.ControlModifier):
            # Same convention as the touch path (#114): negate so drag-right
            # rotates the map clockwise -- content follows the gesture.
            self.rotate_by(-d.x() * _ROTATE_DEG_PER_PX)
        else:
            self.pan_by(d.x(), d.y())
        e.accept()

    def mouseReleaseEvent(self, e):
        if self._drag_last is not None:
            tap = self._drag_total < _TAP_PX
            self._drag_last = None
            self._set_gesture_active(False)
            self._settle_timer.start(_SETTLE_MS)
            if tap:
                # FP10: a tap selects (map pointer / banner). Recenter is the
                # double-tap or the CTR chip.
                pos = e.position()
                self._on_tap(pos.x(), pos.y())
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        """Double-tap = recenter (FP10 moved it off the single tap). The
        first tap of the pair has already placed a pointer; drop it."""
        if getattr(self, "touch_gestures", True):
            self.clear_pointer()
            self.recenter()
            e.accept()
            return
        super().mouseDoubleClickEvent(e)

    def wheelEvent(self, e):
        """Desktop / configurator zoom, mirroring pinch (wheel-up = zoom in).
        One notch (120 eighths-of-a-degree) = 1.25x."""
        if getattr(self, "touch_gestures", True):
            dy = e.angleDelta().y()
            if dy:
                self._settle_timer.start(_SETTLE_MS)   # (re)start (MP1)
                self.zoom_by(1.25 ** (dy / 120.0))
        e.accept()

    # --- painting ----------------------------------------------------------
    def _transform(self):
        track = self._track if self.orientation == "track_up" else 0.0
        rot = track + self._rot_offset
        anchor = max(0.0, min(100.0,
                              float(self.ownship_position))) / 100.0
        # View centre = ownship + the manual pan offset (east/north metres).
        # Feeding the OFFSET centre as the transform origin keeps every layer
        # (terrain image, vector features, rings) registered to it for free;
        # ownship then projects to its own off-centre position in paintEvent.
        coslat = math.cos(math.radians(self._lat)) or 1e-6
        vlat = self._lat + self._pan_n / M_PER_DEG_LAT
        vlon = self._lon + self._pan_e / (M_PER_DEG_LAT * coslat)
        x = MapTransform(vlat, vlon, float(self.range_nm),
                         rot, self.width(), self.height(), anchor,
                         self.font_family)
        x.defer_render = self.defer_render
        return x

    def paintEvent(self, event):
        _perf_t0 = time.perf_counter()
        if not self._layers_built:
            self._build_layers()
            # Options are applied by now; wire runtime control bindings once, but
            # DEFER out of the paint. Binding init writes the seed values (FIX
            # emissions) and can touch layers; doing that inside paintEvent risks
            # re-entering the painter. singleShot(0) runs it after this paint.
            QTimer.singleShot(0, self._init_live_bindings_once)
        self._ui_targets = []
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(16, 24, 32))
        x = self._transform()
        for layer in self._layers:
            if layer.enabled:
                p.save()
                layer.paint(p, x)
                p.restore()

        # Ownship: top-down aircraft arrow at the anchor, up = track
        # (track_up) or rotated to track (north_up).
        stale = self._old.get("LAT", True) or self._old.get("LONG", True)
        col = QColor(Qt.GlobalColor.gray) if stale \
            else QColor(self.symbol_color)
        if not col.isValid():
            col = QColor(Qt.GlobalColor.yellow)
        s = max(8.0, self.width() * 0.025)
        osp = x.to_screen(self._lat, self._lon)   # off-centre when panned
        p.save()
        p.translate(osp.x(), osp.y())
        # Nose points along the ground track as it lands on screen: 0 in the
        # locked track-up case, self._track in locked north-up, and correct
        # under a manual rotation offset (track minus the screen rotation).
        p.rotate(self._track - math.degrees(x.rot))
        p.setPen(QPen(QColor(Qt.GlobalColor.black), 1))
        p.setBrush(QBrush(col))
        p.drawPolygon(QPolygonF([
            QPointF(0, -s), QPointF(s * 0.6, s * 0.8),
            QPointF(0, s * 0.35), QPointF(-s * 0.6, s * 0.8)]))
        p.restore()

        # Status chip: range + orientation (+ NO POS when stale).
        f = QFont(self.font_family)
        f.setPixelSize(max(9, int(self.width() * 0.03)))
        p.setFont(f)
        p.setPen(QPen(QColor(255, 255, 255, 200)))
        mode = "TRK UP" if self.orientation == "track_up" else "NORTH UP"
        chip = "%s NM  %s" % (map_layers.format_range_nm(self.range_nm), mode)
        if stale:
            chip += "  NO POS"
        p.drawText(QRectF(6, 4, self.width() - 12, f.pixelSize() + 6),
                   Qt.AlignmentFlag.AlignLeft, chip)

        # Revert indicator (decision A): while the view is manually offset a
        # small top-RIGHT chip (distinct from the top-left range chip) signals
        # the pending auto-revert -- "CTR" plus the remaining seconds while a
        # timer runs (amber = action pending; no countdown when gesture_timeout
        # is 0, so the view holds until a double-tap / CTR tap / HMI
        # recenter).
        if self.is_offset:
            rem = self._revert_timer.remainingTime()
            label = "CTR %ds" % int(math.ceil(rem / 1000.0)) \
                if rem and rem > 0 else "CTR"
            fr = QFont(self.font_family)
            fr.setPixelSize(max(9, int(self.width() * 0.03)))
            p.setFont(fr)
            pad = 5.0
            bw = p.fontMetrics().horizontalAdvance(label) + 2 * pad
            bh = fr.pixelSize() + 2 * pad
            box = QRectF(self.width() - bw - 6.0, 4.0, bw, bh)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(30, 30, 30, 170)))
            p.drawRoundedRect(box, 4.0, 4.0)
            p.setPen(QPen(QColor(255, 190, 60)))
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, label)
            # The chip is also the recenter soft key (FP10: a single tap on
            # the map selects now). Padded to a touch-sized target.
            self._ui_targets.append(
                (box.adjusted(-8.0, -4.0, 6.0, 8.0), self.recenter))

        self._paint_pointer(p, x)

        # --- MP6 perf accounting -------------------------------------------
        self.perf.record_paint_ms((time.perf_counter() - _perf_t0) * 1000.0)
        if self._perf_settle_pending and self._perf_last_gesture_ns is not None:
            if all(not layer.enabled or layer.is_settled(x)
                   for layer in self._layers):
                self.perf.settle_latency_ms = (
                    (time.perf_counter_ns() - self._perf_last_gesture_ns)
                    / 1e6)
                self._perf_settle_pending = False
        if self._map_perf_overlay:
            self._paint_perf_overlay(p)
        if self._map_perf_log:
            self.perf.maybe_report()

    # --- FP10 pointer / banner / chooser painting ---------------------------
    _TYPE_LABEL = {"airport": "APT", "vor": "VOR", "ndb": "NDB", "fix": "FIX",
                   "user": "USER", "map": "MAP"}
    _POINTER_COLOR = QColor(0, 255, 255)

    def _magvar(self):
        """``MAGVAR`` (positive west, MAG = TRUE + VAR), or None if the
        gateway does not publish it."""
        try:
            return float(fix.db.get_item("MAGVAR").value or 0.0)
        except (KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def _fmt_dm(lat, lon):
        def part(v, pos, neg, width):
            hemi = pos if v >= 0 else neg
            v = abs(v)
            d = int(v)
            return "%0*d %05.2f%s" % (width, d, (v - d) * 60.0, hemi)
        return "%s %s" % (part(lat, "N", "S", 2), part(lon, "E", "W", 3))

    def pointer_banner_text(self):
        """``(title, info)`` for the banner -- what it is, then bearing and
        distance from present position, elevation if the terrain layer can
        answer, and a navaid's frequency."""
        wp = self.pointer_waypoint()
        if wp is None:
            return "", ""
        if wp.type == "map" and wp.id == MAPWPT_ID:
            title = "MAP POINT  " + self._fmt_dm(wp.lat, wp.lon)
        else:
            title = "%s  %s" % (wp.id, self._TYPE_LABEL.get(wp.type, wp.type.upper()))
        brg = fp_geo.initial_bearing(self._lat, self._lon, wp.lat, wp.lon)
        var = self._magvar()
        if var is None:
            brg_txt = "%03d°T" % (int(round(brg)) % 360 or 360)
        else:
            brg_txt = "%03d°" % (int(round(brg + var)) % 360 or 360)
        dist = fp_geo.distance_nm(self._lat, self._lon, wp.lat, wp.lon)
        info = "%s  %s NM" % (brg_txt, ("%.1f" % dist) if dist < 100 else "%d" % round(dist))
        elev = self._pointer.get("elev_ft") if self._pointer else None
        if elev is not None:
            info += "  ELEV %d FT" % int(round(elev))
        if wp.freq:
            info += "  " + wp.freq
        return title, info

    def _ui_metrics(self):
        w, h = self.width(), self.height()
        fs = max(11, int(min(w, h) * 0.035))
        btn_h = max(36.0, min(64.0, h * 0.08))   # touch-sized soft keys
        return fs, btn_h, 6.0

    def _paint_pointer(self, p, x):
        ptr = self._pointer
        if ptr is not None:
            c = x.to_screen(ptr["lat"], ptr["lon"])
            pen = QPen(self._POINTER_COLOR)
            pen.setWidthF(2.0)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            r = HIT_TOL_PX
            p.drawEllipse(c, r, r)
            p.drawLine(QPointF(c.x() - 1.6 * r, c.y()), QPointF(c.x() - 0.5 * r, c.y()))
            p.drawLine(QPointF(c.x() + 0.5 * r, c.y()), QPointF(c.x() + 1.6 * r, c.y()))
            p.drawLine(QPointF(c.x(), c.y() - 1.6 * r), QPointF(c.x(), c.y() - 0.5 * r))
            p.drawLine(QPointF(c.x(), c.y() + 0.5 * r), QPointF(c.x(), c.y() + 1.6 * r))
            if ptr["choosing"]:
                self._paint_chooser(p)
            else:
                self._paint_banner(p)
        if self._toast:
            self._paint_toast(p)

    def _panel(self, p, rect):
        p.setPen(QPen(QColor(90, 90, 90), 1))
        p.setBrush(QBrush(QColor(20, 20, 24, 225)))
        p.drawRoundedRect(rect, 6.0, 6.0)

    def _soft_key(self, p, rect, label, cb, enabled=True):
        p.setPen(QPen(QColor(150, 150, 150) if enabled else QColor(70, 70, 70), 1))
        p.setBrush(QBrush(QColor(45, 45, 52) if enabled else QColor(30, 30, 34)))
        p.drawRoundedRect(rect, 4.0, 4.0)
        p.setPen(QPen(QColor(255, 255, 255) if enabled else QColor(100, 100, 100)))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)
        if enabled:
            self._ui_targets.append((QRectF(rect), cb))

    def _paint_banner(self, p):
        w, h = self.width(), self.height()
        fs, btn_h, pad = self._ui_metrics()
        line_h = fs * 1.35
        bh = pad + 2 * line_h + pad + btn_h + pad
        panel = QRectF(pad, h - bh - pad, w - 2 * pad, bh)
        self._panel(p, panel)
        # The banner swallows taps: a tap on its body must not count as a
        # "second tap away" and close it.
        self._ui_targets.append((QRectF(panel), lambda: None))
        title, info = self.pointer_banner_text()
        f = QFont(self.font_family)
        f.setPixelSize(fs)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QPen(self._POINTER_COLOR))
        tx = panel.x() + pad
        tw = panel.width() - 2 * pad
        p.drawText(QRectF(tx, panel.y() + pad, tw, line_h),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title)
        f.setBold(False)
        p.setFont(f)
        p.setPen(QPen(QColor(235, 235, 235)))
        p.drawText(QRectF(tx, panel.y() + pad + line_h, tw, line_h),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, info)
        bus = self._flightplan_bridge() is not None
        keys = (("DIRECT TO", self.banner_direct_to, bus, 1.25),
                ("INSERT", self.banner_insert, bus, 1.0),
                ("CREATE WPT", self.banner_create_wpt, True, 1.25),
                ("INFO", self.banner_info, True, 0.85),
                ("X", self.clear_pointer, True, 0.6))
        total = sum(k[3] for k in keys)
        gap = pad
        unit = (tw - gap * (len(keys) - 1)) / total
        bf = QFont(self.font_family)
        bf.setPixelSize(max(10, min(fs, int(btn_h * 0.36))))
        p.setFont(bf)
        bx = tx
        by = panel.bottom() - pad - btn_h
        for label, cb, enabled, weight in keys:
            r = QRectF(bx, by, unit * weight, btn_h)
            self._soft_key(p, r, label, cb, enabled)
            bx += unit * weight + gap

    def _paint_chooser(self, p):
        w, h = self.width(), self.height()
        fs, btn_h, pad = self._ui_metrics()
        objs = self._pointer["objects"][:_CHOOSER_MAX]
        row_h = btn_h
        line_h = fs * 1.35
        n = len(objs) + 1            # + CANCEL
        ch = pad + line_h + n * (row_h + pad) + pad
        ch = min(ch, h - 2 * pad)
        panel = QRectF(pad, h - ch - pad, w - 2 * pad, ch)
        self._panel(p, panel)
        self._ui_targets.append((QRectF(panel), lambda: None))
        f = QFont(self.font_family)
        f.setPixelSize(fs)
        p.setFont(f)
        p.setPen(QPen(self._POINTER_COLOR))
        tx = panel.x() + pad
        tw = panel.width() - 2 * pad
        p.drawText(QRectF(tx, panel.y() + pad, tw, line_h),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "%d OBJECTS HERE - SELECT ONE" % len(self._pointer["objects"]))
        y = panel.y() + pad + line_h + pad
        for wp in objs:
            dist = fp_geo.distance_nm(self._lat, self._lon, wp.lat, wp.lon)
            label = "%s   %s   %.1f NM" % (
                wp.id, self._TYPE_LABEL.get(wp.type, wp.type.upper()), dist)
            self._soft_key(p, QRectF(tx, y, tw, row_h), label,
                           lambda wp=wp: self.choose(wp))
            y += row_h + pad
        self._soft_key(p, QRectF(tx, y, tw, row_h), "CANCEL", self.clear_pointer)

    def _paint_toast(self, p):
        w, h = self.width(), self.height()
        fs, btn_h, pad = self._ui_metrics()
        f = QFont(self.font_family)
        f.setPixelSize(fs)
        p.setFont(f)
        tw = p.fontMetrics().horizontalAdvance(self._toast) + 4 * pad
        r = QRectF((w - tw) / 2.0, h * 0.12, tw, fs * 1.8)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(20, 20, 24, 225)))
        p.drawRoundedRect(r, 4.0, 4.0)
        p.setPen(QPen(self._POINTER_COLOR))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, self._toast)

    def _paint_perf_overlay(self, p):
        """map_perf_overlay: true (dev only) -- a small bottom-left stats
        chip so a bench run can be eyeballed without grepping the log
        (brief section 4)."""
        p50, p95, _mx, n = self.perf.paint_ms.stats()
        gp = self.perf.probe.stats()
        lines = [
            "paint p50/p95 %.1f/%.1f ms (n=%d)" % (p50, p95, n),
            "gui gap p95 %.1f ms >%dms:%d" % (
                gp["p95_ms"], int(self.perf.probe.gap_warn_ms),
                gp["over_count"]),
        ]
        if self.perf.settle_latency_ms is not None:
            lines.append("settle %.0f ms" % self.perf.settle_latency_ms)
        f = QFont(self.font_family)
        f.setPixelSize(max(8, int(self.width() * 0.022)))
        p.setFont(f)
        pad = 4.0
        lh = f.pixelSize() + 3
        bw = max(p.fontMetrics().horizontalAdvance(s) for s in lines) \
            + 2 * pad
        bh = lh * len(lines) + 2 * pad
        box = QRectF(6.0, self.height() - bh - 6.0, bw, bh)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(20, 20, 20, 170)))
        p.drawRoundedRect(box, 4.0, 4.0)
        p.setPen(QPen(QColor(120, 255, 120)))
        for i, s in enumerate(lines):
            p.drawText(QRectF(box.x() + pad, box.y() + pad + i * lh,
                              bw - 2 * pad, lh),
                       Qt.AlignmentFlag.AlignLeft, s)

    def _init_live_bindings_once(self):
        self.init_live_bindings(self._live_binding_specs())
