#  SPDX-License-Identifier: GPL-2.0-or-later
"""The `flight_plan` app-like instrument (FP5a/b, billmallard/pyEfis#185,
#187).

FPL page (route header, waypoint list, row menu, footer menu), Entry page
(FastFind ident field, suggestion strip, Recent/Nearest/FPL/User tabs, an
on-screen keypad), Direct To page (Waypoint/FPL/NRST APT tabs), Catalog page
(stored-route list and its Activate/Invert & Activate/Edit/Copy/Delete
actions), WPT Info (lat/lon, elevation/frequency, bearing/distance, user
waypoint Edit/Delete), the physical-keyboard input path and the encoder
path (FP5c, #188) all live here.

Modelled on the `checklist` instrument (docs/checklist_widget.md): a thin
QPainter view that never raises, with per-frame tap targets recorded during
paint and hit-tested in ``mousePressEvent`` (the HSI nav-source-label tap
pattern, ``instruments/hsi/__init__.py``).

The widget owns a *working copy* ``flightplan.model.FlightPlan``. Every edit
mutates it, then commits through ``flightplan.fixbridge.FixBridge.publish``
immediately (model.py: "the editor keeps one working copy and commits it ...
after every edit") and re-reads the bridge's ActivePlan read-back so a
second display of this instrument agrees (Appendix A: consumers act on
``FPLSEQ``, not on the local edit). If the bridge has no route published yet,
the FP1 keys are simply missing (construct-never-raises,
``pyEfis/CLAUDE.md``): ``available`` is False, an annunciation shows, and the
pages render read-only (no tap targets are registered).

Physical keyboard (FP5b): while the ``keyboard`` option is true and the
instrument's ident-entry surface (the Entry page, the Direct To page's
Waypoint tab, or a text/lat-lon modal) is open, the widget takes Qt focus and
consumes A-Z/0-9, Backspace, Enter, Escape, Up/Down, Tab, `.`/`-`; every
other key (and every key while no entry surface is open) is left un-accepted
so Qt's normal key-event propagation carries it up to ``gui.py``'s
``keyPress`` signal and ``hmi/keys.py`` bindings, same as before this
instrument existed. A bound HMI key that collides with A-Z while an entry
surface is open is shadowed by the field -- see docs/flight_plan_widget.md.

Encoder (FP5c): the screen's ``encoder``/``encoder_button`` keys reach the
widget through the ``enc_*`` protocol (``screens/screenbuilder_encoder.py``).
Inside the instrument the knob walks a focus ring built from the SAME
per-frame tap targets touch uses -- whatever is tappable on the topmost layer
is focusable, in paint order -- so a page can never grow a touch control the
knob cannot reach. On an ident field the turn scrolls the character at the
cursor and a push advances it; a long push (``enc_long_press_ms``) is Back.
With a dual-concentric knob (screen ``encoder_outer``) the outer ring moves
the cursor instead and a push on the field is always Enter.
"""

import logging
import math

from pyefis import display_metrics
import os

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QWidget

from pyavtools import fix
from pyefis import hmi
from pyefis.flightplan import airways as fp_airways
from pyefis.flightplan import catalog as fp_catalog
from pyefis.flightplan import fixbridge as fp_fixbridge
from pyefis.flightplan import geo as fp_geo
from pyefis.flightplan import model as fp_model
from pyefis.flightplan import procedures as fp_procedures
from pyefis.flightplan import waypoints as fp_waypoints

logger = logging.getLogger(__name__)

COLUMN_CHOICES = ("DTK", "DIS", "CUM", "ETE", "ETA")
ROLE_ABBREV = {"none": "", "iaf": "IAF", "faf": "FAF", "map": "MAP", "mahp": "MAHP"}
TYPE_FILTERS = {"All": None, "Apt": frozenset({"airport"}), "VOR": frozenset({"vor"}),
                "NDB": frozenset({"ndb"}), "Fix": frozenset({"fix"}),
                "User": frozenset({"user"})}
ENTRY_TABS = ("Recent", "Nearest", "FPL", "User")
DTO_TABS = ("Waypoint", "FPL", "NRST APT")
KEYPAD_ROWS = ("ABCDEFG", "HIJKLMN", "OPQRSTU", "VWXYZ01", "23456789")
KEYPAD_NUMERIC_ROWS = ("789", "456", "123", "0.-", "NSEW")
KEYPAD_CTRL_ROW = ("BKSP", "CLR", "ENT")

_STATE_BADGES = {0: "", 1: "LEG", 2: "DIRECT", 3: "SUSP"}
_APR_TEXT = {0: "", 1: "APR ARM", 2: "LNAV", 3: "MISSED"}
_CDI_SCALE_CHOICES = ("0.3", "1.0", "2.0", "AUTO")
_INSTRUMENT_PAGES = ("fpl", "entry", "dto", "catalog")

# Encoder (FP5c). The character set the knob scrolls through on an ident
# field, in the order the brief gives (A-Z, 0-9, space); a space at the cursor
# means "nothing here", so turning onto it and pushing accepts the field.
ENC_CHARSET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 "
# Hold time that turns an encoder push into Back. abstract.py has no
# long-press convention to inherit, so it is set here and documented in
# docs/flight_plan_widget.md.
ENC_LONG_PRESS_MS = 600
# How long a FPL-page toast (STORED, NO AIRWAYS AT x, ROUTE FULL, an error)
# stays up before it clears itself (pyEfis #323: with no expiry, STORED sat
# over the LEG/DIRECT/SUSP badge for the rest of a bench session).
TOAST_MS = 4000
# Same orange abstract.py uses for an encoder-selected gauge.
_ENC_FOCUS_COLOR = "#ffa500"

_ROW_MENU_ITEMS = (
    ("Insert Before", "_row_menu_insert_before"),
    ("Insert After", "_row_menu_insert_after"),
    ("Load Airway", "_row_menu_load_airway"),
    ("Activate Leg", "_row_menu_activate_leg"),
    ("Direct To", "_row_menu_direct_to"),
    ("WPT Info", "_row_menu_wpt_info"),
    ("Set Role", None),
    ("Remove", "_row_menu_remove"),
)
_ROLE_MENU_ORDER = ("none", "iaf", "faf", "map", "mahp")

# RS3 (AER-3792, brief route_segments_plan.md section 6): a tap on an airway's
# segment row opens this menu instead of the per-fix one. PA7 reuses the row
# and the menu for procedures with its own verbs.
_SEG_MENU_ITEMS = (
    ("Change Exit", "_seg_menu_change_exit"),
    ("Change Entry", "_seg_menu_change_entry"),
    ("Show Fixes", "_seg_menu_show_fixes"),
    ("Activate", "_seg_menu_activate"),
    ("Remove Airway", "_seg_menu_remove"),
)
# One fix inside a segment: from a nested working row or the Show Fixes sheet.
_SEG_FIX_MENU_ITEMS = (
    ("Direct To", "_seg_fix_direct_to"),
    ("Activate Leg", "_seg_fix_activate_leg"),
    ("WPT Info", "_seg_fix_wpt_info"),
)

# Every text size below is a fraction of some *height* (header/footer/row/box),
# while the rects the text sits in are fractions of the *width*. In a pane
# taller than it is wide (the Beelink's ~657x1003 Flight Plan tab) the text
# outgrows its rects and, since Qt does not clip drawText, labels run into
# each other. So fonts also shrink by (w/h)/_FONT_FIT_ASPECT, capped at 1.0:
# square and landscape panes (w/h >= 1.0) keep exactly the original sizes.
_FONT_FIT_ASPECT = 1.0


class FlightPlan(QWidget):
    """The `flight_plan` instrument widget."""

    def __init__(self, parent=None, font_family="DejaVu Sans Condensed",
                 font_percent=None):
        super().__init__(parent)
        self.parent = parent
        self.font_family = font_family
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # The common `font_percent` option (editor/schema.py common_options,
        # not an InstrumentSpec Prop). For this widget it is a multiplier on
        # the built-in text sizing (1.0 = 100%, 0.8 = 80%), NOT the usual
        # "fraction of widget height": the widget draws many text elements,
        # each already sized from its own region. None = 100%. See
        # _font_scale(); apply_options also setattr's it after construction.
        self.font_percent = font_percent

        # apply="attr" InstrumentSpec Props -- keep in lockstep with the
        # registry record (screenbuilder_factory.py) and its defaults.
        self.flightplan_dir = ""
        self.nasr_db_path = ""
        self.navaid_db_path = ""
        self.procedures_db_path = ""
        self.columns = "DTK,DIS,CUM"
        self.keypad = True
        self.keyboard = False
        self.default_page = "fpl"
        self.hmi_group = ""
        self.active_color = "#ff00ff"
        self.future_color = "#ffffff"
        self.past_color = "#808080"
        # Target height of one list row, in MILLIMETRES on the glass. Geometry,
        # not typography: this sets the row pitch, the type icon and (via
        # row_h * 0.5) the row font. It is deliberately physical rather than a
        # fraction of the pane -- a taller pane should show MORE legs, not
        # bigger ones -- and deliberately independent of font_percent, which
        # still scales the text drawn inside the row.
        self.row_height_mm = 14.0

        self._page = None
        self._plan = fp_model.FlightPlan()
        self._plan_dirty = False
        self._engine = {}
        # Every assignment to _message goes through the property below, which
        # (re)starts this one-shot timer; a tap anywhere clears it early.
        self.toast_ms = TOAST_MS
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self._clear_toast)
        self._message = ""
        self._cdi_scale_choice = "AUTO"

        self._row_menu_index = None
        self._role_menu_open = False
        self._wpt_info = None
        self._menu_open = False
        self._confirm = None

        # Airway insertion (PA6, AER-1605): row menu -> pick an airway through
        # the selected fix -> pick an exit fix -> AirwayGraph.expand() inserts
        # the intermediate fixes collapsed into one row (brief section 3.5).
        self._airway_picker = None

        # RS3 segment rows (AER-3792): the segment menu and the Show Fixes
        # sheet are keyed by segment index; the fix menu by flat index.
        self._seg_menu = None
        self._seg_fixes = None
        self._seg_fix_menu = None

        self._entry_mode = None
        self._entry_field = ""
        self._entry_tab = "Recent"
        self._entry_type_filter = "All"
        self._entry_dupe_choices = None
        self._entry_message = ""
        self._entry_nav_index = None

        self._dto_tab = "Waypoint"
        self._dto_target = None

        self._catalog_row_menu = None
        self._catalog_confirm = None
        self._catalog_message = ""
        self._catalog_dist_cache = {}

        self._modal = None
        self._uwpt_new = None
        self._uwpt_edit = None

        self._waypoint_index = None
        self._waypoint_index_key = None
        self._procedure_index = None
        self._procedure_index_key = None
        self._airway_graph = None
        self._airway_graph_key = None
        self._catalog = None
        self._catalog_dir_used = None

        self._tap_targets = []
        # Parallel to _tap_targets: a short tag per target ("row", "soft",
        # "key", ...) so the encoder can choose a sensible default focus and
        # leave the on-screen keypad out of its ring (the knob replaces it).
        self._tap_kinds = []

        # Encoder state (FP5c). _enc_layer_start indexes the first tap target
        # of the topmost layer (set by every overlay backdrop); _enc_field is
        # the ident field painted this frame, if any.
        self.enc_long_press_ms = ENC_LONG_PRESS_MS
        # Set True by EncoderController when the screen names an
        # `encoder_outer` key: the outer ring then moves the cursor, so a push
        # on the field always accepts instead of advancing (Bill, bench,
        # 2026-10-10: push-to-advance accepted KDFW when he meant KDAL).
        self.enc_has_outer = False
        self._enc_layer_start = 0
        self._enc_field = None
        self._enc_highlighted = False
        self._enc_active = False
        self._enc_focus = None
        self._enc_surface_sig = None
        self._enc_editing = False
        self._enc_cursor = 0
        # Popup-menu scroll state (AER-1605 follow-up): keyed by the caller's
        # scroll_key, value is (n_items, offset) -- the count guards against a
        # stale offset surviving into a different (shorter) item list opened
        # under the same key.
        self._menu_scroll = {}

        self._wpt_timer = QTimer(self)
        self._wpt_timer.setInterval(1000)
        self._wpt_timer.timeout.connect(self.update)

        self._bridge = fp_fixbridge.FixBridge(fix)
        if self._bridge.available:
            self._sync_plan_from_bridge()
            self._sync_engine_from_bridge()
            self._bridge.add_listener(self._on_bridge_change)
        self._connect_hmi()

    # -- toast ----------------------------------------------------------------
    @property
    def _message(self):
        return self._toast_text

    @_message.setter
    def _message(self, text):
        self._toast_text = text
        if text:
            self._toast_timer.start(self.toast_ms)
        else:
            self._toast_timer.stop()

    def _clear_toast(self):
        if self._toast_text:
            self._message = ""
            self.update()

    # -- HMI action hub ---------------------------------------------------
    def _connect_hmi(self):
        if hmi.actions is None:
            return
        a = hmi.actions
        for signal, handler in (
            (a.flightplanPage, self._act_page),
            (a.flightplanDirectTo, self._act_direct_to),
            (a.flightplanWptInfo, self._act_wpt_info),
            (a.flightplanCreateWaypoint, self._act_create_waypoint),
        ):
            try:
                signal.connect(handler)
            except Exception:
                logger.warning("flight_plan: could not connect HMI action",
                               exc_info=True)

    def _targeted(self, target):
        t = "" if target is None else str(target).strip()
        return t in ("", "*") or t == self.hmi_group

    def _act_page(self, arg=""):
        parts = str(arg or "").split()
        page = parts[0].lower() if parts else ""
        group = parts[1] if len(parts) > 1 else ""
        if not self._targeted(group):
            return
        if page == "fpl":
            self._row_menu_index = None
            self._seg_menu = None
            self._seg_fixes = None
            self._seg_fix_menu = None
            self._menu_open = False
            self._wpt_info = None
            self._close_entry()
            self._page = "fpl"
            self.update()
        elif page == "dto":
            self._open_dto_page()
        elif page == "catalog":
            self._open_catalog_page()

    def _show_fpl_base(self):
        """Close every menu, overlay and entry surface and show the FPL
        page -- the clean base the ``flightplan page fpl`` verb returns to."""
        self._row_menu_index = None
        self._seg_menu = None
        self._seg_fixes = None
        self._seg_fix_menu = None
        self._menu_open = False
        self._wpt_info = None
        self._modal = None
        self._uwpt_new = None
        self._uwpt_edit = None
        self._close_entry()
        self._page = "fpl"

    def _reveal(self):
        # Deferred import: tab_section pulls in the screenbuilder.
        from pyefis.instruments.tab_section import reveal
        reveal(self)

    def _act_wpt_info(self, wp):
        """Moving-map banner Info (FP10): WPT Info for *wp* (a
        ``flightplan.waypoints.Waypoint``), over the FPL page."""
        if wp is None:
            return
        self._show_fpl_base()
        self._open_wpt_info(wp)
        self._reveal()

    def _act_create_waypoint(self, pos):
        """Moving-map banner Create WPT (FP10): the FP5b user-waypoint form
        with LAT/LON prefilled from the map pointer *pos* ``(lat, lon)``,
        opened where it always lives -- over the Entry page's User tab, so
        the new waypoint is listed there to add once it is saved."""
        try:
            lat, lon = float(pos[0]), float(pos[1])
        except (TypeError, ValueError, IndexError):
            return
        self._show_fpl_base()
        self._open_entry({"kind": "append"})
        self._entry_tab = "User"
        self._open_user_wpt_creator(prefill=(lat, lon))
        self._reveal()

    def _act_direct_to(self, arg=""):
        parts = str(arg or "").split(None, 1)
        ident = parts[0] if parts else ""
        group = parts[1] if len(parts) > 1 else ""
        if not self._targeted(group):
            return
        if not ident:
            self._footer_direct_to()
            return
        if not self._bridge.available:
            return
        matches = self._ensure_waypoint_index().lookup(ident)
        if len(matches) == 1:
            self._bridge.stage_direct_to(matches[0])
            self._bridge.command("DTO")
            self._page = "fpl"
            self.update()

    # -- bridge sync -------------------------------------------------------
    def _sync_plan_from_bridge(self):
        # The bus is the truth (RS2, route segments brief guardrail 1): the
        # segment table says which slots are an airway, so there is nothing
        # to carry over from the plan as it stood before this sync.
        plan = self._bridge.read_plan()
        if plan is not None:
            self._plan = plan

    def _sync_engine_from_bridge(self):
        self._engine = self._bridge.read_engine() or {}

    def _on_bridge_change(self):
        self._sync_plan_from_bridge()
        self._sync_engine_from_bridge()
        self.update()

    def _commit(self):
        if self._bridge.available:
            self._bridge.publish(self._plan)
            self._sync_plan_from_bridge()
            self._sync_engine_from_bridge()
        self.update()

    def _engine_value(self, key, default=None):
        item = self._engine.get(key)
        return item.value if item is not None else default

    def _state_badge(self):
        return _STATE_BADGES.get(int(self._engine_value("FPLSTATE", 0) or 0), "")

    def _approach_text(self):
        return _APR_TEXT.get(int(self._engine_value("FPLAPR", 0) or 0), "")

    def _row_color(self, i, active_idx):
        if active_idx is not None and i == active_idx:
            return self.active_color
        if active_idx is not None and i < active_idx:
            return self.past_color
        return self.future_color

    @staticmethod
    def _fmt_ete(seconds):
        if seconds is None:
            return ""
        seconds = int(seconds)
        return "%d:%02d" % (seconds // 3600, (seconds % 3600) // 60)

    # -- waypoint index / catalog (lazy; path options apply post-construction)
    def _flightplan_dir(self):
        return os.path.expanduser(self.flightplan_dir) if self.flightplan_dir else ""

    def _ensure_waypoint_index(self):
        key = (self.nasr_db_path, self.navaid_db_path, self.flightplan_dir)
        if self._waypoint_index is not None and self._waypoint_index_key == key:
            return self._waypoint_index
        user_file = recent_file = None
        flightplan_dir = self._flightplan_dir()
        if flightplan_dir:
            user_file = f"{flightplan_dir}/user_waypoints.json"
            recent_file = f"{flightplan_dir}/recent.json"
        self._waypoint_index = fp_waypoints.WaypointIndex(
            airports_db_path=self.nasr_db_path or None,
            navaids_db_path=self.navaid_db_path or None,
            user_file=user_file, recent_file=recent_file)
        self._waypoint_index_key = key
        return self._waypoint_index

    def _ensure_procedure_index(self):
        # PA5 (AER-1604): the lookup service is wired here so PA7's PROC page
        # has somewhere to call into; PA7 owns actually driving it from the UI.
        key = self.procedures_db_path
        if self._procedure_index is not None and self._procedure_index_key == key:
            return self._procedure_index
        self._procedure_index = fp_procedures.ProcedureIndex(key or None)
        self._procedure_index_key = key
        return self._procedure_index

    def _ensure_airway_graph(self):
        # PA2 (AER-1601): airways live in the same procedures pack as PA5's
        # ProcedureIndex, so this reuses the same procedures_db_path Prop.
        key = self.procedures_db_path
        if self._airway_graph is not None and self._airway_graph_key == key:
            return self._airway_graph
        self._airway_graph = fp_airways.AirwayGraph(key or None)
        self._airway_graph_key = key
        return self._airway_graph

    def _ensure_catalog(self):
        if self._catalog is None or self._catalog_dir_used != self.flightplan_dir:
            flightplan_dir = self._flightplan_dir()
            directory = f"{flightplan_dir}/routes" if flightplan_dir else "routes"
            self._catalog = fp_catalog.Catalog(directory)
            self._catalog_dir_used = self.flightplan_dir
        return self._catalog

    def _aircraft_position(self):
        try:
            return fix.db.get_item("LAT").value, fix.db.get_item("LONG").value
        except KeyError:
            return 0.0, 0.0

    # -- Entry page: reference point + FastFind ----------------------------
    def _entry_reference_point(self):
        mode = self._entry_mode or {}
        kind = mode.get("kind")
        i = mode.get("index")
        wps = self._plan.waypoints
        if kind == "insert_before" and i is not None:
            neighbours = ([wps[i - 1]] if i - 1 >= 0 else []) \
                + ([wps[i]] if 0 <= i < len(wps) else [])
            return self._midpoint(neighbours)
        if kind == "insert_after" and i is not None:
            neighbours = ([wps[i]] if 0 <= i < len(wps) else []) \
                + ([wps[i + 1]] if i + 1 < len(wps) else [])
            return self._midpoint(neighbours)
        if kind == "append" and wps:
            return wps[-1].lat, wps[-1].lon
        return self._aircraft_position()

    @staticmethod
    def _midpoint(wps):
        if not wps:
            return None
        if len(wps) == 1:
            return wps[0].lat, wps[0].lon
        return (wps[0].lat + wps[1].lat) / 2.0, (wps[0].lon + wps[1].lon) / 2.0

    def _entry_ref(self):
        return self._entry_reference_point() or self._aircraft_position()

    def _entry_candidates(self):
        idx = self._ensure_waypoint_index()
        ref_lat, ref_lon = self._entry_ref()
        types = TYPE_FILTERS.get(self._entry_type_filter)
        return idx.prefix(self._entry_field, ref_lat, ref_lon, limit=5, types=types)

    def _entry_suffix(self):
        if not self._entry_field:
            return ""
        cands = self._entry_candidates()
        if not cands:
            return ""
        best = cands[0].id
        if best.startswith(self._entry_field):
            return best[len(self._entry_field):]
        return ""

    def _entry_tab_rows(self):
        idx = self._ensure_waypoint_index()
        types = TYPE_FILTERS.get(self._entry_type_filter)
        if self._entry_tab == "Recent":
            out = []
            for ident in idx.recent.list():
                matches = idx.lookup(ident)
                if matches and (not types or matches[0].type in types):
                    out.append(matches[0])
            return out
        if self._entry_tab == "Nearest":
            ref_lat, ref_lon = self._entry_ref()
            return [r[0] for r in idx.nearest(ref_lat, ref_lon, types=types)]
        if self._entry_tab == "FPL":
            return [w for w in self._plan.waypoints if not types or w.type in types]
        if self._entry_tab == "User":
            return [w for w in idx.user.list() if not types or w.type in types]
        return []

    # -- Entry page: keypad / commit ---------------------------------------
    def _entry_key(self, ch):
        if len(self._entry_field) < 10:
            self._entry_field += ch
        self._entry_message = ""
        self._entry_nav_index = None
        self.update()

    def _entry_backspace(self):
        self._entry_field = self._entry_field[:-1]
        self._entry_message = ""
        self._entry_nav_index = None
        self.update()

    def _entry_clear(self):
        self._entry_field = ""
        self._entry_message = ""
        self._entry_nav_index = None
        self.update()

    def _entry_cancel(self):
        self._close_entry()

    def _close_entry(self):
        self._entry_mode = None
        self._entry_field = ""
        self._entry_message = ""
        self._entry_dupe_choices = None
        self._entry_nav_index = None
        self._page = "fpl"
        self.update()

    def _entry_enter(self):
        typed = self._entry_field
        if not typed:
            return
        suffix = self._entry_suffix()
        ident = typed + suffix if suffix else typed
        matches = self._ensure_waypoint_index().lookup(ident)
        if not matches:
            self._entry_message = "NO MATCHES"
            self.update()
            return
        if len(matches) > 1:
            self._entry_message = "DUPLICATE FOUND"
            self._entry_dupe_choices = matches
            self.update()
            return
        self._select_waypoint(matches[0])

    def _choose_duplicate(self, wp):
        self._entry_dupe_choices = None
        self._select_waypoint(wp)

    def _cancel_dupe_chooser(self):
        self._entry_dupe_choices = None
        self.update()

    def _select_entry_tab(self, tab):
        self._entry_tab = tab
        self.update()

    def _open_entry(self, mode):
        self._entry_mode = mode
        self._entry_field = ""
        self._entry_message = ""
        self._entry_dupe_choices = None
        self._entry_nav_index = None
        self._entry_tab = "Recent"
        self._entry_type_filter = "All"
        self._page = "entry"
        self.update()

    def _select_waypoint(self, wp):
        mode = self._entry_mode or {"kind": "append"}
        kind = mode.get("kind")
        i = mode.get("index")
        new_wp = fp_model.Waypoint(id=wp.id, type=wp.type, lat=wp.lat, lon=wp.lon,
                                    name=getattr(wp, "name", "") or "")
        if kind == "direct_to":
            if self._bridge.available:
                self._bridge.stage_direct_to(new_wp)
                self._bridge.command("DTO")
            self._close_entry()
            return
        try:
            if kind == "insert_before":
                self._plan.insert_before(i, new_wp)
            elif kind == "insert_after":
                self._plan.insert_after(i, new_wp)
            else:  # append
                self._plan.insert_after(len(self._plan.waypoints) - 1, new_wp)
        except fp_model.FlightPlanError as e:
            self._entry_message = str(e)
            self.update()
            return
        self._ensure_waypoint_index().recent.push(wp.id)
        self._plan_dirty = True
        self._commit()
        self._close_entry()

    # -- FPL page: row menu -------------------------------------------------
    def _open_row_menu(self, i):
        self._row_menu_index = i
        self._role_menu_open = False
        self.update()

    def _close_row_menu(self):
        self._row_menu_index = None
        self._role_menu_open = False
        self.update()

    def _open_role_menu(self):
        self._role_menu_open = True
        self.update()

    def _row_menu_insert_before(self):
        i = self._row_menu_index
        self._close_row_menu()
        self._open_entry({"kind": "insert_before", "index": i})

    def _row_menu_insert_after(self):
        i = self._row_menu_index
        self._close_row_menu()
        self._open_entry({"kind": "insert_after", "index": i})

    def _row_menu_activate_leg(self):
        i = self._row_menu_index
        self._close_row_menu()
        if self._bridge.available:
            self._bridge.command("ACT", i + 1)

    def _row_menu_direct_to(self):
        i = self._row_menu_index
        wp = self._plan.waypoints[i]
        self._close_row_menu()
        if self._bridge.available:
            self._bridge.stage_direct_to(wp)
            self._bridge.command("DTO", i + 1)

    def _row_menu_wpt_info(self):
        i = self._row_menu_index
        wp = self._plan.waypoints[i]
        self._close_row_menu()
        self._open_wpt_info(wp)

    def _open_wpt_info(self, wp):
        """*wp* may be a plan ``model.Waypoint`` (no elevation/frequency) or a
        ``waypoints.Waypoint``; resolve the richer record from the lookup
        index when one exists so elevation/frequency show for anything the
        on-device databases know about (brief 3.5 WPT Info)."""
        self._wpt_info = self._resolve_wpt_info(wp)
        self._wpt_timer.start()
        self.update()

    def _resolve_wpt_info(self, wp):
        matches = self._ensure_waypoint_index().lookup(wp.id)
        for m in matches:
            if m.type == wp.type:
                return m
        if matches:
            return matches[0]
        return fp_waypoints.Waypoint(id=wp.id, type=wp.type, lat=wp.lat, lon=wp.lon,
                                      name=getattr(wp, "name", "") or "")

    def _close_wpt_info(self):
        self._wpt_info = None
        self._wpt_timer.stop()
        self.update()

    def _row_menu_remove(self):
        i = self._row_menu_index
        self._close_row_menu()
        try:
            self._plan.remove(i)
        except fp_model.FlightPlanError as e:
            self._message = str(e)
            self.update()
            return
        self._plan_dirty = True
        self._commit()

    def _row_menu_set_role(self, role):
        i = self._row_menu_index
        try:
            self._plan.set_role(i, role)
        except fp_model.FlightPlanError as e:
            self._message = str(e)
            self._close_row_menu()
            self.update()
            return
        self._close_row_menu()
        self._plan_dirty = True
        self._commit()

    # -- FPL page: airway insertion (PA6, AER-1605) --------------------------
    def _row_menu_load_airway(self):
        i = self._row_menu_index
        wp = self._plan.waypoints[i]
        self._close_row_menu()
        self._open_airway_picker(i, wp)

    def _open_airway_picker(self, i, wp):
        graph = self._ensure_airway_graph()
        idents = graph.airways_through_fix(wp.id)
        if not idents:
            self._message = f"NO AIRWAYS AT {wp.id}"
            self.update()
            return
        self._airway_picker = {"stage": "airway", "entry_index": i, "entry_wp": wp,
                                "idents": idents, "ident": None, "legs": [], "message": ""}
        self.update()

    def _close_airway_picker(self):
        self._airway_picker = None
        self.update()

    def _airway_picker_pick_ident(self, ident):
        picker = self._airway_picker
        graph = self._ensure_airway_graph()
        entry_norm = picker["entry_wp"].id.strip().upper()
        exits = [leg for leg in graph.legs(ident) if leg.fix_id.strip().upper() != entry_norm]
        if not exits:
            picker["message"] = f"NO OTHER FIXES ON {ident}"
            self.update()
            return
        picker.update(stage="exit", ident=ident, legs=exits, message="")
        self.update()

    def _airway_picker_pick_exit(self, exit_fix_id):
        picker = self._airway_picker
        graph = self._ensure_airway_graph()
        try:
            expansion = graph.expand(picker["ident"], picker["entry_wp"].id, exit_fix_id)
        except fp_airways.AirwayError as e:
            picker["message"] = str(e)
            self.update()
            return
        self._insert_airway_segment(picker["entry_index"], picker["ident"], expansion)
        self._airway_picker = None
        self.update()

    def _insert_airway_segment(self, entry_index, ident, expansion):
        """*expansion* is the published fix sequence of *ident* from the entry
        fix at *entry_index* to the chosen exit fix, inclusive of both
        (``AirwayGraph.expand``). ``FlightPlan.insert_airway`` makes it one
        airway segment, whole or not at all: a route already near
        ``MAX_WAYPOINTS`` must not accept half an airway."""
        new_wps = expansion[1:]
        if not new_wps:
            return
        if self._plan.count + len(new_wps) > fp_model.MAX_WAYPOINTS:
            self._message = f"ROUTE FULL -- {ident} NEEDS {len(new_wps)} MORE SLOTS"
            self.update()
            return
        try:
            self._plan.insert_airway(entry_index, ident, expansion[-1].id,
                                     self._ensure_airway_graph())
        except fp_model.FlightPlanError as e:
            self._message = str(e)
            self.update()
            return
        self._plan_dirty = True
        self._commit()

    # -- FPL page: segment rows (RS3, AER-3792) --------------------------------
    def _active_index(self):
        active_leg = self._engine_value("FPLACTLEG")
        return int(active_leg) - 1 if active_leg else None

    def _display_rows(self, active_idx):
        """What the list draws, top to bottom (brief section 6).

        ``("wpt", i)`` is one plain fix. An airway is its entry fix as a plain
        row (the leg into it is not part of the airway) and then one
        ``("seg", k)`` row standing for every leg inside it. When the active
        leg is one of those, the segment opens into nested working rows --
        ``("fix", i, role)`` for the FROM fix, the active TO fix and the next
        fix -- and the rest ahead fold into ``("fold", k, n)``. Passed fixes
        before FROM are not repeated: the header still names the entry."""
        rows = []
        for k, seg in enumerate(self._plan.segments):
            first, last = self._plan.segment_span(k)
            if seg.kind != "airway":
                rows.extend(("wpt", i) for i in range(first, last + 1))
                continue
            rows.append(("wpt", first))
            rows.append(("seg", k))
            if active_idx is None or not (first < active_idx <= last):
                continue
            rows.append(("fix", active_idx - 1, "from"))
            rows.append(("fix", active_idx, "to"))
            if active_idx + 1 <= last:
                rows.append(("fix", active_idx + 1, "next"))
            ahead = last - (active_idx + 1)
            if ahead > 0:
                rows.append(("fold", k, ahead))
        return rows

    def _segment_active(self, k, active_idx):
        first, last = self._plan.segment_span(k)
        return active_idx is not None and first < active_idx <= last

    def _segment_color(self, k, active_idx):
        first, last = self._plan.segment_span(k)
        if active_idx is None or active_idx <= first:
            return self.future_color
        if active_idx <= last:
            return self.active_color
        return self.past_color

    def _segment_length(self, k):
        first, last = self._plan.segment_span(k)
        return sum(self._plan.leg(i)[1] for i in range(first, last))

    @staticmethod
    def _mea_text(wp):
        alt = (wp.alt or "").strip()
        return alt.lstrip("+") if alt.startswith("+") else alt

    def _segment_mea(self, k):
        """Highest leg minimum inside the segment -- the altitude that keeps
        the whole airway legal, which is what a pilot wants in one number."""
        seg = self._plan.segments[k]
        meas = []
        for wp in seg.legs[1:]:
            try:
                meas.append(int(self._mea_text(wp)))
            except ValueError:
                pass
        return max(meas) if meas else None

    def _magvar(self):
        return self._bridge._magvar() if self._bridge.available else 0.0

    def _leg_in(self, i):
        """``(dtk_magnetic, dist_nm)`` of the leg INTO flat fix *i*, or None
        for the first fix. Magnetic with the bridge's MAGVAR -- the same
        conversion the engine applies to ``FPLCRS`` (positive west,
        MAG = TRUE + VAR), so the active row's DTK equals ``FPLCRS``."""
        if i <= 0:
            return None
        wp = self._plan.waypoints[i]
        dtk_true, dist = self._plan.leg(i - 1)
        dtk = wp.crs if wp.crs is not None else (dtk_true + self._magvar()) % 360.0
        return dtk, dist

    # -- segment menu ------------------------------------------------------------
    def _open_seg_menu(self, k):
        self._seg_menu = k
        self.update()

    def _close_seg_menu(self):
        self._seg_menu = None
        self.update()

    def _seg_menu_change_exit(self):
        self._open_segment_picker(self._seg_menu, "exit")

    def _seg_menu_change_entry(self):
        self._open_segment_picker(self._seg_menu, "entry")

    def _open_segment_picker(self, k, end):
        seg = self._plan.segments[k]
        self._seg_menu = None
        keep = seg.entry if end == "exit" else seg.exit
        legs = [leg for leg in self._ensure_airway_graph().legs(seg.ident)
                if leg.fix_id.strip().upper() != keep.strip().upper()]
        if not legs:
            self._message = f"NO OTHER FIXES ON {seg.ident}"
            self.update()
            return
        self._airway_picker = {"stage": f"change_{end}", "seg": k, "ident": seg.ident,
                                "legs": legs, "message": ""}
        self.update()

    def _segment_picker_pick(self, fix_id):
        picker = self._airway_picker
        graph = self._ensure_airway_graph()
        try:
            if picker["stage"] == "change_exit":
                self._plan.change_exit(picker["seg"], fix_id, graph)
            else:
                self._plan.change_entry(picker["seg"], fix_id, graph)
        except fp_model.FlightPlanError as e:
            picker["message"] = str(e)
            self.update()
            return
        self._airway_picker = None
        self._plan_dirty = True
        self._commit()

    def _seg_menu_show_fixes(self):
        k = self._seg_menu
        self._seg_menu = None
        self._open_seg_fixes(k)

    def _open_seg_fixes(self, k):
        self._seg_fixes = k
        self.update()

    def _close_seg_fixes(self):
        self._seg_fixes = None
        self.update()

    def _seg_menu_activate(self):
        # "Activate (to entry)": fly to the airway's entry fix, so the
        # sequencer then carries on into the airway.
        first, _ = self._plan.segment_span(self._seg_menu)
        self._close_seg_menu()
        if self._bridge.available:
            self._bridge.command("ACT", first + 1)

    def _seg_menu_remove(self):
        k = self._seg_menu
        self._close_seg_menu()
        try:
            self._plan.remove_segment(k)
        except fp_model.FlightPlanError as e:
            self._message = str(e)
            self.update()
            return
        self._plan_dirty = True
        self._commit()

    # -- one fix inside a segment -------------------------------------------------
    def _open_seg_fix_menu(self, i):
        self._seg_fix_menu = i
        self.update()

    def _close_seg_fix_menu(self):
        self._seg_fix_menu = None
        self.update()

    def _seg_fix_direct_to(self):
        i = self._seg_fix_menu
        self._seg_fix_menu = None
        self._seg_fixes = None
        if self._bridge.available:
            self._bridge.stage_direct_to(self._plan.waypoints[i])
            self._bridge.command("DTO", i + 1)
        self.update()

    def _seg_fix_activate_leg(self):
        i = self._seg_fix_menu
        self._seg_fix_menu = None
        self._seg_fixes = None
        if self._bridge.available:
            self._bridge.command("ACT", i + 1)
        self.update()

    def _seg_fix_wpt_info(self):
        i = self._seg_fix_menu
        self._seg_fix_menu = None
        self._open_wpt_info(self._plan.waypoints[i])

    # -- FPL page: footer / menu ---------------------------------------------
    def _footer_add(self):
        self._open_entry({"kind": "append", "index": None})

    def _footer_direct_to(self):
        self._open_dto_page()

    def _footer_catalog(self):
        self._open_catalog_page()

    def _footer_menu(self):
        self._menu_open = not self._menu_open
        self._confirm = None
        self.update()

    def _close_menu(self):
        self._menu_open = False
        self._confirm = None
        self.update()

    def _show_plan_notices(self, plan):
        # An airway re-expanded against a newer AIRAC cycle (catalog.py) is
        # surfaced on the FPL page, never swapped in silently (route
        # segments brief guardrail 3). Notices are not on the bus, so they
        # are read here, before _commit() re-reads the plan from it.
        if plan.notices:
            self._message = "; ".join(plan.notices)

    def _menu_invert(self):
        try:
            self._plan = self._plan.invert(self._ensure_airway_graph())
        except fp_model.FlightPlanError as e:
            self._message = str(e)
            self._menu_open = False
            self.update()
            return
        self._plan_dirty = True
        self._menu_open = False
        self._commit()

    def _menu_store(self):
        try:
            self._ensure_catalog().save(self._plan)
            self._message = "STORED"
            self._plan_dirty = False
        except fp_catalog.CatalogError as e:
            self._message = str(e)
        self._menu_open = False
        self.update()

    def _menu_clear_request(self):
        self._confirm = "clear"
        self.update()

    def _menu_clear_confirm(self):
        self._plan = fp_model.FlightPlan()
        self._plan_dirty = False
        self._confirm = None
        self._menu_open = False
        self._commit()

    def _menu_delete_request(self):
        self._confirm = "delete"
        self.update()

    def _menu_delete_confirm(self):
        self._plan = fp_model.FlightPlan()
        self._plan_dirty = False
        self._confirm = None
        self._menu_open = False
        self._commit()

    def _menu_suspend_resume(self):
        if self._bridge.available:
            state = int(self._engine_value("FPLSTATE", 0) or 0)
            self._bridge.command("RESUME" if state == 3 else "SUSP")
        self._menu_open = False
        self.update()

    def _menu_cdi_scale(self):
        cur = self._cdi_scale_choice
        idx = _CDI_SCALE_CHOICES.index(cur) if cur in _CDI_SCALE_CHOICES else -1
        self._cdi_scale_choice = _CDI_SCALE_CHOICES[(idx + 1) % len(_CDI_SCALE_CHOICES)]
        if self._bridge.available:
            self._bridge.command("SCALE", self._cdi_scale_choice)
        self.update()

    # -- Direct To (DTO) page ------------------------------------------------
    def _open_dto_page(self):
        self._dto_tab = "Waypoint"
        self._dto_target = None
        self._entry_mode = {"kind": "direct_to"}
        self._entry_field = ""
        self._entry_message = ""
        self._entry_dupe_choices = None
        self._entry_nav_index = None
        self._page = "dto"
        self.update()

    def _close_dto(self):
        self._entry_mode = None
        self._entry_field = ""
        self._entry_dupe_choices = None
        self._entry_nav_index = None
        self._dto_target = None
        self._page = "fpl"
        self.update()

    def _select_dto_tab(self, tab):
        self._dto_tab = tab
        self._entry_nav_index = None
        self.update()

    def _dto_select_fpl(self, i):
        self._dto_target = ("fpl", i, self._plan.waypoints[i])
        self.update()

    def _dto_select_nearest(self, wp):
        self._dto_target = ("wp", None, wp)
        self.update()

    def _dto_activate(self):
        if not self._bridge.available:
            return
        state = int(self._engine_value("FPLSTATE", 0) or 0)
        if state == 2:  # an existing direct-to is active -- this button is "Remove"
            self._bridge.command("DTOX")
            self._close_dto()
            return
        target = self._dto_target
        if target is None:
            self._message = "SELECT A WAYPOINT"
            self.update()
            return
        kind, idx, wp = target
        self._bridge.stage_direct_to(wp)
        if kind == "fpl":
            self._bridge.command("DTO", idx + 1)
        else:
            self._bridge.command("DTO")
        self._close_dto()

    # -- Catalog page ---------------------------------------------------------
    def _open_catalog_page(self):
        self._catalog_row_menu = None
        self._catalog_confirm = None
        self._catalog_message = ""
        self._page = "catalog"
        self.update()

    def _close_catalog(self):
        self._catalog_row_menu = None
        self._catalog_confirm = None
        self._page = "fpl"
        self.update()

    def _catalog_entries(self):
        return sorted(self._ensure_catalog().list(), key=lambda e: e.mtime, reverse=True)

    def _catalog_entry_distance_nm(self, entry, ref_lat, ref_lon):
        cached = self._catalog_dist_cache.get(entry.slug)
        if cached is not None and cached[0] == entry.mtime:
            return cached[1]
        try:
            plan = self._ensure_catalog().load(entry.slug)
        except fp_catalog.CatalogError:
            return None
        dist = (fp_geo.distance_nm(ref_lat, ref_lon, plan.waypoints[0].lat, plan.waypoints[0].lon)
                if plan.waypoints else None)
        self._catalog_dist_cache[entry.slug] = (entry.mtime, dist)
        return dist

    def _catalog_open_row_menu(self, slug):
        self._catalog_row_menu = slug
        self.update()

    def _close_catalog_row_menu(self):
        self._catalog_row_menu = None
        self.update()

    def _catalog_row_menu_items(self, slug):
        managed = slug.startswith(fp_catalog.MANAGED_PREFIX)
        items = [
            ("Activate", lambda: self._catalog_activate(slug)),
            ("Invert & Activate", lambda: self._catalog_invert_activate(slug)),
        ]
        if not managed:
            items.append(("Edit", lambda: self._catalog_edit(slug)))
        items.append(("Copy", lambda: self._catalog_copy_prompt(slug)))
        if not managed:
            items.append(("Delete", lambda: self._catalog_delete_request(slug)))
        return items

    def _plan_unsaved(self):
        return self._plan_dirty and self._plan.count > 0

    def _catalog_activate(self, slug):
        self._catalog_row_menu = None
        if self._plan_unsaved():
            self._catalog_confirm = {"kind": "activate", "slug": slug}
            self.update()
            return
        self._catalog_do_activate(slug)

    def _catalog_do_activate(self, slug):
        try:
            plan = self._ensure_catalog().load(slug, self._ensure_airway_graph())
        except fp_catalog.CatalogError as e:
            self._catalog_message = str(e)
            self._catalog_confirm = None
            self.update()
            return
        self._plan = plan
        self._plan_dirty = False
        self._catalog_confirm = None
        self._show_plan_notices(plan)
        self._commit()
        self._close_catalog()

    def _catalog_invert_activate(self, slug):
        self._catalog_row_menu = None
        if self._plan_unsaved():
            self._catalog_confirm = {"kind": "invert_activate", "slug": slug}
            self.update()
            return
        self._catalog_do_invert_activate(slug)

    def _catalog_do_invert_activate(self, slug):
        try:
            plan = self._ensure_catalog().invert(slug, self._ensure_airway_graph())
        except (fp_catalog.CatalogError, fp_model.FlightPlanError) as e:
            self._catalog_message = str(e)
            self._catalog_confirm = None
            self.update()
            return
        self._plan = plan
        self._plan_dirty = False
        self._catalog_confirm = None
        self._show_plan_notices(plan)
        self._commit()
        self._close_catalog()

    def _catalog_edit(self, slug):
        """Loads *slug* into the working copy for editing without publishing
        it to the bus -- the guide's "Edit ... Store writes back" (brief
        3.5). The active route on the bus is untouched until the next edit
        commits or Store is used."""
        self._catalog_row_menu = None
        try:
            plan = self._ensure_catalog().load(slug, self._ensure_airway_graph())
        except fp_catalog.CatalogError as e:
            self._catalog_message = str(e)
            self.update()
            return
        self._plan = plan
        self._plan_dirty = bool(plan.notices)
        self._show_plan_notices(plan)
        self._page = "fpl"
        self.update()

    def _catalog_copy_prompt(self, slug):
        self._catalog_row_menu = None
        try:
            plan = self._ensure_catalog().load(slug)
        except fp_catalog.CatalogError as e:
            self._catalog_message = str(e)
            self.update()
            return
        default_name = plan.name or plan.default_name()
        self._modal_open("COPY AS", default_name, False, fp_model.NAME_MAX_LEN,
                          (lambda v, slug=slug: self._catalog_copy_commit(slug, v)))

    def _catalog_copy_commit(self, slug, new_name):
        try:
            self._ensure_catalog().copy(slug, new_name)
            self._catalog_message = "COPIED"
        except fp_catalog.CatalogError as e:
            self._catalog_message = str(e)
        self.update()

    def _catalog_delete_request(self, slug):
        self._catalog_row_menu = None
        self._catalog_confirm = {"kind": "delete", "slug": slug}
        self.update()

    def _catalog_delete_confirm(self):
        slug = self._catalog_confirm["slug"]
        try:
            self._ensure_catalog().delete(slug)
            self._catalog_message = "DELETED"
        except fp_catalog.CatalogError as e:
            self._catalog_message = str(e)
        self._catalog_confirm = None
        self.update()

    def _catalog_new(self):
        if self._plan_unsaved():
            self._catalog_confirm = {"kind": "new"}
            self.update()
            return
        self._catalog_do_new()

    def _catalog_do_new(self):
        self._plan = fp_model.FlightPlan()
        self._plan_dirty = False
        self._catalog_confirm = None
        self._commit()
        self._close_catalog()

    def _catalog_delete_all_request(self):
        self._catalog_confirm = {"kind": "delete_all"}
        self.update()

    def _catalog_delete_all_confirm(self):
        cat = self._ensure_catalog()
        skipped = 0
        for entry in cat.list():
            if entry.slug.startswith(fp_catalog.MANAGED_PREFIX):
                skipped += 1
                continue
            cat.delete(entry.slug)
        self._catalog_message = (f"DELETED ALL (SKIPPED {skipped} MANAGED)" if skipped
                                  else "DELETED ALL")
        self._catalog_confirm = None
        self.update()

    def _catalog_confirm_yes(self):
        c = self._catalog_confirm
        if c is None:
            return
        {
            "activate": lambda: self._catalog_do_activate(c["slug"]),
            "invert_activate": lambda: self._catalog_do_invert_activate(c["slug"]),
            "delete": self._catalog_delete_confirm,
            "delete_all": self._catalog_delete_all_confirm,
            "new": self._catalog_do_new,
        }[c["kind"]]()

    def _catalog_confirm_no(self):
        self._catalog_confirm = None
        self.update()

    # -- generic modal text/numeric entry (Catalog Copy, user waypoints) -----
    def _modal_open(self, title, value, numeric, max_len, on_enter):
        self._modal = {"title": title, "value": value, "numeric": numeric,
                        "max_len": max_len, "on_enter": on_enter}
        self.update()

    def _modal_key(self, ch):
        m = self._modal
        if m is None:
            return
        if len(m["value"]) < m["max_len"]:
            m["value"] += ch
        self.update()

    def _modal_backspace(self):
        m = self._modal
        if m is None:
            return
        m["value"] = m["value"][:-1]
        self.update()

    def _modal_clear(self):
        m = self._modal
        if m is None:
            return
        m["value"] = ""
        self.update()

    def _modal_enter(self):
        m = self._modal
        if m is None:
            return
        self._modal = None
        m["on_enter"](m["value"])

    def _modal_do_cancel(self):
        self._modal = None
        self.update()

    # -- lat/lon entry helpers (numeric modal: digits, '.', '-', N/S/E/W) ----
    @staticmethod
    def _fmt_latlon_entry(value, is_lat):
        hemi = ("N" if value >= 0 else "S") if is_lat else ("E" if value >= 0 else "W")
        return f"{abs(value):.4f}{hemi}"

    @staticmethod
    def _parse_latlon_entry(value, is_lat):
        value = (value or "").strip().upper()
        if not value:
            return None
        hemi = value[-1]
        want = ("N", "S") if is_lat else ("E", "W")
        if hemi not in want:
            return None
        try:
            mag = float(value[:-1])
        except ValueError:
            return None
        return -mag if hemi in ("S", "W") else mag

    @staticmethod
    def _fmt_latlon_dm(lat, lon):
        def part(value, pos_hemi, neg_hemi):
            hemi = pos_hemi if value >= 0 else neg_hemi
            value = abs(value)
            d = int(value)
            m = (value - d) * 60.0
            return f"{d:02d} {m:05.2f}{hemi}"
        return f"{part(lat, 'N', 'S')}  {part(lon, 'E', 'W')}"

    # -- user waypoint create (Entry page User tab) / edit (WPT Info) --------
    def _open_user_wpt_creator(self, prefill=None):
        """*prefill* ``(lat, lon)`` seeds the LAT/LON fields instead of the
        aircraft position (the moving-map Create WPT, FP10)."""
        self._uwpt_new = {"prefill": prefill}
        self._modal_open("IDENT (BLANK=AUTO)", "", False, fp_waypoints.USER_ID_MAX_LEN,
                          self._uwpt_new_ident)

    def _uwpt_new_ident(self, value):
        self._uwpt_new["id"] = value.strip().upper()
        self._modal_open("COMMENT", "", False, fp_waypoints.USER_COMMENT_MAX_LEN,
                          self._uwpt_new_comment)

    def _uwpt_new_comment(self, value):
        self._uwpt_new["comment"] = value
        ref_lat, ref_lon = self._uwpt_new.get("prefill") or self._aircraft_position()
        self._modal_open("LAT", self._fmt_latlon_entry(ref_lat, True), True, 10,
                          self._uwpt_new_lat)

    def _uwpt_new_lat(self, value):
        lat = self._parse_latlon_entry(value, True)
        if lat is None:
            self._message = "BAD LAT"
            self.update()
            return
        self._uwpt_new["lat"] = lat
        ref_lat, ref_lon = self._uwpt_new.get("prefill") or self._aircraft_position()
        self._modal_open("LON", self._fmt_latlon_entry(ref_lon, False), True, 11,
                          self._uwpt_new_lon)

    def _uwpt_new_lon(self, value):
        lon = self._parse_latlon_entry(value, False)
        if lon is None:
            self._message = "BAD LON"
            self.update()
            return
        n = self._uwpt_new
        try:
            wp = self._ensure_waypoint_index().user.add(
                lat=n["lat"], lon=lon, comment=n["comment"], id=n["id"] or None)
            self._message = f"CREATED {wp.id}"
        except fp_waypoints.WaypointError as e:
            self._message = str(e)
        self._uwpt_new = None
        self.update()

    def _open_user_wpt_editor(self, wp):
        self._uwpt_edit = {"id": wp.id}
        self._modal_open("COMMENT", wp.comment or "", False, fp_waypoints.USER_COMMENT_MAX_LEN,
                          self._uwpt_edit_comment)

    def _uwpt_edit_comment(self, value):
        self._uwpt_edit["comment"] = value
        wp = self._wpt_info
        self._modal_open("LAT", self._fmt_latlon_entry(wp.lat, True), True, 10,
                          self._uwpt_edit_lat)

    def _uwpt_edit_lat(self, value):
        lat = self._parse_latlon_entry(value, True)
        if lat is None:
            self._message = "BAD LAT"
            self.update()
            return
        self._uwpt_edit["lat"] = lat
        wp = self._wpt_info
        self._modal_open("LON", self._fmt_latlon_entry(wp.lon, False), True, 11,
                          self._uwpt_edit_lon)

    def _uwpt_edit_lon(self, value):
        lon = self._parse_latlon_entry(value, False)
        if lon is None:
            self._message = "BAD LON"
            self.update()
            return
        e = self._uwpt_edit
        try:
            wp = self._ensure_waypoint_index().user.edit(
                e["id"], lat=e["lat"], lon=lon, comment=e["comment"])
            self._wpt_info = wp
            self._message = "SAVED"
        except fp_waypoints.WaypointError as ex:
            self._message = str(ex)
        self._uwpt_edit = None
        self.update()

    def _user_wpt_delete_request(self, wp):
        active_idents = [w.id for w in self._plan.waypoints]
        try:
            self._ensure_waypoint_index().user.delete(wp.id, active_idents=active_idents)
            self._message = "DELETED"
            self._close_wpt_info()
        except fp_waypoints.WaypointError as e:
            self._message = str(e)
            self.update()

    # -- physical keyboard (FP5b) ---------------------------------------------
    def _keyboard_active(self):
        """Whether an ident-entry surface is open and ``keyboard`` wants the
        widget to consume A-Z/0-9/control keys instead of letting them
        propagate to ``hmi/keys.py`` bindings (brief 3.5)."""
        if not self.keyboard:
            return False
        if self._modal is not None:
            return True
        if self._page == "entry":
            return True
        if self._page == "dto" and self._dto_tab == "Waypoint":
            return True
        return False

    def _keyboard_char(self, ch):
        if self._modal is not None:
            self._modal_key(ch)
        elif self._page in ("entry", "dto"):
            self._entry_key(ch)

    def _keyboard_backspace(self):
        if self._modal is not None:
            self._modal_backspace()
        else:
            self._entry_backspace()

    def _keyboard_enter(self):
        if self._modal is not None:
            self._modal_enter()
            return
        if self._entry_nav_index is not None:
            choices = self._entry_dupe_choices or self._entry_candidates()
            if 0 <= self._entry_nav_index < len(choices):
                wp = choices[self._entry_nav_index]
                self._entry_nav_index = None
                if self._entry_dupe_choices:
                    self._choose_duplicate(wp)
                else:
                    self._select_waypoint(wp)
                return
        if self._page in ("entry", "dto"):
            self._entry_enter()

    def _keyboard_escape(self):
        if self._modal is not None:
            self._modal_do_cancel()
        elif self._entry_dupe_choices:
            self._cancel_dupe_chooser()
        elif self._page == "dto":
            self._close_dto()
        elif self._page == "entry":
            self._entry_cancel()

    def _keyboard_nav(self, direction):
        if self._modal is not None:
            return
        choices = self._entry_dupe_choices or self._entry_candidates()
        if not choices:
            return
        idx = self._entry_nav_index if self._entry_nav_index is not None else -1
        self._entry_nav_index = (idx + direction) % len(choices)
        self.update()

    def _keyboard_tab(self):
        if self._modal is not None:
            return
        if self._page == "entry":
            i = ENTRY_TABS.index(self._entry_tab)
            self._select_entry_tab(ENTRY_TABS[(i + 1) % len(ENTRY_TABS)])
        elif self._page == "dto":
            i = DTO_TABS.index(self._dto_tab)
            self._select_dto_tab(DTO_TABS[(i + 1) % len(DTO_TABS)])

    def keyPressEvent(self, event):
        if not self._keyboard_active():
            event.ignore()
            super().keyPressEvent(event)
            return
        key = event.key()
        text = event.text()
        if key == Qt.Key.Key_Escape:
            self._keyboard_escape()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._keyboard_enter()
        elif key == Qt.Key.Key_Backspace:
            self._keyboard_backspace()
        elif key == Qt.Key.Key_Up:
            self._keyboard_nav(-1)
        elif key == Qt.Key.Key_Down:
            self._keyboard_nav(1)
        elif key == Qt.Key.Key_Tab:
            self._keyboard_tab()
        elif text and (text.isalnum() or text in ".-") and len(text) == 1:
            self._keyboard_char(text.upper())
        else:
            event.ignore()
            super().keyPressEvent(event)
            return
        event.accept()

    # -- encoder HMI protocol (FP5c) ------------------------------------------
    # The screen-level controller (screens/screenbuilder_encoder.py) moves the
    # highlight between instruments; a push on this one calls enc_select and
    # from then on every turn/push lands here until a method returns False.
    def enc_selectable(self):
        return True

    def enc_highlight(self, onoff):
        self._enc_highlighted = bool(onoff)
        if not onoff:
            # The controller drops control on timeout and on a False return;
            # either way the next enc_select starts from the page defaults.
            self._enc_active = False
            self._enc_editing = False
            self._enc_surface_sig = None
        self.update()

    def enc_select(self):
        self._enc_active = True
        self._enc_surface_sig = None
        self._enc_focus = None
        self._enc_editing = False
        if self._bridge.available:
            self._enc_prepare()
        self.update()
        return True

    def enc_changed(self, data):
        if not self._bridge.available:
            return True
        ring = self._enc_prepare()
        if self._enc_editing:
            self._enc_scroll_char(int(data))
        elif ring:
            slots = self._enc_slots(ring)
            cur = slots.index(self._enc_focus) if self._enc_focus in slots else 0
            self._enc_focus = slots[(cur + int(data)) % len(slots)]
        self._enc_settle()
        return True

    def enc_clicked(self):
        if not self._bridge.available:
            return True
        ring = self._enc_prepare()
        if self._enc_editing:
            self._enc_field_push(ring)
        elif self._enc_focus is None:
            if self._enc_base_page() == "fpl":
                self._enc_direct_to_shortcut()
        elif 0 <= self._enc_focus < len(ring):
            kind, _rect, callback = ring[self._enc_focus]
            if kind == "field":
                self._enc_start_editing()
            else:
                callback()
        self._enc_settle()
        return True

    def enc_outer_changed(self, data):
        """Outer ring: on an ident field, move the cursor between character
        positions (the GNX outer knob); anywhere else, walk the focus ring
        exactly as the inner ring does."""
        if not self._bridge.available:
            return True
        self._enc_prepare()
        if self._enc_editing:
            last = min(len(self._entry_field), 9)
            self._enc_cursor = max(0, min(last, self._enc_cursor + int(data)))
            self._enc_settle()
            return True
        return self.enc_changed(data)

    def enc_long_clicked(self):
        """Back one level: close the topmost overlay, else leave the page,
        else (FPL page, nothing open) hand the knob back to the screen."""
        if not self._bridge.available:
            return False
        self._enc_prepare()
        if not self._enc_back():
            return False
        self._enc_settle()
        return True

    # -- encoder internals -----------------------------------------------------
    def _enc_base_page(self):
        return self._page if self._bridge.available else "fpl"

    def _enc_refresh(self):
        """Re-run paint offscreen so the tap targets describe the state as it
        is NOW -- the last real paint may predate the action that opened a
        menu or changed page, and nothing guarantees a repaint in between
        two encoder events."""
        img = QImage(max(1, self.width()), max(1, self.height()),
                     QImage.Format.Format_ARGB32_Premultiplied)
        try:
            self._paint(img)
        except Exception:
            logger.warning("flight_plan: encoder refresh paint error", exc_info=True)

    def _enc_ring(self):
        """The focusable elements of the topmost layer, in paint order, as
        ``(kind, rect, callback)``. The on-screen keypad is left out when an
        ident field is up: the knob edits the field directly."""
        start = self._enc_layer_start
        field = self._enc_field if start == 0 else None
        ring = [("field", field[0], None)] if field is not None else []
        for target, kind in zip(self._tap_targets[start:], self._tap_kinds[start:]):
            if field is not None and kind == "key":
                continue
            x, y, w, h, callback = target
            ring.append((kind, QRectF(x, y, w, h), callback))
        return ring

    def _enc_slots(self, ring):
        # The FPL page proper also has a "nothing focused" position -- where
        # a push is the Direct-To shortcut (brief 3.5, guide 3-45).
        slots = list(range(len(ring)))
        if self._enc_base_page() == "fpl" and self._enc_layer_start == 0:
            slots.insert(0, None)
        return slots

    def _enc_surface(self):
        """Identity of what is on screen; when it changes, the focus resets to
        the new surface's default instead of pointing into a stale list."""
        picker = self._airway_picker
        return (self._enc_base_page(), self._row_menu_index, self._role_menu_open,
                self._menu_open, self._confirm, self._wpt_info is not None,
                self._modal is not None, None if picker is None else picker["stage"],
                bool(self._entry_dupe_choices), self._catalog_row_menu,
                self._catalog_confirm is not None, self._dto_tab,
                self._dto_target is not None, self._seg_menu, self._seg_fixes,
                self._seg_fix_menu)

    def _enc_prepare(self):
        self._enc_refresh()
        ring = self._enc_ring()
        sig = self._enc_surface()
        if sig != self._enc_surface_sig:
            self._enc_surface_sig = sig
            self._enc_apply_default(ring)
        elif self._enc_focus is not None and self._enc_focus >= len(ring):
            self._enc_focus = len(ring) - 1 if ring else None
        if self._enc_editing and not (ring and ring[0][0] == "field"):
            self._enc_editing = False
        return ring

    def _enc_settle(self):
        # Re-derive focus against what the action just opened, so the next
        # real paint draws the ring on the new surface rather than an index
        # into the old one.
        self._enc_prepare()
        self.update()

    def _enc_apply_default(self, ring):
        self._enc_editing = False
        self._enc_focus = None
        kinds = [k for k, _r, _c in ring]
        if self._enc_layer_start == 0:
            page = self._enc_base_page()
            if page == "fpl":
                return
            if page == "dto" and "activate" in kinds and self._dto_target is not None:
                self._enc_focus = kinds.index("activate")
                return
            if "field" in kinds:
                self._enc_focus = kinds.index("field")
                self._enc_start_editing()
                return
            if "row" in kinds:
                self._enc_focus = kinds.index("row")
                return
        elif "no" in kinds:
            # A confirm box defaults to its safe answer.
            self._enc_focus = kinds.index("no")
            return
        self._enc_focus = 0 if ring else None

    def _enc_start_editing(self):
        self._enc_editing = True
        self._enc_cursor = len(self._entry_field)

    def _enc_scroll_char(self, data):
        field = self._entry_field
        cur = self._enc_cursor
        ch = field[cur] if cur < len(field) else " "
        # Only the last character may scroll to blank (which deletes it). A
        # character with more after it skips the blank, so spinning through
        # the set never truncates the rest of the ident -- reachable only
        # with the outer ring, which can put the cursor mid-field.
        charset = ENC_CHARSET if cur >= len(field) - 1 else ENC_CHARSET.rstrip(" ")
        idx = charset.index(ch) if ch in charset else len(charset) - 1
        new = charset[(idx + data) % len(charset)]
        if new == " ":
            field = field[:cur]
        elif cur < len(field):
            field = field[:cur] + new + field[cur + 1:]
        elif len(field) < 10:
            field = field + new
        self._entry_field = field
        self._entry_message = ""
        self._entry_nav_index = None

    def _enc_field_push(self, ring):
        if self.enc_has_outer and self._entry_field:
            # The outer ring owns the cursor: a push is always Enter.
            self._entry_enter()
            return
        if self._enc_cursor < len(self._entry_field):
            # A character is under the cursor: keep it and move on.
            self._enc_cursor += 1
            return
        if self._entry_field:
            # Blank at the cursor: accept, taking the FastFind prediction.
            self._entry_enter()
            return
        # Nothing typed: hand the turn back to the ring (tabs, rows, X).
        self._enc_editing = False
        self._enc_focus = 1 if len(ring) > 1 else 0

    def _enc_direct_to_shortcut(self):
        """Push with nothing focused on the FPL page: open Direct To with the
        active waypoint pre-selected, so a second push activates it."""
        self._open_dto_page()
        active_leg = self._engine_value("FPLACTLEG")
        wps = self._plan.waypoints
        if active_leg and 0 < int(active_leg) <= len(wps):
            idx = int(active_leg) - 1
            self._dto_tab = "FPL"
            self._dto_target = ("fpl", idx, wps[idx])

    def _enc_back(self):
        """Returns False when there is nothing left to back out of."""
        if self._modal is not None:
            self._modal_do_cancel()
        elif self._entry_dupe_choices:
            self._cancel_dupe_chooser()
        elif self._row_menu_index is not None:
            self._close_row_menu()
        elif self._seg_menu is not None:
            self._close_seg_menu()
        elif self._wpt_info is not None and self._seg_fixes is not None:
            self._close_wpt_info()
        elif self._seg_fix_menu is not None:
            self._close_seg_fix_menu()
        elif self._seg_fixes is not None:
            self._close_seg_fixes()
        elif self._menu_open:
            self._close_menu()
        elif self._wpt_info is not None:
            self._close_wpt_info()
        elif self._airway_picker is not None:
            self._close_airway_picker()
        elif self._catalog_row_menu is not None:
            self._close_catalog_row_menu()
        elif self._catalog_confirm is not None:
            self._catalog_confirm_no()
        elif self._page == "entry":
            self._entry_cancel()
        elif self._page == "dto":
            self._close_dto()
        elif self._page == "catalog":
            self._close_catalog()
        else:
            return False
        return True

    def _paint_enc_focus(self, p, w, h):
        if not (self._enc_highlighted or self._enc_active):
            return
        pen = QPen(QColor(_ENC_FOCUS_COLOR))
        pen.setWidthF(3.0)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        if not self._enc_active:
            p.drawRect(QRectF(1.5, 1.5, w - 3, h - 3))
            return
        ring = self._enc_ring()
        if self._enc_focus is None or not (0 <= self._enc_focus < len(ring)):
            return
        kind, rect, _callback = ring[self._enc_focus]
        p.drawRect(rect.adjusted(2, 2, -2, -2))
        if kind == "field" and self._enc_editing and self._enc_field is not None:
            frect, font, x0 = self._enc_field
            p.setFont(font)
            fm = p.fontMetrics()
            field = self._entry_field
            cx = x0 + fm.horizontalAdvance(field[:self._enc_cursor])
            ch = field[self._enc_cursor] if self._enc_cursor < len(field) else "W"
            cw = fm.horizontalAdvance(ch)
            y = frect.top() + frect.height() * 0.5 + fm.height() * 0.5
            p.drawLine(QPointF(cx, y), QPointF(cx + cw, y))

    # -- input dispatch ------------------------------------------------------
    def _tap(self, x, y, w, h, callback, kind=None):
        self._tap_targets.append((x, y, w, h, callback))
        self._tap_kinds.append(kind)

    def mousePressEvent(self, event):
        # Any tap dismisses the toast; a callback that raises a new one below
        # sets it again (and restarts the timer).
        self._clear_toast()
        x, y = event.pos().x(), event.pos().y()
        for tx, ty, tw, th, callback in reversed(self._tap_targets):
            if tx <= x <= tx + tw and ty <= y <= ty + th:
                callback()
                event.accept()
                return
        super().mousePressEvent(event)

    # -- painting -------------------------------------------------------------
    def _font_scale(self):
        """Multiplier applied to every font size: user x fit.

        user -- ``font_percent`` normalised like
        ``screenbuilder_preferences.normalize_font_percent`` (a value > 1 is a
        whole-number percent, so 80 and 0.8 both mean 80%); unset, zero,
        negative or non-numeric means 1.0. Inlined rather than imported to keep
        pyefis.screens out of this module's imports (import cycle).
        fit -- ``min(1, (w/h) / _FONT_FIT_ASPECT)``: shrinks text in a pane
        taller than it is wide so it stays inside its width-fraction rects;
        exactly 1.0 for square/landscape panes. Only fonts scale -- geometry
        and tap targets never do."""
        try:
            user = float(self.font_percent) if self.font_percent is not None else 1.0
        except (TypeError, ValueError):
            user = 1.0
        if not math.isfinite(user) or user <= 0:
            user = 1.0
        elif user > 1.0:
            user /= 100.0
        w, h = self.width(), self.height()
        fit = 1.0 if h <= 0 else min(1.0, (w / h) / _FONT_FIT_ASPECT)
        return user * fit

    def _px_per_mm(self):
        """Pixels per millimetre on the panel this widget is drawn on.

        The screen geometry lives on the main window (``screen.parent``), which
        is also where the configured ``screenDiagonalInches`` lands. Every
        lookup is defensive: this runs inside paint, and an instrument built
        without the usual parent chain (tests, the twin exporter) must still
        render rather than raise.
        """
        main = getattr(getattr(self, "parent", None), "parent", None)
        qscreen = None
        try:
            qscreen = self.screen()
        except Exception:
            qscreen = None
        return display_metrics.pixels_per_mm(
            getattr(main, "screenWidth", None),
            getattr(main, "screenHeight", None),
            getattr(main, "screenDiagonalInches", None),
            qscreen,
        )

    def _row_h_cap(self):
        """Tallest a list row may be, in pixels, from the physical target.

        The previous cap was ``header_h`` -- 0.16 x the pane height, which came
        to 158 px on a 993 px pane and rendered four grotesque rows. Row height
        drives the icon and the row font, and neither is touched by
        font_percent (see _font_scale: only fonts scale, geometry never does),
        so no text setting could correct it.

        The floor keeps a row usable if the physical information is wrong or
        missing; the list still shrinks rows below this when a long plan needs
        the space, because the caller takes a min() against the available area.
        """
        try:
            mm = float(self.row_height_mm)
        except (TypeError, ValueError):
            mm = 14.0
        if not math.isfinite(mm) or mm <= 0:
            mm = 14.0
        return max(24.0, mm * self._px_per_mm())

    def _chrome_h(self, h, units, max_fraction):
        """Height of a chrome band -- a header, footer or tab strip -- in px.

        Physical for the same reason the rows are. A band holds one line of
        text or a row of soft keys, and how tall that has to be is a property
        of the glass and the finger, not of the pane it happens to sit in.
        These were pane fractions (0.16 h for the FPL header, 0.10 h for its
        footer), which on a 993 px pane spent 257 px of chrome on ~20 px of
        text and pushed the list into what was left.

        *units* is a multiple of the physical row height, so the whole
        instrument scales together: a header is worth about one and a half
        rows, a soft-key footer a little over one, a tab strip one.

        Clamped both ways. *max_fraction* keeps a short pane from spending
        itself entirely on chrome -- the list is the point of the page -- and
        the floor keeps a band from collapsing if the physical data is absent
        and the nominal DPI is far off.
        """
        return max(16.0, min(units * self._row_h_cap(), h * max_fraction))

    def _px(self, value, minimum):
        """Pixel size for a font nominally *value* px, scaled by
        ``_font_scale()`` and floored at *minimum* (the original per-site
        legibility floors are kept as they were)."""
        return max(minimum, int(value * self._font_scale()))

    def paintEvent(self, event):
        try:
            self._paint()
        except Exception:
            logger.warning("flight_plan: paint error", exc_info=True)

    def _paint(self, device=None):
        if self._page not in _INSTRUMENT_PAGES:
            self._page = self.default_page if self.default_page in _INSTRUMENT_PAGES else "fpl"
        self._sync_keyboard_focus()
        self._tap_targets = []
        self._tap_kinds = []
        self._enc_layer_start = 0
        self._enc_field = None
        p = QPainter(self if device is None else device)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            w, h = self.width(), self.height()
            p.fillRect(0, 0, w, h, QColor("#000000"))
            page = self._page if self._bridge.available else "fpl"
            if page == "entry":
                self._paint_entry(p, w, h)
            elif page == "dto":
                self._paint_dto(p, w, h)
            elif page == "catalog":
                self._paint_catalog(p, w, h)
            else:
                self._paint_fpl(p, w, h)
            self._paint_enc_focus(p, w, h)
        finally:
            p.end()

    def _sync_keyboard_focus(self):
        active = self._keyboard_active()
        if active and not self.hasFocus():
            self.setFocus()
        elif not active and self.hasFocus():
            self.clearFocus()

    # -- FPL page --------------------------------------------------------------
    def _paint_fpl(self, p, w, h):
        interactive = self._bridge.available
        # 2.0 because this header draws TWO lines -- name/badge/remaining in
        # the top half, approach state or the gateway warning in the bottom --
        # so it is worth two rows. The footer is a soft-key touch row: 1.3
        # rows is ~18 mm, comfortably above a fingertip.
        header_h = int(self._chrome_h(h, 2.0, 0.26))
        footer_h = int(self._chrome_h(h, 1.3, 0.18))

        self._paint_header(p, w, header_h, interactive)
        self._paint_list(p, w, header_h, h - footer_h,
                         self._row_h_cap(), interactive)
        self._paint_footer(p, w, h - footer_h, footer_h, interactive)

        if self._row_menu_index is not None:
            self._paint_row_menu(p, w, h)
        elif self._seg_menu is not None:
            self._paint_seg_menu(p, w, h)
        elif self._menu_open:
            self._paint_menu(p, w, h)
        elif self._seg_fixes is not None or self._wpt_info is not None:
            # WPT Info opened from the Show Fixes sheet stacks on top of it.
            if self._seg_fixes is not None:
                self._paint_seg_fixes(p, w, h)
                if self._seg_fix_menu is not None:
                    self._paint_seg_fix_menu(p, w, h)
            if self._wpt_info is not None:
                self._paint_wpt_info(p, w, h)
                if self._modal is not None:
                    self._paint_modal(p, w, h)
        elif self._seg_fix_menu is not None:
            self._paint_seg_fix_menu(p, w, h)
        elif self._airway_picker is not None:
            self._paint_airway_picker(p, w, h)

        if self._message:
            self._paint_toast(p, w, h, self._message)

    def _paint_header(self, p, w, header_h, interactive):
        f = QFont(self.font_family)
        f.setPixelSize(self._px(int(header_h * 0.32), 10))
        p.setFont(f)

        name = self._plan.name or self._plan.default_name() or "NO FLT PLAN"
        p.setPen(QPen(QColor("#ffffff")))
        p.drawText(QRectF(4, 2, w * 0.4, header_h * 0.5),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)

        badge = self._state_badge()
        if badge:
            p.setPen(QPen(QColor("#ffaa00")))
            p.drawText(QRectF(w * 0.42, 2, w * 0.2, header_h * 0.5),
                       Qt.AlignmentFlag.AlignCenter, badge)

        remdis = self._engine_value("FPLREMDIS")
        if remdis is not None:
            rem_text = f"{remdis:.0f} NM  {self._fmt_ete(self._engine_value('FPLREMETE'))}"
            p.setPen(QPen(QColor("#00ffff")))
            p.drawText(QRectF(w * 0.60, 2, w * 0.38, header_h * 0.5),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, rem_text)

        if not interactive:
            p.setPen(QPen(QColor("#ff0000")))
            p.drawText(QRectF(4, header_h * 0.52, w - 8, header_h * 0.46),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       "FPL: GATEWAY KEYS MISSING")
            return

        apr_text = self._approach_text()
        if apr_text:
            p.setPen(QPen(QColor("#00ff00")))
            p.drawText(QRectF(4, header_h * 0.52, w * 0.5, header_h * 0.46),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, apr_text)

        if self._engine_value("FPLINTEG", True) is False:
            p.setPen(QPen(QColor("#ff0000")))
            p.drawText(QRectF(w * 0.55, header_h * 0.52, w * 0.42, header_h * 0.46),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "LOI")

    def _column_text(self, col, i, active_idx):
        """Column *col* of flat fix *i*. DTK and DIS are the leg INTO the fix
        (the leg you fly to reach it), so the active TO row carries the
        engine's ``FPLCRS``; CUM is the distance from the first fix to it."""
        try:
            if col in ("DTK", "DIS"):
                leg = self._leg_in(i)
                if leg is None:
                    return ""
                return f"{leg[0]:03.0f}°" if col == "DTK" else f"{leg[1]:.0f}"
            if col == "CUM":
                return f"{self._plan.cumulative(i):.0f}"
            if col == "ETE":
                return self._fmt_ete(self._engine_value("WPETE")) if i == active_idx else ""
            if col == "ETA":
                return ""
        except fp_model.FlightPlanError:
            return ""
        return ""

    def _segment_column_text(self, col, k, active_idx):
        """A segment row's columns: DTK blank (an airway changes course), DIS
        the segment's own length, CUM to its exit fix."""
        try:
            if col == "DIS":
                return f"{self._segment_length(k):.0f}"
            if col == "CUM":
                return f"{self._plan.cumulative(self._plan.segment_span(k)[1]):.0f}"
            if col == "ETE":
                return (self._fmt_ete(self._engine_value("WPETE"))
                        if self._segment_active(k, active_idx) else "")
        except fp_model.FlightPlanError:
            return ""
        return ""

    def _draw_type_icon(self, p, cx, cy, r, wtype):
        p.save()
        color = p.pen().color()
        p.setBrush(QBrush(color))
        p.setPen(Qt.PenStyle.NoPen)
        if wtype == "airport":
            p.drawEllipse(QRectF(cx - r, cy - r, 2 * r, 2 * r))
        elif wtype == "vor":
            p.drawRect(QRectF(cx - r, cy - r, 2 * r, 2 * r))
        elif wtype == "user":
            p.drawPolygon(QPolygonF([QPointF(cx, cy - r), QPointF(cx + r, cy),
                                      QPointF(cx, cy + r), QPointF(cx - r, cy)]))
        else:
            p.drawPolygon(QPolygonF([QPointF(cx, cy - r), QPointF(cx + r, cy + r),
                                      QPointF(cx - r, cy + r)]))
        p.restore()

    def _columns(self):
        cols = [c.strip().upper() for c in (self.columns or "").split(",") if c.strip()]
        return [c for c in cols if c in COLUMN_CHOICES] or ["DTK", "DIS", "CUM"]

    @staticmethod
    def _column_rects(w, cols):
        col_w = (w * 0.55) / len(cols)
        return [(w * 0.42 + n * col_w, col_w) for n in range(len(cols))]

    def _paint_column_headers(self, p, w, top, hh, row_h, cols):
        """RS3: the list finally says what its numbers are."""
        _, _, lx = self._row_icon_geometry(row_h)
        f = QFont(self.font_family)
        f.setPixelSize(self._px(int(row_h * 0.36), 8))
        p.setFont(f)
        p.setPen(QPen(QColor("#9a9a9a")))
        p.drawText(QRectF(lx, top, w * 0.4, hh),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "WPT / SEGMENT")
        for c, (cx, cw) in zip(cols, self._column_rects(w, cols)):
            p.drawText(QRectF(cx, top, cw, hh),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, c)
        p.setPen(QPen(QColor("#333333")))
        p.drawLine(QPointF(0, top + hh - 1), QPointF(w, top + hh - 1))

    def _list_metrics(self, top, bottom, max_row_h, n_rows):
        """``(header_h, row_h)``. The header strip is half a physical row;
        rows size off the count of DISPLAY rows, not of fixes, so a folded
        airway never steals the height every other row gets."""
        hh = max(14.0, max_row_h * 0.5)
        row_h = max(14, min((bottom - top - hh) / max(n_rows, 1), max_row_h))
        return hh, row_h

    def _paint_list(self, p, w, top, bottom, max_row_h, interactive):
        rows = self._plan.waypoints
        if not rows:
            p.setPen(QPen(QColor("#808080")))
            f = QFont(self.font_family)
            f.setPixelSize(self._px(min(int((bottom - top) * 0.08), int(max_row_h * 0.5)), 10))
            p.setFont(f)
            p.drawText(QRectF(0, top, w, bottom - top),
                       Qt.AlignmentFlag.AlignCenter, "NO WAYPOINTS")
            return

        active_idx = self._active_index()
        cols = self._columns()
        display = self._display_rows(active_idx)
        hh, row_h = self._list_metrics(top, bottom, max_row_h, len(display))
        self._paint_column_headers(p, w, top, hh, row_h, cols)

        f = QFont(self.font_family)
        f.setPixelSize(self._px(int(row_h * 0.5), 9))
        y = top + hh
        nest_top = None
        for row in display:
            rh = min(row_h, bottom - y)
            if rh <= 0:
                break
            p.setFont(f)
            kind = row[0]
            if kind == "wpt":
                self._paint_one_row(p, w, y, rh, row[1], rows[row[1]], active_idx, cols,
                                    interactive)
            elif kind == "seg":
                self._paint_segment_row(p, w, y, rh, row[1], active_idx, cols, interactive)
                nest_top = y + rh
            elif kind == "fix":
                self._paint_nested_fix_row(p, w, y, rh, row[1], row[2], active_idx, cols,
                                           interactive)
                self._paint_nest_guide(p, rh, nest_top, y)
            elif kind == "fold":
                self._paint_fold_row(p, w, y, rh, row[1], row[2], interactive)
                self._paint_nest_guide(p, rh, nest_top, y)
            y += rh

    def _row_icon_geometry(self, rh):
        # Centre must clear its own radius: the original
        # `6 + rh*0.15` against radius `rh*0.28` puts the left edge at
        # `6 - rh*0.13`, negative for any rh > 46, which is why the type
        # icons clipped off the left of the widget at the old row sizes.
        ir = rh * 0.28
        icx = max(6 + rh * 0.15, ir + 2.0)
        # `rh * 0.5` assumed the old oversized icon; once rows are sane it
        # lands inside the icon, so take the icon's right edge.
        lx = max(rh * 0.5, icx + ir + 8.0)
        return ir, icx, lx

    def _nest_indent(self, rh):
        """How far a segment's working rows sit right of a plain row: one
        icon column, so the nested icons line up under the header's label."""
        ir, icx, lx = self._row_icon_geometry(rh)
        return lx - (icx - ir)

    def _paint_nest_guide(self, p, rh, nest_top, y):
        """The tree line: a vertical rule down from the segment header's icon
        and a short tick into each nested row."""
        if nest_top is None:
            return
        ir, icx, _ = self._row_icon_geometry(rh)
        mid = y + rh / 2
        p.save()
        p.setPen(QPen(QColor("#5a5a5a"), 2))
        p.drawLine(QPointF(icx, y if y > nest_top else nest_top - rh * 0.2), QPointF(icx, mid))
        p.drawLine(QPointF(icx, mid), QPointF(icx + self._nest_indent(rh) - ir - 4, mid))
        p.restore()

    def _paint_row_columns(self, p, w, y, rh, cols, texts):
        for (cx, cw), text in zip(self._column_rects(w, cols), texts):
            p.drawText(QRectF(cx, y, cw, rh),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, text)

    def _paint_one_row(self, p, w, y, rh, i, wp, active_idx, cols, interactive):
        p.setPen(QPen(QColor(self._row_color(i, active_idx))))
        ir, icx, lx = self._row_icon_geometry(rh)
        self._draw_type_icon(p, icx, y + rh / 2, ir, wp.type)

        label = wp.id
        role = ROLE_ABBREV.get(wp.role, "")
        if role:
            label = f"{label} {role}"
        p.drawText(QRectF(lx, y, w * 0.4 - lx, rh),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)
        self._paint_row_columns(p, w, y, rh, cols,
                                [self._column_text(c, i, active_idx) for c in cols])
        if interactive:
            self._tap(0, y, w, rh, (lambda idx=i: self._open_row_menu(idx)), "row")

    def _draw_airway_icon(self, p, cx, cy, r):
        """A segment's glyph: a short dog-leg route through three fixes, so
        it never reads as one of the fix-type shapes."""
        p.save()
        color = p.pen().color()
        p.setPen(QPen(color, max(2.0, r * 0.22)))
        # Spans 0.8 r each side so the end dots (0.18 r) and the pen stay
        # inside the icon box every other row type uses -- at full r they
        # clipped the pane's left edge and touched the label.
        a = r * 0.8
        pts = [QPointF(cx - a, cy + a * 0.55), QPointF(cx - a * 0.15, cy - a * 0.55),
               QPointF(cx + a * 0.35, cy + a * 0.25), QPointF(cx + a, cy - a * 0.55)]
        p.drawPolyline(QPolygonF(pts))
        p.setBrush(QBrush(color))
        p.setPen(Qt.PenStyle.NoPen)
        for pt in pts:
            p.drawEllipse(pt, r * 0.18, r * 0.18)
        p.restore()

    def _paint_segment_row(self, p, w, y, rh, k, active_idx, cols, interactive):
        """One airway: ident and entry -> exit on the first line, the fix
        count and MEA beneath it in a smaller face. Same geometry whether or
        not the segment is active, so opening it never shifts the row."""
        seg = self._plan.segments[k]
        color = QColor(self._segment_color(k, active_idx))
        p.setPen(QPen(color))
        ir, icx, lx = self._row_icon_geometry(rh)
        self._draw_airway_icon(p, icx, y + rh / 2, ir)

        top_h = rh * 0.58
        base = p.font()
        bold = QFont(base)
        bold.setBold(True)
        p.setFont(bold)
        ident_w = p.fontMetrics().horizontalAdvance(seg.ident + "  ")
        p.drawText(QRectF(lx, y, w * 0.42 - lx, top_h),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, seg.ident)
        p.setFont(base)
        p.drawText(QRectF(lx + ident_w, y, w * 0.42 - lx - ident_w, top_h),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
                   f"{seg.entry} → {seg.exit}")

        detail = f"{len(seg.legs)} fixes"
        mea = self._segment_mea(k)
        if mea is not None:
            detail += f"   MEA {mea}"
        small = QFont(base)
        small.setPixelSize(max(9, int(base.pixelSize() * 0.86)))
        p.setFont(small)
        dim = QColor(color)
        dim.setAlpha(190)
        p.setPen(QPen(dim))
        p.drawText(QRectF(lx, y + top_h, w * 0.42 - lx, rh - top_h),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, detail)
        p.setFont(base)
        p.setPen(QPen(color))
        # Columns share line 1's baseline, so they read with the ident.
        for (cx, cw), c in zip(self._column_rects(w, cols), cols):
            p.drawText(QRectF(cx, y, cw, top_h),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom,
                       self._segment_column_text(c, k, active_idx))
        if interactive:
            self._tap(0, y, w, rh, (lambda kk=k: self._open_seg_menu(kk)), "row")

    _NEST_ROLE_TEXT = {"from": "from", "to": "", "next": ""}

    def _paint_nested_fix_row(self, p, w, y, rh, i, role, active_idx, cols, interactive):
        wp = self._plan.waypoints[i]
        color = {"from": self.past_color, "to": self.active_color}.get(role, self.future_color)
        p.setPen(QPen(QColor(color)))
        ir, icx, lx = self._row_icon_geometry(rh)
        dx = self._nest_indent(rh)
        self._draw_type_icon(p, icx + dx, y + rh / 2, ir * 0.85, wp.type)
        label = wp.id
        if role == "from":
            label = f"{wp.id}  (from)"
        p.drawText(QRectF(lx + dx, y, w * 0.42 - lx - dx, rh),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)
        if role != "from":
            self._paint_row_columns(p, w, y, rh, cols,
                                    [self._column_text(c, i, active_idx) for c in cols])
        if interactive:
            self._tap(0, y, w, rh, (lambda idx=i: self._open_seg_fix_menu(idx)), "row")

    def _paint_fold_row(self, p, w, y, rh, k, n, interactive):
        ir, icx, lx = self._row_icon_geometry(rh)
        dx = self._nest_indent(rh)
        p.setPen(QPen(QColor("#00ffff")))
        p.drawText(QRectF(lx + dx, y, w * 0.9 - lx - dx, rh),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"+ {n} more  ▸")
        if interactive:
            self._tap(0, y, w, rh, (lambda kk=k: self._open_seg_fixes(kk)), "row")

    def _paint_footer(self, p, w, top, footer_h, interactive):
        p.setPen(QPen(QColor("#333333")))
        p.drawLine(0, top, w, top)
        labels = ("ADD WPT", "DIRECT TO", "CATALOG", "MENU")
        callbacks = (self._footer_add, self._footer_direct_to, self._footer_catalog,
                     self._footer_menu)
        seg = w / len(labels)
        f = QFont(self.font_family)
        f.setPixelSize(self._px(int(footer_h * 0.34), 9))
        p.setFont(f)
        p.setPen(QPen(QColor("#ffffff")))
        for i, label in enumerate(labels):
            x = i * seg
            p.drawText(QRectF(x, top, seg, footer_h), Qt.AlignmentFlag.AlignCenter, label)
            if interactive:
                self._tap(x, top, seg, footer_h, callbacks[i], "soft")

    # -- overlays ---------------------------------------------------------------
    def _paint_overlay_backdrop(self, p, w, h):
        p.fillRect(QRectF(0, 0, w, h), QColor(0, 0, 0, 160))
        # Everything registered from here on is the topmost layer: the
        # encoder ring walks only that, never the page dimmed behind it.
        self._enc_layer_start = len(self._tap_targets)

    def _menu_scroll_by(self, key, delta):
        n_items, offset = self._menu_scroll.get(key, (0, 0))
        self._menu_scroll[key] = (n_items, offset + delta)
        self.update()

    def _paint_menu_list(self, p, w, h, items, on_cancel, scroll_key=None, title=None):
        """Popup menu of *items* (label, callback) plus a trailing Cancel row.

        Row height is physical (``_row_h_cap()``), not a fraction of the
        popup's own height -- an airway can carry dozens of exit fixes, and
        sizing text off ``h / len(items)`` (the previous approach) shrank it
        to unreadable as the list grew (AER-1605 follow-up, reported live by
        Bill against the V27 exit-fix list). When the list doesn't fit, it
        scrolls instead of shrinking further, with tappable up/down rows --
        this box is driven by touch, no wheel or drag-scroll available.
        """
        n_items = len(items)
        box_w = w * 0.6
        box_x = (w - box_w) / 2
        box_top = h * 0.12
        avail_h = h * 0.76
        item_h = max(1.0, min(self._row_h_cap(), avail_h))

        # Budget: Cancel always gets one row. The item list gets whatever is
        # left; if that isn't enough to show every item, two more rows are
        # spent on scroll arrows and the visible window shrinks to fit them.
        rows_free = max(0, int(avail_h / item_h) - 1)
        scrollable = n_items > rows_free
        visible_rows = max(1, min(n_items, rows_free - 2)) if scrollable else n_items
        box_rows = visible_rows + (2 if scrollable else 0) + 1

        # A long list (a big airway's exit-fix picker) can force rows_free
        # to 0-2: the floor of one visible row plus, when scrollable, the two
        # arrow rows and Cancel still add up to more rows than the physical
        # cap leaves room for. Re-deriving item_h from box_rows keeps the
        # popup inside avail_h instead of drawing past the bottom of the pane
        # (AER-1605 follow-up -- Bill's V27 exit-fix list overflowed off the
        # visible area before he could reach a fix past the fold).
        if box_rows * item_h > avail_h:
            item_h = avail_h / box_rows

        offset = 0
        key = scroll_key or "menu"
        if scrollable:
            stored_n, stored_offset = self._menu_scroll.get(key, (n_items, 0))
            offset = stored_offset if stored_n == n_items else 0
            offset = max(0, min(offset, n_items - visible_rows))
            self._menu_scroll[key] = (n_items, offset)
        elif key in self._menu_scroll:
            self._menu_scroll[key] = (n_items, 0)

        f = QFont(self.font_family)
        f.setPixelSize(self._px(int(item_h * 0.4), 10))
        p.setFont(f)
        box_h = item_h * box_rows
        if title:
            # Names what the menu acts on (RS3: which airway). Sits above
            # the box so the item rows keep their physical pitch.
            p.setPen(QPen(QColor("#ffffff")))
            p.drawText(QRectF(box_x - w * 0.1, box_top - item_h, box_w + w * 0.2, item_h),
                       Qt.AlignmentFlag.AlignCenter, title)
        p.setPen(QPen(QColor("#ffffff")))
        p.setBrush(QBrush(QColor("#202020")))
        p.drawRect(QRectF(box_x, box_top, box_w, box_h))

        y = box_top
        if scrollable:
            can_up = offset > 0
            p.setPen(QPen(QColor("#00ffff" if can_up else "#505050")))
            p.drawText(QRectF(box_x, y, box_w, item_h), Qt.AlignmentFlag.AlignCenter, "▲")
            if can_up:
                self._tap(box_x, y, box_w, item_h,
                           (lambda k=key, d=-visible_rows: self._menu_scroll_by(k, d)))
            y += item_h

        for label, callback in items[offset:offset + visible_rows]:
            p.setPen(QPen(QColor("#000000")))
            p.drawRect(QRectF(box_x + 2, y + 2, box_w - 4, item_h - 4))
            p.setPen(QPen(QColor("#00ffff")))
            p.drawText(QRectF(box_x, y, box_w, item_h), Qt.AlignmentFlag.AlignCenter, label)
            self._tap(box_x, y, box_w, item_h, callback, "row")
            y += item_h

        if scrollable:
            can_down = offset + visible_rows < n_items
            p.setPen(QPen(QColor("#00ffff" if can_down else "#505050")))
            p.drawText(QRectF(box_x, y, box_w, item_h), Qt.AlignmentFlag.AlignCenter, "▼")
            if can_down:
                self._tap(box_x, y, box_w, item_h,
                           (lambda k=key, d=visible_rows: self._menu_scroll_by(k, d)))
            y += item_h

        p.setPen(QPen(QColor("#ff8080")))
        p.drawText(QRectF(box_x, y, box_w, item_h), Qt.AlignmentFlag.AlignCenter, "Cancel")
        self._tap(box_x, y, box_w, item_h, on_cancel)

    def _paint_row_menu(self, p, w, h):
        self._paint_overlay_backdrop(p, w, h)
        if self._role_menu_open:
            items = [(ROLE_ABBREV.get(r) or "NONE", (lambda role=r: self._row_menu_set_role(role)))
                     for r in _ROLE_MENU_ORDER]
            self._paint_menu_list(p, w, h, items, self._close_row_menu, scroll_key="row_menu_role")
            return
        items = []
        for label, attr in _ROW_MENU_ITEMS:
            items.append((label, self._open_role_menu if attr is None else getattr(self, attr)))
        self._paint_menu_list(p, w, h, items, self._close_row_menu, scroll_key="row_menu")

    def _segment_title(self, k):
        seg = self._plan.segments[k]
        return f"{seg.ident}  {seg.entry} → {seg.exit}"

    def _paint_seg_menu(self, p, w, h):
        self._paint_overlay_backdrop(p, w, h)
        k = self._seg_menu
        first, _ = self._plan.segment_span(k)
        items = []
        for label, attr in _SEG_MENU_ITEMS:
            if attr == "_seg_menu_activate":
                label = f"Activate to {self._plan.waypoints[first].id}"
            items.append((label, getattr(self, attr)))
        self._paint_menu_list(p, w, h, items, self._close_seg_menu, scroll_key="seg_menu",
                              title=self._segment_title(k))

    def _paint_seg_fix_menu(self, p, w, h):
        self._paint_overlay_backdrop(p, w, h)
        i = self._seg_fix_menu
        items = [(label, getattr(self, attr)) for label, attr in _SEG_FIX_MENU_ITEMS]
        self._paint_menu_list(p, w, h, items, self._close_seg_fix_menu,
                              scroll_key="seg_fix_menu", title=self._plan.waypoints[i].id)

    def _seg_fixes_scroll_by(self, delta):
        self._menu_scroll_by("seg_fixes", delta)

    def _paint_seg_fixes(self, p, w, h):
        """Show Fixes: every fix of one airway, read-only, with the leg course
        (magnetic), distance and MEA of the leg into it. A tap on a fix opens
        the one-fix menu (Direct To, Activate Leg, WPT Info) -- per-fix access
        without putting every fix on the route list."""
        self._paint_overlay_backdrop(p, w, h)
        k = self._seg_fixes
        seg = self._plan.segments[k]
        first, last = self._plan.segment_span(k)
        active_idx = self._active_index()

        row_h = self._row_h_cap()
        box_x, box_w = w * 0.04, w * 0.92
        box_top = h * 0.06
        box_h = h * 0.88
        title_h = row_h
        head_h = row_h * 0.5
        foot_h = row_h
        list_top = box_top + title_h + head_h
        list_h = box_h - title_h - head_h - foot_h
        n = last - first + 1
        fit = max(1, int(list_h // row_h))
        scrollable = n > fit
        visible = max(1, fit - 1) if scrollable else n
        stored_n, offset = self._menu_scroll.get("seg_fixes", (n, 0))
        offset = max(0, min(offset if stored_n == n else 0, n - visible))
        self._menu_scroll["seg_fixes"] = (n, offset)

        p.setPen(QPen(QColor("#ffffff")))
        p.setBrush(QBrush(QColor("#202020")))
        p.drawRect(QRectF(box_x, box_top, box_w, box_h))

        f = QFont(self.font_family)
        f.setPixelSize(self._px(int(row_h * 0.5), 9))
        bold = QFont(f)
        bold.setBold(True)
        p.setFont(bold)
        p.drawText(QRectF(box_x + 12, box_top, box_w - 24, title_h),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._segment_title(k))
        small = QFont(f)
        small.setPixelSize(self._px(int(row_h * 0.36), 8))
        p.setFont(small)
        p.setPen(QPen(QColor("#9a9a9a")))
        if seg.cycle:
            p.drawText(QRectF(box_x + 12, box_top, box_w - 24, title_h),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       f"AIRAC {seg.cycle}")

        # FIX | CRS | DIS | MEA, columns right-aligned like the route list.
        col_x = [box_x + box_w * f_ for f_ in (0.40, 0.58, 0.76)]
        col_w = box_w * 0.18
        hy = box_top + title_h
        ir, icx, lx = self._row_icon_geometry(row_h)
        p.drawText(QRectF(box_x + lx, hy, box_w * 0.3, head_h),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "FIX")
        for x, label in zip(col_x, ("CRS", "DIS", "MEA")):
            p.drawText(QRectF(x, hy, col_w, head_h),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, label)
        p.setPen(QPen(QColor("#333333")))
        p.drawLine(QPointF(box_x, hy + head_h - 1), QPointF(box_x + box_w, hy + head_h - 1))

        y = list_top
        for i in range(first + offset, first + offset + visible):
            wp = self._plan.waypoints[i]
            color = self._row_color(i, active_idx)
            p.setFont(f)
            p.setPen(QPen(QColor(color)))
            self._draw_type_icon(p, box_x + icx, y + row_h / 2, ir * 0.85, wp.type)
            p.drawText(QRectF(box_x + lx, y, box_w * 0.4 - lx, row_h),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, wp.id)
            leg = self._leg_in(i) if i > first else None
            texts = ("", "", "") if leg is None else (
                f"{leg[0]:03.0f}°", f"{leg[1]:.0f}", self._mea_text(wp))
            for x, text in zip(col_x, texts):
                p.drawText(QRectF(x, y, col_w, row_h),
                           Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, text)
            self._tap(box_x, y, box_w, row_h, (lambda idx=i: self._open_seg_fix_menu(idx)), "row")
            y += row_h

        if scrollable:
            # Up and down share one row under the list, left and right.
            half = box_w / 2
            can_up, can_down = offset > 0, offset + visible < n
            for n_, (label, ok, d) in enumerate((("▲", can_up, -visible),
                                                 ("▼", can_down, visible))):
                rx = box_x + n_ * half
                p.setPen(QPen(QColor("#00ffff" if ok else "#505050")))
                p.drawText(QRectF(rx, y, half, row_h), Qt.AlignmentFlag.AlignCenter, label)
                if ok:
                    self._tap(rx, y, half, row_h, (lambda dd=d: self._seg_fixes_scroll_by(dd)))

        fy = box_top + box_h - foot_h
        p.setPen(QPen(QColor("#333333")))
        p.drawLine(QPointF(box_x, fy), QPointF(box_x + box_w, fy))
        p.setFont(f)
        p.setPen(QPen(QColor("#ffffff")))
        p.drawText(QRectF(box_x, fy, box_w, foot_h), Qt.AlignmentFlag.AlignCenter, "Close")
        self._tap(box_x, fy, box_w, foot_h, self._close_seg_fixes)

    def _paint_airway_picker(self, p, w, h):
        self._paint_overlay_backdrop(p, w, h)
        picker = self._airway_picker
        if picker["stage"] == "airway":
            items = [(ident, (lambda i=ident: self._airway_picker_pick_ident(i)))
                     for ident in picker["idents"]]
        else:
            items = []
            for leg in picker["legs"]:
                label = leg.fix_id
                if leg.min_alt_ft is not None or leg.max_alt_ft is not None:
                    lo = leg.min_alt_ft if leg.min_alt_ft is not None else "-"
                    hi = leg.max_alt_ft if leg.max_alt_ft is not None else "-"
                    label = f"{label}  {lo}-{hi}FT"
                pick = (self._airway_picker_pick_exit if picker["stage"] == "exit"
                        else self._segment_picker_pick)
                items.append((label, (lambda fid=leg.fix_id, f=pick: f(fid))))
        self._paint_menu_list(p, w, h, items, self._close_airway_picker,
                               scroll_key=f"airway_picker_{picker['stage']}")
        if picker["message"]:
            f = QFont(self.font_family)
            f.setPixelSize(self._px(int(h * 0.04), 10))
            p.setFont(f)
            p.setPen(QPen(QColor("#ff8080")))
            p.drawText(QRectF(0, h * 0.03, w, h * 0.08),
                       Qt.AlignmentFlag.AlignCenter, picker["message"])

    def _paint_confirm(self, p, w, h, text, on_yes):
        box_w, box_h = w * 0.6, h * 0.3
        box_x, box_y = (w - box_w) / 2, (h - box_h) / 2
        p.setBrush(QBrush(QColor("#202020")))
        p.setPen(QPen(QColor("#ffffff")))
        p.drawRect(QRectF(box_x, box_y, box_w, box_h))
        f = QFont(self.font_family)
        f.setPixelSize(self._px(int(box_h * 0.16), 10))
        p.setFont(f)
        p.drawText(QRectF(box_x, box_y, box_w, box_h * 0.5),
                   Qt.AlignmentFlag.AlignCenter, text)
        yes_rect = (box_x, box_y + box_h * 0.5, box_w / 2, box_h * 0.5)
        no_rect = (box_x + box_w / 2, box_y + box_h * 0.5, box_w / 2, box_h * 0.5)
        p.setPen(QPen(QColor("#ff8080")))
        p.drawText(QRectF(*yes_rect), Qt.AlignmentFlag.AlignCenter, "Yes")
        p.setPen(QPen(QColor("#80ff80")))
        p.drawText(QRectF(*no_rect), Qt.AlignmentFlag.AlignCenter, "No")
        self._tap(*yes_rect, on_yes)
        self._tap(*no_rect, self._close_menu, "no")

    def _paint_menu(self, p, w, h):
        self._paint_overlay_backdrop(p, w, h)
        if self._confirm:
            text = "Clear flight plan?" if self._confirm == "clear" else "Delete flight plan?"
            on_yes = self._menu_clear_confirm if self._confirm == "clear" else self._menu_delete_confirm
            self._paint_confirm(p, w, h, text, on_yes)
            return
        state = int(self._engine_value("FPLSTATE", 0) or 0)
        susp_label = "Resume" if state == 3 else "Suspend"
        items = [
            ("Invert", self._menu_invert),
            ("Store", self._menu_store),
            ("Clear", self._menu_clear_request),
            (susp_label, self._menu_suspend_resume),
            (f"CDI Scale ({self._cdi_scale_choice})", self._menu_cdi_scale),
            ("Delete", self._menu_delete_request),
        ]
        self._paint_menu_list(p, w, h, items, self._close_menu, scroll_key="menu")

    def _paint_wpt_info(self, p, w, h):
        self._paint_overlay_backdrop(p, w, h)
        wp = self._wpt_info
        box_w, box_h = w * 0.8, h * 0.6
        box_x, box_y = (w - box_w) / 2, (h - box_h) / 2
        p.setBrush(QBrush(QColor("#202020")))
        p.setPen(QPen(QColor("#ffffff")))
        p.drawRect(QRectF(box_x, box_y, box_w, box_h))

        ref_lat, ref_lon = self._aircraft_position()
        brg = fp_geo.initial_bearing(ref_lat, ref_lon, wp.lat, wp.lon)
        dist = fp_geo.distance_nm(ref_lat, ref_lon, wp.lat, wp.lon)

        lines = [f"{wp.id}  {wp.type.upper()}", wp.name or "", self._fmt_latlon_dm(wp.lat, wp.lon)]
        elev = getattr(wp, "elev_ft", None)
        freq = getattr(wp, "freq", None)
        extra = []
        if elev is not None:
            extra.append(f"{elev:.0f} FT")
        if freq:
            extra.append(str(freq))
        if extra:
            lines.append("  ".join(extra))
        lines.append(f"{brg:03.0f}°  {dist:.1f} NM")
        comment = getattr(wp, "comment", "")
        if comment:
            lines.append(comment)

        f = QFont(self.font_family)
        f.setPixelSize(self._px(int(box_h * 0.08), 9))
        p.setFont(f)
        ly = box_y + box_h * 0.04
        line_h = (box_h * 0.72) / max(len(lines), 1)
        for line in lines:
            p.setPen(QPen(QColor("#ffffff")))
            p.drawText(QRectF(box_x, ly, box_w, line_h),
                       Qt.AlignmentFlag.AlignCenter, line)
            ly += line_h

        footer_top = box_y + box_h * 0.8
        footer_h = box_h * 0.2
        if wp.type == "user":
            seg = box_w / 3.0
            edit_rect = (box_x, footer_top, seg, footer_h)
            p.setPen(QPen(QColor("#00ffff")))
            p.drawText(QRectF(*edit_rect), Qt.AlignmentFlag.AlignCenter, "Edit")
            self._tap(*edit_rect, (lambda w_=wp: self._open_user_wpt_editor(w_)))
            del_rect = (box_x + seg, footer_top, seg, footer_h)
            p.setPen(QPen(QColor("#ff8080")))
            p.drawText(QRectF(*del_rect), Qt.AlignmentFlag.AlignCenter, "Delete")
            self._tap(*del_rect, (lambda w_=wp: self._user_wpt_delete_request(w_)))
            close_rect = (box_x + seg * 2, footer_top, seg, footer_h)
        else:
            close_rect = (box_x, footer_top, box_w, footer_h)
        p.setPen(QPen(QColor("#ffffff")))
        p.drawText(QRectF(*close_rect), Qt.AlignmentFlag.AlignCenter, "Close")
        self._tap(*close_rect, self._close_wpt_info)

    def _paint_toast(self, p, w, h, text):
        f = QFont(self.font_family)
        f.setPixelSize(self._px(int(h * 0.05), 10))
        p.setFont(f)
        p.setPen(QPen(QColor("#ffff00")))
        p.drawText(QRectF(0, h * 0.02, w, h * 0.06), Qt.AlignmentFlag.AlignCenter, text)

    # -- Entry page ---------------------------------------------------------------
    def _paint_entry(self, p, w, h):
        field_h = h * 0.10
        strip_h = self._chrome_h(h, 1.0, 0.12)
        tabs_h = self._chrome_h(h, 1.0, 0.10)
        keypad_h = h * 0.5 if self.keypad else 0
        list_h = h - field_h - strip_h - tabs_h - keypad_h

        self._paint_entry_field(p, w, 0, field_h)
        y = field_h
        self._paint_suggestion_strip(p, w, y, strip_h)
        y += strip_h
        self._paint_entry_tabs(p, w, y, tabs_h)
        y += tabs_h
        self._paint_entry_list(p, w, y, list_h)
        y += list_h
        if self.keypad:
            self._paint_keypad(p, w, y, keypad_h)

        if self._entry_dupe_choices:
            self._paint_dupe_chooser(p, w, h)
        elif self._modal is not None:
            self._paint_modal(p, w, h)

    # -- Direct To page ---------------------------------------------------------
    def _paint_dto(self, p, w, h):
        header_h = int(self._chrome_h(h, 1.3, 0.18))   # single-line title
        tabs_h = int(self._chrome_h(h, 1.0, 0.12))
        footer_h = int(self._chrome_h(h, 1.3, 0.18))

        self._paint_dto_header(p, w, header_h)
        y = header_h
        self._paint_dto_tabs(p, w, y, tabs_h)
        y += tabs_h
        body_h = h - y - footer_h
        if self._dto_tab == "Waypoint":
            self._paint_dto_waypoint_tab(p, w, y, body_h)
        elif self._dto_tab == "FPL":
            self._paint_dto_fpl_tab(p, w, y, body_h)
        else:
            self._paint_dto_nrst_tab(p, w, y, body_h)
        self._paint_dto_footer(p, w, h - footer_h, footer_h)

        if self._dto_tab == "Waypoint" and self._entry_dupe_choices:
            self._paint_dupe_chooser(p, w, h)
        if self._message:
            self._paint_toast(p, w, h, self._message)

    def _paint_dto_header(self, p, w, header_h):
        f = QFont(self.font_family)
        f.setPixelSize(self._px(int(header_h * 0.4), 10))
        p.setFont(f)
        p.setPen(QPen(QColor("#ffffff")))
        p.drawText(QRectF(0, 0, w, header_h), Qt.AlignmentFlag.AlignCenter, "DIRECT TO")
        cancel_rect = (w - header_h, 0, header_h, header_h)
        p.setPen(QPen(QColor("#ff8080")))
        p.drawText(QRectF(*cancel_rect), Qt.AlignmentFlag.AlignCenter, "X")
        self._tap(*cancel_rect, self._close_dto)

    def _paint_dto_tabs(self, p, w, top, tabs_h):
        seg = w / len(DTO_TABS)
        f = QFont(self.font_family)
        f.setPixelSize(self._px(int(tabs_h * 0.5), 9))
        p.setFont(f)
        for i, tab in enumerate(DTO_TABS):
            x = i * seg
            color = "#00ffff" if tab == self._dto_tab else "#808080"
            p.setPen(QPen(QColor(color)))
            p.drawText(QRectF(x, top, seg, tabs_h), Qt.AlignmentFlag.AlignCenter, tab)
            self._tap(x, top, seg, tabs_h, (lambda t=tab: self._select_dto_tab(t)))

    def _paint_dto_waypoint_tab(self, p, w, top, h):
        field_h = h * 0.28
        strip_h = h * 0.22
        keypad_h = h - field_h - strip_h if self.keypad else 0
        self._paint_entry_field(p, w, top, field_h, show_cancel=False)
        y = top + field_h
        self._paint_suggestion_strip(p, w, y, strip_h)
        y += strip_h
        if self.keypad:
            self._paint_keypad(p, w, y, keypad_h)

    def _paint_dto_fpl_tab(self, p, w, top, h):
        rows = self._plan.waypoints
        f = QFont(self.font_family)
        if not rows:
            f.setPixelSize(self._px(int(h * 0.06), 10))
            p.setFont(f)
            p.setPen(QPen(QColor("#808080")))
            p.drawText(QRectF(0, top, w, h), Qt.AlignmentFlag.AlignCenter, "NO WAYPOINTS")
            return
        row_h = max(h / len(rows), 18)
        f.setPixelSize(self._px(int(row_h * 0.5), 9))
        p.setFont(f)
        y = top
        for i, wp in enumerate(rows):
            rh = min(row_h, top + h - y)
            if rh <= 0:
                break
            selected = self._dto_target is not None and self._dto_target[:2] == ("fpl", i)
            p.setPen(QPen(QColor("#00ffff" if selected else "#ffffff")))
            label = wp.id
            role = ROLE_ABBREV.get(wp.role, "")
            if role:
                label = f"{label} {role}"
            p.drawText(QRectF(6, y, w - 12, rh),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)
            self._tap(0, y, w, rh, (lambda idx=i: self._dto_select_fpl(idx)), "row")
            y += rh

    def _paint_dto_nrst_tab(self, p, w, top, h):
        idx = self._ensure_waypoint_index()
        ref_lat, ref_lon = self._aircraft_position()
        results = idx.nearest(ref_lat, ref_lon, types=frozenset({"airport"}))
        f = QFont(self.font_family)
        if not results:
            f.setPixelSize(self._px(int(h * 0.06), 10))
            p.setFont(f)
            p.setPen(QPen(QColor("#808080")))
            p.drawText(QRectF(0, top, w, h), Qt.AlignmentFlag.AlignCenter, "NO AIRPORTS")
            return
        row_h = max(h / len(results), 18)
        f.setPixelSize(self._px(int(row_h * 0.42), 9))
        p.setFont(f)
        y = top
        for wp, dist, brg, rwy in results:
            rh = min(row_h, top + h - y)
            if rh <= 0:
                break
            selected = (self._dto_target is not None and self._dto_target[0] == "wp"
                        and self._dto_target[2].id == wp.id)
            p.setPen(QPen(QColor("#00ffff" if selected else "#ffffff")))
            p.drawText(QRectF(6, y, w * 0.3, rh),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, wp.id)
            mid = f"{brg:03.0f}° {dist:.0f}NM"
            p.drawText(QRectF(w * 0.32, y, w * 0.38, rh),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, mid)
            if rwy:
                p.drawText(QRectF(w * 0.68, y, w * 0.3, rh),
                           Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                           f"RWY {int(rwy)}FT")
            self._tap(0, y, w, rh, (lambda w_=wp: self._dto_select_nearest(w_)), "row")
            y += rh

    def _paint_dto_footer(self, p, w, top, footer_h):
        state = int(self._engine_value("FPLSTATE", 0) or 0)
        label = "REMOVE" if state == 2 else "ACTIVATE"
        color = "#ff8080" if state == 2 else "#00ff00"
        f = QFont(self.font_family)
        f.setPixelSize(self._px(int(footer_h * 0.4), 10))
        p.setFont(f)
        p.setPen(QPen(QColor(color)))
        rect = (0, top, w, footer_h)
        p.drawText(QRectF(*rect), Qt.AlignmentFlag.AlignCenter, label)
        self._tap(*rect, self._dto_activate, "activate")

    # -- Catalog page -------------------------------------------------------------
    def _paint_catalog(self, p, w, h):
        header_h = int(self._chrome_h(h, 1.3, 0.18))   # single-line title
        footer_h = int(self._chrome_h(h, 1.3, 0.18))
        self._paint_catalog_header(p, w, header_h)
        self._paint_catalog_list(p, w, header_h, h - footer_h)
        self._paint_catalog_footer(p, w, h - footer_h, footer_h)

        if self._catalog_row_menu is not None:
            self._paint_catalog_row_menu(p, w, h)
        elif self._catalog_confirm is not None:
            self._paint_catalog_confirm(p, w, h)
        elif self._modal is not None:
            self._paint_modal(p, w, h)

        if self._catalog_message:
            self._paint_toast(p, w, h, self._catalog_message)

    def _paint_catalog_header(self, p, w, header_h):
        f = QFont(self.font_family)
        f.setPixelSize(self._px(int(header_h * 0.4), 10))
        p.setFont(f)
        p.setPen(QPen(QColor("#ffffff")))
        p.drawText(QRectF(0, 0, w, header_h), Qt.AlignmentFlag.AlignCenter, "CATALOG")
        cancel_rect = (w - header_h, 0, header_h, header_h)
        p.setPen(QPen(QColor("#ff8080")))
        p.drawText(QRectF(*cancel_rect), Qt.AlignmentFlag.AlignCenter, "X")
        self._tap(*cancel_rect, self._close_catalog)

    def _draw_lock_icon(self, p, x, y, size):
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor("#ffaa00")))
        p.drawRect(QRectF(x, y + size * 0.45, size, size * 0.55))
        pen = QPen(QColor("#ffaa00"))
        pen.setWidthF(max(1.0, size * 0.15))
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(QRectF(x + size * 0.15, y, size * 0.7, size * 0.7), 0, 180 * 16)
        p.restore()

    def _paint_catalog_list(self, p, w, top, bottom):
        entries = self._catalog_entries()
        f = QFont(self.font_family)
        if not entries:
            f.setPixelSize(self._px(int((bottom - top) * 0.08), 10))
            p.setFont(f)
            p.setPen(QPen(QColor("#808080")))
            p.drawText(QRectF(0, top, w, bottom - top),
                       Qt.AlignmentFlag.AlignCenter, "NO STORED ROUTES")
            return
        ref_lat, ref_lon = self._aircraft_position()
        row_h = max(18, min((bottom - top) / len(entries), (bottom - top) * 0.22))
        f.setPixelSize(self._px(int(row_h * 0.4), 9))
        p.setFont(f)
        y = top
        for entry in entries:
            rh = min(row_h, bottom - y)
            if rh <= 0:
                break
            managed = entry.slug.startswith(fp_catalog.MANAGED_PREFIX)
            lock_size = rh * 0.4
            x0 = 4.0
            if managed:
                self._draw_lock_icon(p, x0, y + (rh - lock_size) / 2, lock_size)
                x0 += lock_size + 6
            p.setPen(QPen(QColor("#ffffff")))
            p.drawText(QRectF(x0, y, w * 0.4, rh),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, entry.name)
            dist = self._catalog_entry_distance_nm(entry, ref_lat, ref_lon)
            dist_text = f"{dist:.0f}NM" if dist is not None else ""
            p.drawText(QRectF(w * 0.42, y, w * 0.18, rh),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, dist_text)
            p.drawText(QRectF(w * 0.6, y, w * 0.12, rh),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       f"{entry.count}WP")
            p.drawText(QRectF(w * 0.72, y, w * 0.26, rh),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       entry.comment or "")
            self._tap(0, y, w, rh, (lambda slug=entry.slug: self._catalog_open_row_menu(slug)),
                      "row")
            y += rh

    def _paint_catalog_footer(self, p, w, top, footer_h):
        labels = ("NEW", "DELETE ALL")
        callbacks = (self._catalog_new, self._catalog_delete_all_request)
        seg = w / len(labels)
        f = QFont(self.font_family)
        f.setPixelSize(self._px(int(footer_h * 0.34), 9))
        p.setFont(f)
        p.setPen(QPen(QColor("#ffffff")))
        for i, label in enumerate(labels):
            x = i * seg
            p.drawText(QRectF(x, top, seg, footer_h), Qt.AlignmentFlag.AlignCenter, label)
            self._tap(x, top, seg, footer_h, callbacks[i], "soft")

    def _paint_catalog_row_menu(self, p, w, h):
        self._paint_overlay_backdrop(p, w, h)
        items = self._catalog_row_menu_items(self._catalog_row_menu)
        self._paint_menu_list(p, w, h, items, self._close_catalog_row_menu, scroll_key="catalog_row_menu")

    def _paint_catalog_confirm(self, p, w, h):
        self._paint_overlay_backdrop(p, w, h)
        kind = self._catalog_confirm["kind"]
        text = {
            "activate": "Active plan has unsaved edits.\nActivate anyway?",
            "invert_activate": "Active plan has unsaved edits.\nInvert & Activate anyway?",
            "delete": "Delete this stored route?",
            "delete_all": "Delete all stored routes?",
            "new": "Active plan has unsaved edits.\nStart a new plan?",
        }[kind]
        self._paint_confirm(p, w, h, text, self._catalog_confirm_yes)

    # -- generic modal overlay ------------------------------------------------
    def _paint_modal(self, p, w, h):
        self._paint_overlay_backdrop(p, w, h)
        m = self._modal
        box_w, box_h = w * 0.8, h * 0.8
        box_x, box_y = (w - box_w) / 2, (h - box_h) / 2
        p.setBrush(QBrush(QColor("#202020")))
        p.setPen(QPen(QColor("#ffffff")))
        p.drawRect(QRectF(box_x, box_y, box_w, box_h))

        f = QFont(self.font_family)
        f.setPixelSize(self._px(int(box_h * 0.06), 10))
        p.setFont(f)
        p.setPen(QPen(QColor("#ffffff")))
        p.drawText(QRectF(box_x, box_y + 2, box_w, box_h * 0.1),
                   Qt.AlignmentFlag.AlignCenter, m["title"])
        p.setPen(QPen(QColor("#00ffff")))
        p.drawText(QRectF(box_x, box_y + box_h * 0.1, box_w, box_h * 0.12),
                   Qt.AlignmentFlag.AlignCenter, m["value"] or " ")

        cancel_size = box_h * 0.08
        cancel_rect = (box_x, box_y + 2, cancel_size, cancel_size)
        p.setPen(QPen(QColor("#ff8080")))
        p.drawText(QRectF(*cancel_rect), Qt.AlignmentFlag.AlignCenter, "X")
        self._tap(*cancel_rect, self._modal_do_cancel)

        rows = KEYPAD_NUMERIC_ROWS if m["numeric"] else KEYPAD_ROWS
        kp_top = box_y + box_h * 0.24
        kp_h = box_h * 0.76
        n_rows = len(rows) + 1
        row_h = kp_h / n_rows
        fk = QFont(self.font_family)
        fk.setPixelSize(self._px(int(row_h * 0.4), 10))
        p.setFont(fk)
        y = kp_top
        for row in rows:
            seg = box_w / len(row)
            for i, ch in enumerate(row):
                x = box_x + i * seg
                p.setPen(QPen(QColor("#333333")))
                p.drawRect(QRectF(x + 1, y + 1, seg - 2, row_h - 2))
                p.setPen(QPen(QColor("#ffffff")))
                p.drawText(QRectF(x, y, seg, row_h), Qt.AlignmentFlag.AlignCenter, ch)
                self._tap(x, y, seg, row_h, (lambda c=ch: self._modal_key(c)))
            y += row_h
        seg = box_w / len(KEYPAD_CTRL_ROW)
        callbacks = {"BKSP": self._modal_backspace, "CLR": self._modal_clear,
                     "ENT": self._modal_enter}
        for i, label in enumerate(KEYPAD_CTRL_ROW):
            x = box_x + i * seg
            p.setPen(QPen(QColor("#333333")))
            p.drawRect(QRectF(x + 1, y + 1, seg - 2, row_h - 2))
            p.setPen(QPen(QColor("#00ff00" if label == "ENT" else "#ff8080")))
            p.drawText(QRectF(x, y, seg, row_h), Qt.AlignmentFlag.AlignCenter, label)
            self._tap(x, y, seg, row_h, callbacks[label])

    def _paint_entry_field(self, p, w, top, field_h, show_cancel=True):
        p.setPen(QPen(QColor("#444444")))
        p.drawLine(0, int(top + field_h), w, int(top + field_h))
        f = QFont(self.font_family)
        f.setPixelSize(self._px(int(field_h * 0.5), 12))
        p.setFont(f)
        typed = self._entry_field
        suffix = self._entry_suffix()
        self._enc_field = (QRectF(0, top, w, field_h), QFont(f), 8.0)
        p.setPen(QPen(QColor("#ffffff")))
        p.drawText(QRectF(8, top, w * 0.5, field_h),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, typed)
        if suffix:
            advance = p.fontMetrics().horizontalAdvance(typed)
            p.setPen(QPen(QColor("#00ffff")))
            p.drawText(QRectF(8 + advance, top, w * 0.5, field_h),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, suffix)
        if self._entry_message:
            p.setPen(QPen(QColor("#ff0000")))
            p.drawText(QRectF(w * 0.5, top, w * 0.42, field_h),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       self._entry_message)
        if show_cancel:
            cancel_rect = (w - field_h, top, field_h, field_h)
            p.setPen(QPen(QColor("#ff8080")))
            p.drawText(QRectF(*cancel_rect), Qt.AlignmentFlag.AlignCenter, "X")
            self._tap(*cancel_rect, self._entry_cancel)

    def _paint_suggestion_strip(self, p, w, top, strip_h):
        cands = self._entry_candidates()
        f = QFont(self.font_family)
        f.setPixelSize(self._px(int(strip_h * 0.45), 9))
        p.setFont(f)
        seg = w / 5.0
        for i in range(5):
            x = i * seg
            p.setPen(QPen(QColor("#222222")))
            p.drawRect(QRectF(x + 1, top + 1, seg - 2, strip_h - 2))
            if i < len(cands):
                wp = cands[i]
                p.setPen(QPen(QColor("#ffffff")))
                p.drawText(QRectF(x, top, seg, strip_h), Qt.AlignmentFlag.AlignCenter, wp.id)
                self._tap(x, top, seg, strip_h, (lambda w_=wp: self._select_waypoint(w_)))

    def _paint_entry_tabs(self, p, w, top, tabs_h):
        seg = w / len(ENTRY_TABS)
        f = QFont(self.font_family)
        f.setPixelSize(self._px(int(tabs_h * 0.5), 9))
        p.setFont(f)
        for i, tab in enumerate(ENTRY_TABS):
            x = i * seg
            color = "#00ffff" if tab == self._entry_tab else "#808080"
            p.setPen(QPen(QColor(color)))
            p.drawText(QRectF(x, top, seg, tabs_h), Qt.AlignmentFlag.AlignCenter, tab)
            self._tap(x, top, seg, tabs_h, (lambda t=tab: self._select_entry_tab(t)))

    def _paint_entry_list(self, p, w, top, list_h):
        f = QFont(self.font_family)
        f.setPixelSize(self._px(int(max(list_h, 1) * 0.08), 9))
        p.setFont(f)

        if self._entry_tab == "User":
            create_row_h = min(max(list_h * 0.16, 16), list_h)
            create_rect = (0, top, w, create_row_h)
            p.setPen(QPen(QColor("#00ff00")))
            p.drawText(QRectF(*create_rect), Qt.AlignmentFlag.AlignCenter,
                       "+ CREATE USER WAYPOINT")
            self._tap(*create_rect, self._open_user_wpt_creator)
            top += create_row_h
            list_h -= create_row_h

        rows = self._entry_tab_rows()
        if not rows:
            p.setPen(QPen(QColor("#808080")))
            p.drawText(QRectF(0, top, w, list_h), Qt.AlignmentFlag.AlignCenter, "NO MATCHES")
            return
        row_h = max(list_h / len(rows), 14)
        ref_lat, ref_lon = self._entry_ref()
        y = top
        for wp in rows:
            rh = min(row_h, top + list_h - y)
            if rh <= 0:
                break
            brg = fp_geo.initial_bearing(ref_lat, ref_lon, wp.lat, wp.lon)
            dist = fp_geo.distance_nm(ref_lat, ref_lon, wp.lat, wp.lon)
            p.setPen(QPen(QColor("#ffffff")))
            p.drawText(QRectF(4, y, w * 0.3, rh),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, wp.id)
            p.drawText(QRectF(w * 0.3, y, w * 0.35, rh),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, wp.type)
            p.drawText(QRectF(w * 0.65, y, w * 0.34, rh),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       f"{brg:03.0f} {dist:.0f}NM")
            self._tap(0, y, w, rh, (lambda w_=wp: self._select_waypoint(w_)), "row")
            y += rh

    def _paint_keypad(self, p, w, top, keypad_h):
        n_rows = len(KEYPAD_ROWS) + 1
        row_h = keypad_h / n_rows
        f = QFont(self.font_family)
        f.setPixelSize(self._px(int(row_h * 0.5), 10))
        p.setFont(f)
        y = top
        for row in KEYPAD_ROWS:
            seg = w / len(row)
            for i, ch in enumerate(row):
                x = i * seg
                p.setPen(QPen(QColor("#333333")))
                p.drawRect(QRectF(x + 1, y + 1, seg - 2, row_h - 2))
                p.setPen(QPen(QColor("#ffffff")))
                p.drawText(QRectF(x, y, seg, row_h), Qt.AlignmentFlag.AlignCenter, ch)
                self._tap(x, y, seg, row_h, (lambda c=ch: self._entry_key(c)), "key")
            y += row_h
        seg = w / len(KEYPAD_CTRL_ROW)
        callbacks = {"BKSP": self._entry_backspace, "CLR": self._entry_clear,
                     "ENT": self._entry_enter}
        for i, label in enumerate(KEYPAD_CTRL_ROW):
            x = i * seg
            p.setPen(QPen(QColor("#333333")))
            p.drawRect(QRectF(x + 1, y + 1, seg - 2, row_h - 2))
            p.setPen(QPen(QColor("#00ff00" if label == "ENT" else "#ff8080")))
            p.drawText(QRectF(x, y, seg, row_h), Qt.AlignmentFlag.AlignCenter, label)
            self._tap(x, y, seg, row_h, callbacks[label], "key")

    def _paint_dupe_chooser(self, p, w, h):
        self._paint_overlay_backdrop(p, w, h)
        items = [(f"{wp.id} {wp.type} {wp.name or ''}".strip(),
                  (lambda w_=wp: self._choose_duplicate(w_)))
                 for wp in self._entry_dupe_choices]
        self._paint_menu_list(p, w, h, items, self._cancel_dupe_chooser, scroll_key="dupe_chooser")
