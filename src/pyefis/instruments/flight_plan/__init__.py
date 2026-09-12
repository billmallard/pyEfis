#  SPDX-License-Identifier: GPL-2.0-or-later
"""The `flight_plan` app-like instrument (FP5a/b, billmallard/pyEfis#185,
#187).

FPL page (route header, waypoint list, row menu, footer menu), Entry page
(FastFind ident field, suggestion strip, Recent/Nearest/FPL/User tabs, an
on-screen keypad), Direct To page (Waypoint/FPL/NRST APT tabs), Catalog page
(stored-route list and its Activate/Invert & Activate/Edit/Copy/Delete
actions), WPT Info (lat/lon, elevation/frequency, bearing/distance, user
waypoint Edit/Delete) and the physical-keyboard input path all live here.
The encoder path is FP5c -- not wired yet.

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
"""

import logging
import os

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QWidget

from pyavtools import fix
from pyefis import hmi
from pyefis.flightplan import catalog as fp_catalog
from pyefis.flightplan import fixbridge as fp_fixbridge
from pyefis.flightplan import geo as fp_geo
from pyefis.flightplan import model as fp_model
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

_ROW_MENU_ITEMS = (
    ("Insert Before", "_row_menu_insert_before"),
    ("Insert After", "_row_menu_insert_after"),
    ("Activate Leg", "_row_menu_activate_leg"),
    ("Direct To", "_row_menu_direct_to"),
    ("WPT Info", "_row_menu_wpt_info"),
    ("Set Role", None),
    ("Remove", "_row_menu_remove"),
)
_ROLE_MENU_ORDER = ("none", "iaf", "faf", "map", "mahp")


class FlightPlan(QWidget):
    """The `flight_plan` instrument widget."""

    def __init__(self, parent=None, font_family="DejaVu Sans Condensed"):
        super().__init__(parent)
        self.parent = parent
        self.font_family = font_family
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # apply="attr" InstrumentSpec Props -- keep in lockstep with the
        # registry record (screenbuilder_factory.py) and its defaults.
        self.flightplan_dir = ""
        self.nasr_db_path = ""
        self.navaid_db_path = ""
        self.columns = "DTK,DIS,CUM"
        self.keypad = True
        self.keyboard = False
        self.default_page = "fpl"
        self.hmi_group = ""
        self.active_color = "#ff00ff"
        self.future_color = "#ffffff"
        self.past_color = "#808080"

        self._page = None
        self._plan = fp_model.FlightPlan()
        self._plan_dirty = False
        self._engine = {}
        self._message = ""
        self._cdi_scale_choice = "AUTO"

        self._row_menu_index = None
        self._role_menu_open = False
        self._wpt_info = None
        self._menu_open = False
        self._confirm = None

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
        self._catalog = None
        self._catalog_dir_used = None

        self._tap_targets = []

        self._wpt_timer = QTimer(self)
        self._wpt_timer.setInterval(1000)
        self._wpt_timer.timeout.connect(self.update)

        self._bridge = fp_fixbridge.FixBridge(fix)
        if self._bridge.available:
            self._sync_plan_from_bridge()
            self._sync_engine_from_bridge()
            self._bridge.add_listener(self._on_bridge_change)
        self._connect_hmi()

    # -- HMI action hub ---------------------------------------------------
    def _connect_hmi(self):
        if hmi.actions is None:
            return
        a = hmi.actions
        for signal, handler in (
            (a.flightplanPage, self._act_page),
            (a.flightplanDirectTo, self._act_direct_to),
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
            self._menu_open = False
            self._wpt_info = None
            self._close_entry()
            self._page = "fpl"
            self.update()
        elif page == "dto":
            self._open_dto_page()
        elif page == "catalog":
            self._open_catalog_page()

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
        route = self._bridge.read_route()
        if route is None:
            return
        self._plan = fp_model.FlightPlan(
            name=route.name,
            waypoints=[fp_model.Waypoint(id=s.id, type=s.type, lat=s.lat, lon=s.lon,
                                          role=s.role) for s in route.waypoints])

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

    def _menu_invert(self):
        self._plan = self._plan.invert()
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
            plan = self._ensure_catalog().load(slug)
        except fp_catalog.CatalogError as e:
            self._catalog_message = str(e)
            self._catalog_confirm = None
            self.update()
            return
        self._plan = plan
        self._plan_dirty = False
        self._catalog_confirm = None
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
            plan = self._ensure_catalog().invert(slug)
        except fp_catalog.CatalogError as e:
            self._catalog_message = str(e)
            self._catalog_confirm = None
            self.update()
            return
        self._plan = plan
        self._plan_dirty = False
        self._catalog_confirm = None
        self._commit()
        self._close_catalog()

    def _catalog_edit(self, slug):
        """Loads *slug* into the working copy for editing without publishing
        it to the bus -- the guide's "Edit ... Store writes back" (brief
        3.5). The active route on the bus is untouched until the next edit
        commits or Store is used."""
        self._catalog_row_menu = None
        try:
            plan = self._ensure_catalog().load(slug)
        except fp_catalog.CatalogError as e:
            self._catalog_message = str(e)
            self.update()
            return
        self._plan = plan
        self._plan_dirty = False
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
    def _open_user_wpt_creator(self):
        self._uwpt_new = {}
        self._modal_open("IDENT (BLANK=AUTO)", "", False, fp_waypoints.USER_ID_MAX_LEN,
                          self._uwpt_new_ident)

    def _uwpt_new_ident(self, value):
        self._uwpt_new["id"] = value.strip().upper()
        self._modal_open("COMMENT", "", False, fp_waypoints.USER_COMMENT_MAX_LEN,
                          self._uwpt_new_comment)

    def _uwpt_new_comment(self, value):
        self._uwpt_new["comment"] = value
        ref_lat, ref_lon = self._aircraft_position()
        self._modal_open("LAT", self._fmt_latlon_entry(ref_lat, True), True, 10,
                          self._uwpt_new_lat)

    def _uwpt_new_lat(self, value):
        lat = self._parse_latlon_entry(value, True)
        if lat is None:
            self._message = "BAD LAT"
            self.update()
            return
        self._uwpt_new["lat"] = lat
        ref_lat, ref_lon = self._aircraft_position()
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

    # -- input dispatch ------------------------------------------------------
    def _tap(self, x, y, w, h, callback):
        self._tap_targets.append((x, y, w, h, callback))

    def mousePressEvent(self, event):
        x, y = event.pos().x(), event.pos().y()
        for tx, ty, tw, th, callback in reversed(self._tap_targets):
            if tx <= x <= tx + tw and ty <= y <= ty + th:
                callback()
                event.accept()
                return
        super().mousePressEvent(event)

    # -- painting -------------------------------------------------------------
    def paintEvent(self, event):
        try:
            self._paint()
        except Exception:
            logger.warning("flight_plan: paint error", exc_info=True)

    def _paint(self):
        if self._page not in _INSTRUMENT_PAGES:
            self._page = self.default_page if self.default_page in _INSTRUMENT_PAGES else "fpl"
        self._sync_keyboard_focus()
        self._tap_targets = []
        p = QPainter(self)
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
        header_h = int(h * 0.16)
        footer_h = int(h * 0.10)

        self._paint_header(p, w, header_h, interactive)
        self._paint_list(p, w, header_h, h - footer_h, header_h, interactive)
        self._paint_footer(p, w, h - footer_h, footer_h, interactive)

        if self._row_menu_index is not None:
            self._paint_row_menu(p, w, h)
        elif self._menu_open:
            self._paint_menu(p, w, h)
        elif self._wpt_info is not None:
            self._paint_wpt_info(p, w, h)
            if self._modal is not None:
                self._paint_modal(p, w, h)

        if self._message:
            self._paint_toast(p, w, h, self._message)

    def _paint_header(self, p, w, header_h, interactive):
        f = QFont(self.font_family)
        f.setPixelSize(max(10, int(header_h * 0.32)))
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
        n = len(self._plan.waypoints)
        try:
            if col == "DTK":
                return f"{self._plan.leg(i)[0]:03.0f}" if i < n - 1 else ""
            if col == "DIS":
                return f"{self._plan.leg(i)[1]:.0f}" if i < n - 1 else ""
            if col == "CUM":
                return f"{self._plan.cumulative(i):.0f}"
            if col == "ETE":
                return self._fmt_ete(self._engine_value("WPETE")) if i == active_idx else ""
            if col == "ETA":
                return ""
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

    def _paint_list(self, p, w, top, bottom, max_row_h, interactive):
        rows = self._plan.waypoints
        n = len(rows)
        if n == 0:
            p.setPen(QPen(QColor("#808080")))
            f = QFont(self.font_family)
            f.setPixelSize(max(10, min(int((bottom - top) * 0.08), int(max_row_h * 0.5))))
            p.setFont(f)
            p.drawText(QRectF(0, top, w, bottom - top),
                       Qt.AlignmentFlag.AlignCenter, "NO WAYPOINTS")
            return

        active_leg = self._engine_value("FPLACTLEG")
        active_idx = int(active_leg) - 1 if active_leg else None
        cols = [c.strip().upper() for c in (self.columns or "").split(",") if c.strip()]
        cols = [c for c in cols if c in COLUMN_CHOICES] or ["DTK", "DIS", "CUM"]

        # Cap the row height so a near-empty plan doesn't stretch one or two
        # rows into a grotesquely oversized icon/font -- a real 50-slot plan
        # is what sizes rows down to fit, not the list area's leftover space.
        row_h = max(14, min((bottom - top) / n, max_row_h))
        f = QFont(self.font_family)
        f.setPixelSize(max(9, int(row_h * 0.5)))
        p.setFont(f)

        y = top
        for i, wp in enumerate(rows):
            rh = min(row_h, bottom - y)
            if rh <= 0:
                break
            p.setPen(QPen(QColor(self._row_color(i, active_idx))))
            self._draw_type_icon(p, 6 + rh * 0.15, y + rh / 2, rh * 0.28, wp.type)

            label = wp.id
            role = ROLE_ABBREV.get(wp.role, "")
            if role:
                label = f"{label} {role}"
            p.drawText(QRectF(rh * 0.5, y, w * 0.35, rh),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)

            col_w = (w * 0.55) / len(cols)
            cx = w * 0.42
            for c in cols:
                p.drawText(QRectF(cx, y, col_w, rh),
                           Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                           self._column_text(c, i, active_idx))
                cx += col_w

            if interactive:
                self._tap(0, y, w, rh, (lambda idx=i: self._open_row_menu(idx)))
            y += rh

    def _paint_footer(self, p, w, top, footer_h, interactive):
        p.setPen(QPen(QColor("#333333")))
        p.drawLine(0, top, w, top)
        labels = ("ADD WPT", "DIRECT TO", "CATALOG", "MENU")
        callbacks = (self._footer_add, self._footer_direct_to, self._footer_catalog,
                     self._footer_menu)
        seg = w / len(labels)
        f = QFont(self.font_family)
        f.setPixelSize(max(9, int(footer_h * 0.34)))
        p.setFont(f)
        p.setPen(QPen(QColor("#ffffff")))
        for i, label in enumerate(labels):
            x = i * seg
            p.drawText(QRectF(x, top, seg, footer_h), Qt.AlignmentFlag.AlignCenter, label)
            if interactive:
                self._tap(x, top, seg, footer_h, callbacks[i])

    # -- overlays ---------------------------------------------------------------
    def _paint_overlay_backdrop(self, p, w, h):
        p.fillRect(QRectF(0, 0, w, h), QColor(0, 0, 0, 160))

    def _paint_menu_list(self, p, w, h, items, on_cancel):
        n = len(items) + 1
        box_w = w * 0.6
        box_x = (w - box_w) / 2
        box_top = h * 0.12
        item_h = (h * 0.76) / n
        f = QFont(self.font_family)
        f.setPixelSize(max(10, int(item_h * 0.4)))
        p.setFont(f)
        p.setPen(QPen(QColor("#ffffff")))
        p.setBrush(QBrush(QColor("#202020")))
        p.drawRect(QRectF(box_x, box_top, box_w, item_h * n))
        y = box_top
        for label, callback in items:
            p.setPen(QPen(QColor("#000000")))
            p.drawRect(QRectF(box_x + 2, y + 2, box_w - 4, item_h - 4))
            p.setPen(QPen(QColor("#00ffff")))
            p.drawText(QRectF(box_x, y, box_w, item_h), Qt.AlignmentFlag.AlignCenter, label)
            self._tap(box_x, y, box_w, item_h, callback)
            y += item_h
        p.setPen(QPen(QColor("#ff8080")))
        p.drawText(QRectF(box_x, y, box_w, item_h), Qt.AlignmentFlag.AlignCenter, "Cancel")
        self._tap(box_x, y, box_w, item_h, on_cancel)

    def _paint_row_menu(self, p, w, h):
        self._paint_overlay_backdrop(p, w, h)
        if self._role_menu_open:
            items = [(ROLE_ABBREV.get(r) or "NONE", (lambda role=r: self._row_menu_set_role(role)))
                     for r in _ROLE_MENU_ORDER]
            self._paint_menu_list(p, w, h, items, self._close_row_menu)
            return
        items = []
        for label, attr in _ROW_MENU_ITEMS:
            items.append((label, self._open_role_menu if attr is None else getattr(self, attr)))
        self._paint_menu_list(p, w, h, items, self._close_row_menu)

    def _paint_confirm(self, p, w, h, text, on_yes):
        box_w, box_h = w * 0.6, h * 0.3
        box_x, box_y = (w - box_w) / 2, (h - box_h) / 2
        p.setBrush(QBrush(QColor("#202020")))
        p.setPen(QPen(QColor("#ffffff")))
        p.drawRect(QRectF(box_x, box_y, box_w, box_h))
        f = QFont(self.font_family)
        f.setPixelSize(max(10, int(box_h * 0.16)))
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
        self._tap(*no_rect, self._close_menu)

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
        self._paint_menu_list(p, w, h, items, self._close_menu)

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
        f.setPixelSize(max(9, int(box_h * 0.08)))
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
        f.setPixelSize(max(10, int(h * 0.05)))
        p.setFont(f)
        p.setPen(QPen(QColor("#ffff00")))
        p.drawText(QRectF(0, h * 0.02, w, h * 0.06), Qt.AlignmentFlag.AlignCenter, text)

    # -- Entry page ---------------------------------------------------------------
    def _paint_entry(self, p, w, h):
        field_h = h * 0.10
        strip_h = h * 0.08
        tabs_h = h * 0.06
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
        header_h = int(h * 0.14)
        tabs_h = int(h * 0.08)
        footer_h = int(h * 0.10)

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
        f.setPixelSize(max(10, int(header_h * 0.4)))
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
        f.setPixelSize(max(9, int(tabs_h * 0.5)))
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
            f.setPixelSize(max(10, int(h * 0.06)))
            p.setFont(f)
            p.setPen(QPen(QColor("#808080")))
            p.drawText(QRectF(0, top, w, h), Qt.AlignmentFlag.AlignCenter, "NO WAYPOINTS")
            return
        row_h = max(h / len(rows), 18)
        f.setPixelSize(max(9, int(row_h * 0.5)))
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
            self._tap(0, y, w, rh, (lambda idx=i: self._dto_select_fpl(idx)))
            y += rh

    def _paint_dto_nrst_tab(self, p, w, top, h):
        idx = self._ensure_waypoint_index()
        ref_lat, ref_lon = self._aircraft_position()
        results = idx.nearest(ref_lat, ref_lon, types=frozenset({"airport"}))
        f = QFont(self.font_family)
        if not results:
            f.setPixelSize(max(10, int(h * 0.06)))
            p.setFont(f)
            p.setPen(QPen(QColor("#808080")))
            p.drawText(QRectF(0, top, w, h), Qt.AlignmentFlag.AlignCenter, "NO AIRPORTS")
            return
        row_h = max(h / len(results), 18)
        f.setPixelSize(max(9, int(row_h * 0.42)))
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
            self._tap(0, y, w, rh, (lambda w_=wp: self._dto_select_nearest(w_)))
            y += rh

    def _paint_dto_footer(self, p, w, top, footer_h):
        state = int(self._engine_value("FPLSTATE", 0) or 0)
        label = "REMOVE" if state == 2 else "ACTIVATE"
        color = "#ff8080" if state == 2 else "#00ff00"
        f = QFont(self.font_family)
        f.setPixelSize(max(10, int(footer_h * 0.4)))
        p.setFont(f)
        p.setPen(QPen(QColor(color)))
        rect = (0, top, w, footer_h)
        p.drawText(QRectF(*rect), Qt.AlignmentFlag.AlignCenter, label)
        self._tap(*rect, self._dto_activate)

    # -- Catalog page -------------------------------------------------------------
    def _paint_catalog(self, p, w, h):
        header_h = int(h * 0.12)
        footer_h = int(h * 0.10)
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
        f.setPixelSize(max(10, int(header_h * 0.4)))
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
            f.setPixelSize(max(10, int((bottom - top) * 0.08)))
            p.setFont(f)
            p.setPen(QPen(QColor("#808080")))
            p.drawText(QRectF(0, top, w, bottom - top),
                       Qt.AlignmentFlag.AlignCenter, "NO STORED ROUTES")
            return
        ref_lat, ref_lon = self._aircraft_position()
        row_h = max(18, min((bottom - top) / len(entries), (bottom - top) * 0.22))
        f.setPixelSize(max(9, int(row_h * 0.4)))
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
            self._tap(0, y, w, rh, (lambda slug=entry.slug: self._catalog_open_row_menu(slug)))
            y += rh

    def _paint_catalog_footer(self, p, w, top, footer_h):
        labels = ("NEW", "DELETE ALL")
        callbacks = (self._catalog_new, self._catalog_delete_all_request)
        seg = w / len(labels)
        f = QFont(self.font_family)
        f.setPixelSize(max(9, int(footer_h * 0.34)))
        p.setFont(f)
        p.setPen(QPen(QColor("#ffffff")))
        for i, label in enumerate(labels):
            x = i * seg
            p.drawText(QRectF(x, top, seg, footer_h), Qt.AlignmentFlag.AlignCenter, label)
            self._tap(x, top, seg, footer_h, callbacks[i])

    def _paint_catalog_row_menu(self, p, w, h):
        self._paint_overlay_backdrop(p, w, h)
        items = self._catalog_row_menu_items(self._catalog_row_menu)
        self._paint_menu_list(p, w, h, items, self._close_catalog_row_menu)

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
        f.setPixelSize(max(10, int(box_h * 0.06)))
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
        fk.setPixelSize(max(10, int(row_h * 0.4)))
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
        f.setPixelSize(max(12, int(field_h * 0.5)))
        p.setFont(f)
        typed = self._entry_field
        suffix = self._entry_suffix()
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
        f.setPixelSize(max(9, int(strip_h * 0.45)))
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
        f.setPixelSize(max(9, int(tabs_h * 0.5)))
        p.setFont(f)
        for i, tab in enumerate(ENTRY_TABS):
            x = i * seg
            color = "#00ffff" if tab == self._entry_tab else "#808080"
            p.setPen(QPen(QColor(color)))
            p.drawText(QRectF(x, top, seg, tabs_h), Qt.AlignmentFlag.AlignCenter, tab)
            self._tap(x, top, seg, tabs_h, (lambda t=tab: self._select_entry_tab(t)))

    def _paint_entry_list(self, p, w, top, list_h):
        f = QFont(self.font_family)
        f.setPixelSize(max(9, int(max(list_h, 1) * 0.08)))
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
            self._tap(0, y, w, rh, (lambda w_=wp: self._select_waypoint(w_)))
            y += rh

    def _paint_keypad(self, p, w, top, keypad_h):
        n_rows = len(KEYPAD_ROWS) + 1
        row_h = keypad_h / n_rows
        f = QFont(self.font_family)
        f.setPixelSize(max(10, int(row_h * 0.5)))
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
                self._tap(x, y, seg, row_h, (lambda c=ch: self._entry_key(c)))
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
            self._tap(x, y, seg, row_h, callbacks[label])

    def _paint_dupe_chooser(self, p, w, h):
        self._paint_overlay_backdrop(p, w, h)
        items = [(f"{wp.id} {wp.type} {wp.name or ''}".strip(),
                  (lambda w_=wp: self._choose_duplicate(w_)))
                 for wp in self._entry_dupe_choices]
        self._paint_menu_list(p, w, h, items, self._cancel_dupe_chooser)
