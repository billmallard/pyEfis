#  SPDX-License-Identifier: GPL-2.0-or-later
"""The `flight_plan` app-like instrument (FP5a/b, billmallard/pyEfis#185,
#187).

FPL page (route header, waypoint list, row menu, footer menu), Entry page
(FastFind ident field, suggestion strip, Recent/Nearest/FPL/User tabs, an
on-screen keypad), Direct To page (Waypoint/FPL/NRST APT tabs), Catalog page
(stored-route list and its Activate/Invert & Activate/Edit/Copy/Delete
actions), PROC page (PA7, #238: departure/arrival/approach selection,
loaded as a named block), WPT Info (lat/lon, elevation/frequency, bearing/distance, user
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

List scrolling (PA15, AER-2087): FPL rows keep their physical height and the
list scrolls under a finger instead of shrinking. A press on the list is not
a tap until the finger lifts: moving past ``drag_threshold_mm`` turns it into
a drag (kinetic on release, clamped at both ends) and cancels the row tap it
started on. Every other tap target still fires on press.
"""

import copy
import logging
import math
import time

from pyefis import display_metrics
import os

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import (QBrush, QColor, QFont, QFontMetrics, QGuiApplication, QImage,
                         QKeySequence, QPainter, QPen, QPolygonF)
from PyQt6.QtWidgets import QWidget

from pyavtools import fix
from pyefis import hmi
from pyefis import kiosk
from pyefis.flightplan import airac as fp_airac
from pyefis.flightplan import airways as fp_airways
from pyefis.flightplan import catalog as fp_catalog
from pyefis.flightplan import fixbridge as fp_fixbridge
from pyefis.flightplan import geo as fp_geo
from pyefis.flightplan import hold as fp_hold
from pyefis.flightplan import model as fp_model
from pyefis.flightplan import plates as fp_plates
from pyefis.flightplan import proc_load as fp_proc
from pyefis.flightplan import procedures as fp_procedures
from pyefis.flightplan import refusal as fp_refusal
from pyefis.flightplan import route_string as fp_route_string
from pyefis.flightplan import vocab as fp_vocab
from pyefis.flightplan import waypoints as fp_waypoints
from pyefis.instruments.flight_plan import plate_render

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
# A route string (RTE1b) also needs a space between its tokens and the dot
# of FLOUT5.VTU.
KEYPAD_ROUTE_ROWS = KEYPAD_ROWS + (" .",)
ROUTE_MAX_LEN = 200

_STATE_BADGES = {0: "", 1: "LEG", 2: "DIRECT", 3: "SUSP", 4: "OBS"}
_STATE_SUSP = 3
# GPS OBS (fix-gateway OBS2, pyEfis OBS3): a pilot course through the TO
# waypoint, set by FPLCMD OBS <deg> and left by FPLCMD OBS OFF.
_STATE_OBS = 4
_APR_TEXT = {0: "", 1: "APR ARM", 2: "LNAV", 3: "MISSED"}
# Expired procedure data (PA9): the data-status screen's expired amber.
_EXPIRED_COLOR = "#ffb000"
_CYCLE_COLOR = "#9a9a9a"
_CDI_SCALE_CHOICES = ("0.3", "1.0", "2.0", "AUTO")
_INSTRUMENT_PAGES = ("fpl", "entry", "dto", "catalog", "proc", "charts")
# PROC page (PA7): its tabs, in the guide's order, and the fields each kind
# asks for, in the order the pilot picks them (pyEfis #238).
PROC_TABS = (("Departure", "departure"), ("Arrival", "arrival"), ("Approach", "approach"))
_PROC_FIELDS = {"departure": ("airport", "proc", "runway", "transition"),
                "arrival": ("airport", "proc", "transition", "runway"),
                "approach": ("airport", "proc", "transition")}
_PROC_FIELD_LABELS = {"airport": "Airport", "runway": "Runway", "transition": "Transition"}
_PROC_KIND_LABELS = {"departure": "Departure", "arrival": "Arrival", "approach": "Approach"}
# Charts page (PA12): what each d-TPP chart type is called in the list, and
# the zoom steps the - and + keys walk (1 = the whole page fits the pane).
_CHART_LABELS = {"APD": "DIAGRAM", "IAP": "APPROACH", "DP": "DEPARTURE", "ODP": "OBST DP",
                 "STR": "ARRIVAL", "MIN": "MINIMUMS", "HOT": "HOT SPOTS", "LAH": "LAHSO",
                 "DAU": "ALT MIN"}
CHART_ZOOMS = (1.0, 1.5, 2.0, 3.0)
_SEGMENT_PAGE_KIND = {"departure": "departure", "arrival": "arrival",
                      "approach": "approach", "missed": "approach"}

# Encoder (FP5c). The character set the knob scrolls through on an ident
# field, in the order the brief gives (A-Z, 0-9, space); a space at the cursor
# means "nothing here", so turning onto it and pushing accepts the field.
ENC_CHARSET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 "
# Hold time that turns an encoder push into Back. abstract.py has no
# long-press convention to inherit, so it is set here and documented in
# docs/flight_plan_widget.md.
ENC_LONG_PRESS_MS = 600
# Activate Leg asks first when the leg's from-fix is farther than this from
# the aircraft (FPACT1, AER-5801).
ACT_CONFIRM_NM = 500.0
# How long a FPL-page toast (STORED, NO AIRWAYS AT x, ROUTE FULL, an error)
# stays up before it clears itself (pyEfis #323: with no expiry, STORED sat
# over the LEG/DIRECT/SUSP badge for the rest of a bench session).
TOAST_MS = 4000
# G61 (pyEfis #380): how long a route commit may go unanswered before the
# page treats it as refused. The engine answers a commit on the same gateway
# cycle -- FPLLDSEQ when it loads the route, FPLMSG when it refuses it -- so
# this only fires when no answer arrives at all.
COMMIT_ANSWER_MS = 2000
# Why a hold at present position is refused with no usable LAT/LONG.
NO_GPS_POSITION = "NO GPS POSITION"
# The route is read when FPLSEQ / FPLLDSEQ / the counts change, not on every
# engine output write. This is how often, at most, a write also checks the
# slots on the bus against the route last read, so a slot value that arrived
# after the key still reaches the page (FlightPlan._route_drifted).
ROUTE_VERIFY_S = 1.0
# The writes that can move FixBridge.route_key(): FPLSEQ goes last in a
# commit (RS1), and FPLLDSEQ is the engine's answer to it. FPLCOUNT and
# FPLSEGCNT are written before FPLSEQ and are not watched; a writer that
# breaks that order is caught by the route_verify_s check.
_ROUTE_KEY_WRITES = frozenset(("FPLSEQ", "FPLLDSEQ"))
# The prompt for a plan staged on the bus (EFB4b, PROV0): the only place that
# says where a staged plan came from. Accept, Reject and the sheet are the
# same for every staging block (fixbridge.STAGING_BLOCKS). FPLIMP holds a
# .fpl uploaded to fix-gateway's fpl_exchange, and carries no origin key, so
# it names the kind of device, not the app; a .fpl carries only the fixes
# (fix-gateway doc/plugins/fpl_exchange.md, "What crosses"). "source" is the
# model's provenance field for the accepted plan.
STAGED_NOTE = "ALTITUDES AND SPEEDS DID NOT COME ACROSS"
STAGING_PROMPTS = {
    "FPLIMP": {"title": "PLAN FROM EFB", "note": STAGED_NOTE, "source": "efb"},
}
# A block with no entry above still gets a prompt that claims no origin.
STAGING_PROMPT_DEFAULT = {"title": "PLAN RECEIVED", "note": STAGED_NOTE, "source": "device"}
# A route the pilot typed or pasted on the FPL menu (RTE1b) is offered on the
# same sheet; a route string carries no altitudes or speeds either.
ROUTE_TITLE = "ROUTE"
ROUTE_NOTE = "ALTITUDES AND SPEEDS ARE NOT IN A ROUTE"


def _no_op():
    pass


class _PickedIndex:
    """A WaypointIndex whose lookup of an ident the pilot has already
    disambiguated (RTE1b) returns only the place they picked, so a route
    string expands again with the DUPLICATE FOUND answers in it."""

    def __init__(self, index, picks):
        self._index = index
        self._picks = picks

    def lookup(self, ident, *args, **kwargs):
        pick = self._picks.get(str(ident or "").upper())
        return [pick] if pick is not None else self._index.lookup(ident, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._index, name)

# Same orange abstract.py uses for an encoder-selected gauge.
_ENC_FOCUS_COLOR = "#ffa500"

# FPL list scrolling (PA15). Movement before a list press stops being a tap,
# in millimetres on the glass: a fingertip rolls 1-2 mm while it presses, so
# 3 mm keeps a sloppy tap a tap and still starts a drag almost at once.
DRAG_THRESHOLD_MM = 3.0
# How long a pilot scroll holds the list where it was left before the
# sequencer may scroll it to the active leg again.
SCROLL_HOLD_S = 20.0
# Fling: finger speed over the last _FLING_SAMPLE_S before lift-off, decaying
# exponentially with time constant _FLING_TAU_S. Speeds are mm/s so a fling
# travels the same distance on the glass whatever the panel's pixel density.
_FLING_SAMPLE_S = 0.1
_FLING_TAU_S = 0.35
_FLING_MIN_MM_S = 50.0
_FLING_STOP_MM_S = 10.0
_FLING_MAX_MM_S = 1500.0
_FLING_TICK_MS = 16

_ROW_MENU_ITEMS = (
    ("Insert Before", "_row_menu_insert_before"),
    ("Insert After", "_row_menu_insert_after"),
    ("Load Airway", "_row_menu_load_airway"),
    ("Activate Leg", "_row_menu_activate_leg"),
    ("Direct To", "_row_menu_direct_to"),
    ("Hold...", "_row_menu_hold"),
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
    ("Load Airway", "_seg_menu_load_airway"),
    ("Activate", "_seg_menu_activate"),
    ("Remove Airway", "_seg_menu_remove"),
)
# PA7: a loaded procedure's segment row. The approach and its missed
# approach are one block: each opens this menu, and Remove takes both.
# Load Airway is offered on a departure only (G87, pyEfis #474): the block's
# last fix has no plain row of its own to load one from.
_PROC_SEG_MENU_ITEMS = (
    ("Show Fixes", "_seg_menu_show_fixes"),
    ("Load Airway", "_seg_menu_load_airway"),
    ("Activate", "_seg_menu_activate"),
    ("Select", "_seg_menu_select_procedure"),
    ("Remove", "_seg_menu_remove_procedure"),
)
# One fix inside a segment: from a nested working row or the Show Fixes sheet.
_SEG_FIX_MENU_ITEMS = (
    ("Direct To", "_seg_fix_direct_to"),
    ("Activate Leg", "_seg_fix_activate_leg"),
    ("Hold...", "_seg_fix_hold"),
    ("WPT Info", "_seg_fix_wpt_info"),
    ("Remove Hold", "_seg_fix_remove_hold"),
)
# Menu items offered only where a hold can be built, or removed (HOLDFIX1).
_HOLD_MENU_ATTRS = frozenset({"_row_menu_hold", "_seg_fix_hold"})

# Every text size below is a fraction of some *height* (header/footer/row/box),
# while the rects the text sits in are fractions of the *width*. In a pane
# taller than it is wide (the Beelink's ~657x1003 Flight Plan tab) the text
# outgrows its rects and, since Qt does not clip drawText, labels run into
# each other. So fonts also shrink by (w/h)/_FONT_FIT_ASPECT, capped at 1.0:
# square and landscape panes (w/h >= 1.0) keep exactly the original sizes.
_FONT_FIT_ASPECT = 1.0


class FlightPlan(QWidget):
    """The `flight_plan` instrument widget."""

    # The bridge calls back on whichever thread wrote the key (the FIX
    # client thread on a live bus); a QTimer may only be started from the
    # thread it lives in, so the commit timer is armed through this signal.
    _arm_commit_timer = pyqtSignal()
    # An OBS command's refusal text, re-emitted onto the GUI thread: the
    # FPLCMDACK callback runs on the gateway client's thread.
    _obs_refused = pyqtSignal(str)
    # Hold at present position (HOLDFIX2): the ACT for the hold slot, sent
    # from the GUI thread once the engine has loaded the route (the engine's
    # answer arrives on the gateway client's thread), and its refusal text.
    _send_hold_act = pyqtSignal(int)
    _hold_act_refused = pyqtSignal(str)
    # Activate Leg, Activate (to entry) and the far-fix Yes (G97, AER-6536):
    # the engine's refusal of that ACT, re-emitted onto the GUI thread.
    _act_refused = pyqtSignal(str)

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
        # each already sized from its own region. None = 100%. Expects the
        # fraction screenbuilder_preferences.normalize_font_percent produces. See
        # _font_scale(); apply_options also setattr's it after construction.
        self.font_percent = font_percent

        # apply="attr" InstrumentSpec Props -- keep in lockstep with the
        # registry record (screenbuilder_factory.py) and its defaults.
        self.flightplan_dir = ""
        self.nasr_db_path = ""
        self.navaid_db_path = ""
        self.procedures_db_path = ""
        self.plates_path = ""
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
        # PA7: the speed a time-coded hold's leg (one minute) is turned into
        # a distance at, since the bus carries no leg time.
        self.hold_speed_kt = fp_proc.HOLD_SPEED_KT

        self._page = None
        self._plan = fp_model.FlightPlan()
        self._plan_dirty = False
        # The engine outputs as last read (FixBridge.read_engine). A bus
        # write only marks them stale; _engine_value() reads them again on
        # the next use, so the 25 writes of an engine cycle cost one read,
        # and none for a page that is not painted.
        self._engine = {}
        self._engine_stale = False
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
        # Activate Leg from a far from-fix (FPACT1, AER-5801): the pending
        # {"slot", "from_id", "dist_nm"} the pilot is asked about before ACT.
        self._act_confirm = None
        # A plan offered for the pilot to accept or reject (EFB4b, AER-6706),
        # whatever its source: a dict -- "key" (what identifies this offer),
        # "plan" (the model.FlightPlan Accept commits), "title", "note",
        # "staged" (True when it came from a staging block on the bus),
        # "valid" (a callable: is it still exactly what the pilot reviewed?)
        # and "answer" (a callable taking accepted, run after Accept's commit
        # or on Reject) -- or None. _offer_open is True while the sheet is up.
        self._offer = None
        self._offer_open = False
        # Route-string entry (RTE1b, AER-6785): the route being expanded --
        # "text" as entered, "runways" (airport -> runway, for a SID or STAR
        # that needs one), "picks" (ident -> the place chosen where it names
        # two) and "ident" (the one the DUPLICATE FOUND chooser is answering)
        # -- or None. _route_runway is the RunwayNeededError the runway
        # chooser is answering, or None.
        self._route = None
        self._route_runway = None

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

        # PROC page (PA7). _proc is the selection being built: kind, airport,
        # proc (a procedures.Procedure), transition, runway and the page's
        # message; _proc_picker the field whose choice list is open.
        self._proc = None
        self._proc_picker = None

        self._catalog_row_menu = None
        self._catalog_confirm = None
        self._catalog_message = ""
        self._catalog_dist_cache = {}

        # Charts page (PA12). _charts is the page's state: the airport, the
        # chart on view (None for the airport's chart list), the list's
        # first row, the zoom step, the page point at the view's centre as
        # a fraction of the page, and a message. _plate_view is where the
        # last paint put the chart (for a pan drag), _plate_drag the drag.
        self._charts = None
        self._plate_view = None
        self._plate_drag = None
        self._plate_renderer = plate_render.PlateRenderer()

        self._modal = None
        self._uwpt_new = None
        self._uwpt_edit = None
        # Hold at a fix (HOLDFIX1, AER-6210): the clearance being entered,
        # or None. See _open_hold_editor for the fields.
        self._hold_edit = None
        # Hold at present position (HOLDFIX2, AER-6322): the hold slot to
        # ACT once the engine loads the commit that carries it, or None.
        # See _take_pending_hold_act.
        self._pending_hold_act = None

        self._waypoint_index = None
        self._waypoint_index_key = None
        self._procedure_index = None
        self._procedure_index_key = None
        self._airway_graph = None
        self._airway_graph_key = None
        self._plate_index = None
        self._plate_index_key = None
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

        # FPL list scrolling (PA15, AER-2087). _list_scroll is how far the
        # list content is scrolled, in px. _list_view describes the list as
        # the last paint laid it out (None when no list is under the finger:
        # another page, or an overlay on top); _press is the gesture in
        # progress; _followed_active is the active leg the list last scrolled
        # to, so the sequencer only moves it on a change.
        self.drag_threshold_mm = DRAG_THRESHOLD_MM
        self.scroll_hold_s = SCROLL_HOLD_S
        self._list_scroll = 0.0
        self._list_view = None
        # The FPL message strip's rect as last painted (AER-6156), or None.
        self._message_rect = None
        self._press = None
        self._last_pilot_scroll = None
        self._followed_active = None
        self._fling_v = 0.0
        self._fling_last = None
        self._fling_timer = QTimer(self)
        self._fling_timer.setInterval(_FLING_TICK_MS)
        self._fling_timer.timeout.connect(self._fling_tick)

        self._wpt_timer = QTimer(self)
        self._wpt_timer.setInterval(1000)
        self._wpt_timer.timeout.connect(self.update)

        # Refused commits (G61, pyEfis #380). After the engine refuses a
        # route the slots on the bus still hold it, and only FPLLDSEQ says
        # which commit the engine flies. _flown_plan is the last plan seen
        # loaded (None when none has been seen this session); _refusal is
        # (FPLSEQ, reason) of the refused commit on the bus; _draft is that
        # commit's route, kept for the pilot to reopen; _draft_open is True
        # while the page shows the draft instead of the flown plan.
        # _pending_seq is a commit seen arriving that the engine has not
        # answered yet; _seen_seq the last FPLSEQ this widget has read.
        self.commit_answer_ms = COMMIT_ANSWER_MS
        self._flown_plan = None
        self._refusal = None
        self._draft = None
        self._draft_open = False
        self._pending_seq = None
        self._seen_seq = None
        # (FPLSEQ, plan) of this page's last commit: the plan as committed,
        # with the fields the bus does not carry (_with_off_bus_fields).
        self._committed = None
        # FixBridge.route_key() at the last plan sync: the bridge notifies
        # on every engine output write, and only a change of this is a
        # reason to read the route again (_on_bridge_change). _synced_route
        # is the route block read then; _route_drifted() checks the bus
        # against it at most every route_verify_s.
        self._synced_route_key = None
        self._synced_route = None
        self.route_verify_s = ROUTE_VERIFY_S
        self._route_checked_at = 0.0
        self._clock = time.monotonic
        self._commit_timer = QTimer(self)
        self._commit_timer.setSingleShot(True)
        self._commit_timer.timeout.connect(self._on_commit_timeout)
        self._arm_commit_timer.connect(self._start_commit_timer)
        self._obs_refused.connect(self._show_obs_refusal)
        self._send_hold_act.connect(self._act_hold_slot)
        self._hold_act_refused.connect(self._show_hold_act_refusal)
        self._act_refused.connect(self._show_act_refusal)

        self._bridge = fp_fixbridge.FixBridge(fix)
        if self._bridge.available:
            self._sync_plan_from_bridge()
            self._sync_engine_from_bridge()
            self._bridge.add_listener(self._on_bridge_change, keyed=True)
            self._sync_staged_from_bridge()
            msg_item = self._bridge._get("FPLMSG")
            msg_item.valueWrite[msg_item.dtype].connect(self._on_fplmsg)
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
        if kiosk.locked() and page != "fpl":
            # DEMO4: every other page edits the plan or the catalog.
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
        elif page == "proc":
            self._open_proc_page()
        elif page == "charts":
            self._open_charts_page()

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
        self._hold_edit = None
        self._proc_picker = None
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
        if kiosk.locked():
            return
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
        if not self._targeted(group) or kiosk.locked():
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
        elif matches:
            # An ident that names two places is shown, never guessed (FPA5):
            # the DTO page opens on its chooser, and the pick goes direct.
            self._open_dto_page()
            self._entry_field = ident.strip().upper()
            self._entry_message = "DUPLICATE FOUND"
            self._entry_dupe_choices = matches
            self._reveal()

    # -- bridge sync -------------------------------------------------------
    def _sync_plan_from_bridge(self, answered=False):
        """Take the route on the bus as the plan -- but only once the
        engine has loaded it (G61, pyEfis #380).

        The bus is the truth (RS2, route segments brief guardrail 1): the
        segment table says which slots are an airway, so there is nothing
        to carry over from the plan as it stood before this sync. The slots
        are only the flight plan when ``FPLLDSEQ`` equals ``FPLSEQ``. A
        commit the engine has not answered yet leaves the page as it is
        (the pilot's own edit stays on screen, with no flicker). A refused
        one -- answered with ``FPLMSG`` (*answered*), unanswered for
        ``commit_answer_ms``, or already on the bus when this widget first
        looks -- puts the flown plan back on the page and keeps the refused
        route as a draft. A gateway without ``FPLLDSEQ`` keeps the
        behaviour from before the key."""
        # The key before the route: a commit landing between the two reads
        # leaves a key older than the route, and its own notification then
        # syncs again.
        self._synced_route_key = self._bridge.route_key()
        route = self._bridge.read_route()
        if route is None:
            return
        self._synced_route = route
        self._route_checked_at = self._clock()
        seq = int(self._bridge._get("FPLSEQ").value)
        plan = self._with_off_bus_fields(fp_fixbridge.route_to_plan(route), seq)
        first_look, self._seen_seq = self._seen_seq is None, seq
        loaded = self._loaded_seq()
        if loaded is None or loaded == seq:
            self._plan = plan
            self._flown_plan = copy.deepcopy(plan)
            self._refusal = self._draft = self._pending_seq = None
            self._draft_open = False
            self._take_pending_hold_act(seq)
            return
        if self._refusal is not None and self._refusal[0] == seq:
            return
        if not (first_look or answered):
            if self._pending_seq != seq:
                # A new commit on its way to the engine.
                self._pending_seq = seq
                self._arm_commit_timer.emit()
            return
        # On a first look the refusal happened before this widget existed,
        # and FPLMSG on the bus is the engine's answer to it.
        self._refuse(seq, plan, self._bridge._get("FPLMSG").value)

    def _with_off_bus_fields(self, plan, seq):
        """*plan*, read off the bus at *seq*, with the fields the bus does
        not carry put back from this page's commit of it (FPA2, AER-6419):
        each waypoint's name, alt_ft, comment and extra, each segment's
        cycle and extra (the bus has one FPLDBCYC for the plan), and the
        plan's comment, created, modified, source and extra. Without them
        Store rewrote a stored route bare. Only when *seq* is that commit
        and its fixes and segments are still the ones on the bus; a route
        another writer committed (the map, a second display) is the bus's
        alone. Every field the bus carries stays as read."""
        if self._committed is None or self._committed[0] != seq:
            return plan
        mine = self._committed[1]
        if ([(s.kind, s.ident, [w.id for w in s.legs]) for s in plan.segments]
                != [(s.kind, s.ident, [w.id for w in s.legs]) for s in mine.segments]):
            return plan
        for seg, own in zip(plan.segments, mine.segments):
            seg.cycle = own.cycle
            seg.extra = dict(own.extra)
            for wp, w in zip(seg.legs, own.legs):
                wp.name, wp.alt_ft, wp.comment = w.name, w.alt_ft, w.comment
                wp.extra = dict(w.extra)
        plan.comment, plan.created, plan.modified = mine.comment, mine.created, mine.modified
        plan.source, plan.extra = mine.source, dict(mine.extra)
        return plan

    def _refuse(self, seq, plan, reason):
        self._pending_seq = None
        self._pending_hold_act = None
        # G61a: the engine's code in plain words, naming the waypoint.
        self._refusal = (seq, fp_refusal.plain_reason(reason, plan) or "NO ENGINE ANSWER")
        self._draft = plan
        if self._draft_open:
            # The pilot is correcting the draft: the refused edit is the new
            # draft, and they stay in it.
            self._plan = copy.deepcopy(plan)
        else:
            self._plan = (copy.deepcopy(self._flown_plan) if self._flown_plan is not None
                          else fp_model.FlightPlan())

    def _loaded_seq(self):
        """``FPLLDSEQ``, or None when the gateway does not publish it."""
        try:
            return int(self._bridge._get("FPLLDSEQ").value)
        except (KeyError, TypeError, ValueError):
            return None

    def _on_fplmsg(self, *_args):
        # The engine's answer to a commit it refused. Only a commit still
        # waiting for an answer takes it: FPLMSG also answers commands. An
        # accepted commit's active-leg notice is toasted either way.
        pending = self._pending_seq is not None
        if pending:
            self._sync_plan_from_bridge(answered=True)
            self._sync_engine_from_bridge()
        if self._show_active_leg_notice() or pending:
            self.update()

    def _show_active_leg_notice(self):
        """An accepted commit that dropped the active leg says why on
        ``FPLMSG``, after ``FPLLDSEQ`` (fix-gateway HOLDFIX0): toast it in
        plain words (G97, AER-6536). Only once the route on the bus is the
        one loaded, so a refusal is never read as a notice. True if shown."""
        msg = str(self._bridge._get("FPLMSG").value or "").strip()
        if msg not in fp_refusal.ACTIVE_LEG_NOTICES:
            return False
        if self._loaded_seq() != int(self._bridge._get("FPLSEQ").value):
            return False
        self._message = fp_refusal.plain_reason(msg)
        return True

    @pyqtSlot()
    def _start_commit_timer(self):
        self._commit_timer.start(self.commit_answer_ms)

    def _on_commit_timeout(self):
        if self._pending_seq is None:
            return
        self._pending_seq = None
        plan = self._bridge.read_plan()
        seq = int(self._bridge._get("FPLSEQ").value)
        if plan is not None and self._loaded_seq() not in (None, seq):
            self._refuse(seq, plan, "")
        self.update()

    def _plan_refused(self):
        return self._refusal is not None

    def _reopen_draft(self):
        """Refusal strip "Edit draft": the refused route back on the page
        for the pilot to correct. Every edit commits as usual; the engine
        loading one ends the draft."""
        if self._draft is None:
            return
        self._draft_open = True
        self._plan = copy.deepcopy(self._draft)
        self._list_scroll = 0.0
        self.update()

    def _show_flown_plan(self):
        """Refusal strip "Flown plan": back to the plan the engine flies;
        the draft is kept."""
        self._draft_open = False
        self._plan = (copy.deepcopy(self._flown_plan) if self._flown_plan is not None
                      else fp_model.FlightPlan())
        self._list_scroll = 0.0
        self.update()

    def _sync_engine_from_bridge(self):
        """Mark the engine outputs stale: the next _engine_value() reads
        them from the bus."""
        self._engine_stale = True

    def _on_bridge_change(self, key=None):
        """A write of *key*: ``FPLSEQ``, an engine output, a slot's
        ``FPLfTA`` or the staged direct-to point. The engine rewrites every
        output each guidance cycle, so this runs some 25 times a cycle, for
        each widget loaded, hidden or not: it reads nothing from the bus.
        The engine values are marked stale, and the route is read only when
        it or the engine's answer to it changed (``route_key``, which only
        a write of ``FPLSEQ`` or ``FPLLDSEQ`` moves). Reading the route on
        every call cost a FIX lookup per slot field plus a deep copy of the
        plan -- and put the bus route back over a catalog "Edit" working
        copy the pilot had not committed yet; building the engine dict on
        every call cost 27 lookups (pyEfis #480)."""
        if (((key is None or key in _ROUTE_KEY_WRITES)
                and self._bridge.route_key() != self._synced_route_key)
                or self._route_drifted()):
            self._sync_plan_from_bridge()
        if key is None or key in fp_fixbridge.STAGING_WATCH_KEYS:
            self._sync_staged_from_bridge()
        self._sync_engine_from_bridge()
        self.update()

    def _route_drifted(self):
        """True when the slots on the bus no longer match the route last
        synced although ``route_key`` has not moved: slot values that
        arrived after the key (a gateway reconnect re-sending the database
        in its own order), or a writer that did not write ``FPLSEQ`` last.
        Reading the route on every notification used to hide both within
        one engine cycle; this looks at most every ``route_verify_s``, so
        the page still converges on the bus without the per-write cost."""
        now = self._clock()
        if now - self._route_checked_at < self.route_verify_s:
            return False
        self._route_checked_at = now
        return self._bridge.read_route() != self._synced_route

    def _commit(self):
        if self._bridge.available:
            self._bridge.publish(self._plan)
            self._committed = (int(self._bridge._get("FPLSEQ").value),
                               copy.deepcopy(self._plan))
            self._sync_plan_from_bridge()
            self._sync_engine_from_bridge()
        self.update()

    # -- a plan offered for acceptance (EFB4b) ------------------------------
    def _sync_staged_from_bridge(self):
        """Offer a plan staged on the bus, or withdraw a staged offer once it
        is answered (here or on another display) or replaced by a newer one.
        A staged plan never replaces the route by itself: it is only
        offered, and only Accept commits it. An offer the pilot made on this
        page (not staged) is never displaced: a staged plan waits behind it
        and is offered once it is answered."""
        current = self._offer
        if current is not None and not current["staged"]:
            return
        for block in self._bridge.staging:
            seq = self._bridge.staged_seq(block)
            if seq is None:
                continue
            if current is not None and current["key"] == (block.prefix, seq):
                return
            offer = self._staged_offer(block)
            if offer is not None:
                self._set_offer(offer)
                return
        if current is not None and current["staged"]:
            self._set_offer(None)

    def _staged_offer(self, block):
        staged = self._bridge.read_staged(block)
        if staged is None or not staged.points:
            return None
        prompt = STAGING_PROMPTS.get(block.prefix, STAGING_PROMPT_DEFAULT)
        try:
            plan = fp_fixbridge.staged_to_plan(staged, prompt["source"])
        except fp_model.FlightPlanError:
            logger.warning("flight_plan: staged plan %s %d not offered", block.prefix,
                           staged.seq, exc_info=True)
            return None
        bridge = self._bridge
        return {"key": (block.prefix, staged.seq), "plan": plan, "staged": True,
                "title": f"{prompt['title']}: {plan.name or plan.default_name()}",
                "note": prompt["note"],
                "valid": lambda: bridge.read_staged(block) == staged,
                "answer": lambda accepted: bridge.answer_staged(block, staged.seq)}

    def _set_offer(self, offer):
        # A newer offer replaces the one under review: the sheet closes, so
        # the pilot never accepts a list that changed under their finger.
        self._offer = offer
        self._offer_open = False
        self._menu_scroll.pop("offer", None)

    def _open_offer(self):
        if self._offer is not None:
            self._offer_open = True
            self.update()

    def _close_offer(self):
        """Later: the sheet closes and the plan stays offered."""
        self._offer_open = False
        self.update()

    def _offer_accept(self):
        """Accept: the offered plan becomes the route, committed as any edit
        is (publish, then the engine's answer), then the offer is answered."""
        offer = self._offer
        if offer is None:
            return
        if not offer["valid"]():
            self._set_offer(None)
            self._sync_staged_from_bridge()
            self._message = "PLAN CHANGED - REVIEW AGAIN" if self._offer else ""
            self.update()
            return
        self._set_offer(None)
        self._plan = copy.deepcopy(offer["plan"])
        self._plan_dirty = False
        self._list_scroll = 0.0
        self._commit()
        offer["answer"](True)
        self._sync_staged_from_bridge()
        self.update()

    def _offer_reject(self):
        """Reject: the offer is answered and dropped; the route is untouched."""
        offer = self._offer
        if offer is None:
            return
        self._set_offer(None)
        offer["answer"](False)
        self._sync_staged_from_bridge()
        self.update()

    # -- a route typed or pasted (RTE1b) ------------------------------------
    def _menu_route(self, text="", message=""):
        """Menu Route: enter an ATC route string. It is expanded from the
        page's own navdata and offered on the Accept/Reject sheet; it never
        becomes the route by itself."""
        if kiosk.locked():
            return
        self._menu_open = False
        self._modal_open("ENTER ROUTE", text, False, ROUTE_MAX_LEN, self._route_entered,
                         rows=KEYPAD_ROUTE_ROWS, message=message)

    def _route_entered(self, text):
        if not text.strip():
            self._route = None
            self.update()
            return
        self._route = {"text": text, "runways": {}, "picks": {}, "ident": None}
        self._route_expand()

    def _route_expand(self):
        """Expand the route as entered, with every runway and place the
        pilot has chosen so far. A SID or STAR that needs a runway asks for
        it; an ident that names two places opens DUPLICATE FOUND; any other
        refusal reopens the entry with the reason, so the pilot fixes the
        string rather than typing it again."""
        r = self._route
        var = self._bridge.magvar_or_none() if self._bridge.available else None
        try:
            hold_speed = float(self.hold_speed_kt)
        except (TypeError, ValueError):
            hold_speed = fp_proc.HOLD_SPEED_KT
        if not math.isfinite(hold_speed) or hold_speed <= 0:
            hold_speed = fp_proc.HOLD_SPEED_KT
        try:
            plan = fp_route_string.expand(
                r["text"], _PickedIndex(self._ensure_waypoint_index(), r["picks"]),
                self._ensure_airway_graph(), self._ensure_procedure_index(),
                runways=r["runways"], magvar=0.0 if var is None else var,
                hold_speed_kt=hold_speed, resolve_navaid=self._resolve_navaid)
        except fp_route_string.RunwayNeededError as e:
            self._route_runway = e
            self.update()
            return
        except fp_route_string.RouteStringError as e:
            # A pick that did not settle an ident (one that is also an
            # airway) is not asked again: the refusal says why.
            open_ = [k for k in e.ambiguous if k not in r["picks"]]
            if open_:
                r["ident"] = open_[0]
                self._entry_message = "DUPLICATE FOUND"
                self._entry_dupe_choices = list(e.ambiguous[open_[0]])
                self._entry_nav_index = None
                self.update()
                return
            self._route = None
            self._menu_route(r["text"], str(e))
            return
        self._route = None
        self._set_offer({"key": ("route", r["text"]), "plan": plan, "staged": False,
                         "title": f"{ROUTE_TITLE}: {plan.name}", "note": ROUTE_NOTE,
                         "valid": lambda: True, "answer": lambda accepted: None})
        # The pilot just asked for it: the sheet opens on it.
        self._open_offer()

    def _route_choose_runway(self, runway):
        e = self._route_runway
        self._route_runway = None
        if e is None or self._route is None:
            self.update()
            return
        self._route["runways"][e.airport] = runway
        self._route_expand()

    def _route_cancel_runway(self):
        """Back out of the runway chooser: to the entry, the text kept."""
        r = self._route
        self._route_runway = None
        self._route = None
        self._menu_route(r["text"] if r else "")

    def _route_choose_place(self, wp):
        r = self._route
        r["picks"][r["ident"]] = wp
        r["ident"] = None
        self._route_expand()

    def _route_cancel_place(self):
        r = self._route
        self._route = None
        self._menu_route(r["text"], "TWO PLACES NAMED: " + r["ident"])

    def _engine_value(self, key, default=None):
        if self._engine_stale:
            self._engine_stale = False
            self._engine = self._bridge.read_engine() or {}
        item = self._engine.get(key)
        return item.value if item is not None else default

    def _state_badge(self):
        return _STATE_BADGES.get(int(self._engine_value("FPLSTATE", 0) or 0), "")

    def _suspended_at_map(self):
        """True when the plan is suspended at the MAP auto-suspend (G49,
        pyEfis #330), where RESUME flies the missed approach.

        The engine says so on FPLSUSPMAP. pyEfis does not work it out from
        FPLSTATE / the active slot / FPLTF: the engine is the authority, and
        that inference mislabels a pilot SUSP past the MAP. An older gateway
        without the key reads as not-at-the-MAP, so it keeps "Resume".
        FPLSTATE is checked too because the two keys arrive one at a time:
        right after RESUME, FPLSTATE can already read LEG while FPLSUSPMAP
        still reads 1, and the banner must not flash a "Suspend" button."""
        return (int(self._engine_value("FPLSTATE", 0) or 0) == _STATE_SUSP
                and int(self._engine_value("FPLSUSPMAP", 0) or 0) == 1)

    def _in_hm_hold(self):
        """Flying a hold the pilot ends (HOLDFIX1): the engine reports
        FPLPHASE HOLD and the active slot is an ``HM``. RESUME there means
        "exit at the next fix passage" (fix-gateway PA13); an ``HF`` or
        ``HA`` hold ends by itself, so it offers no exit."""
        if str(self._engine_value("FPLPHASE", "") or "") != "HOLD":
            return False
        act = int(self._engine_value("FPLACTLEG", 0) or 0)
        wps = self._plan.waypoints
        return 1 <= act <= len(wps) and wps[act - 1].pt == "HM"

    def _suspend_label(self):
        """The menu's suspend/continue item. "Exit hold" in an ``HM`` hold,
        "Fly the missed" at the MAP auto-suspend, "Resume" for any other
        suspend; all three send RESUME."""
        if self._in_hm_hold():
            return "Exit hold"
        if int(self._engine_value("FPLSTATE", 0) or 0) != _STATE_SUSP:
            return "Suspend"
        return "Fly the missed" if self._suspended_at_map() else "Resume"

    def _approach_text(self):
        return _APR_TEXT.get(int(self._engine_value("FPLAPR", 0) or 0), "")

    @staticmethod
    def _cycle_text(cycle):
        """``(text, colour)`` for an AIRAC *cycle* label: ``AIRAC 2611``
        grey, or ``AIRAC 2609 EXPIRED`` amber once it has expired (PA9).
        Expired data is annunciated, never refused (brief guardrail 3)."""
        if fp_airac.is_expired(cycle):
            return f"AIRAC {cycle} EXPIRED", _EXPIRED_COLOR
        return f"AIRAC {cycle}", _CYCLE_COLOR

    def _procedure_text(self):
        """``(text, colour)`` for the header: the loaded approach's type and
        the cycle the plan's procedures came from (``RNAV  AIRAC 2611``), or
        None with no procedure loaded."""
        cycle = next((s.cycle for s in self._plan.segments if s.cycle), "")
        if not cycle:
            return None
        text, color = self._cycle_text(cycle)
        aprtype = fp_proc.approach_type(self._plan.segments)
        return (f"{aprtype}  {text}" if aprtype else text), color

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

    def _ensure_plate_index(self):
        key = self.plates_path
        if self._plate_index is not None and self._plate_index_key == key:
            return self._plate_index
        self._plate_index = fp_plates.PlateIndex(key or None)
        self._plate_index_key = key
        return self._plate_index

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

    def _valid_aircraft_position(self):
        """``(lat, lon)``, or None when LAT/LONG is missing, failed or old."""
        try:
            items = fix.db.get_item("LAT"), fix.db.get_item("LONG")
        except KeyError:
            return None
        if any(it.fail or it.old for it in items):
            return None
        return items[0].value, items[1].value

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
            return idx.recent_waypoints(types)
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
        # The PROC page's airport field opens this page over it, and back
        # out goes back there.
        back = {"proc_airport": "proc", "charts_airport": "charts"}.get(
            (self._entry_mode or {}).get("kind"), "fpl")
        self._entry_mode = None
        self._entry_field = ""
        self._entry_message = ""
        self._entry_dupe_choices = None
        self._entry_nav_index = None
        self._page = back
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
        if self._route is not None and self._route["ident"]:
            self._route_choose_place(wp)
            return
        self._select_waypoint(wp)

    def _cancel_dupe_chooser(self):
        self._entry_dupe_choices = None
        if self._route is not None and self._route["ident"]:
            self._route_cancel_place()
            return
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
        if mode.get("kind") in ("proc_airport", "charts_airport"):
            self._entry_tab = "Nearest"
            self._entry_type_filter = "Apt"
        self._page = "entry"
        self.update()

    def _select_waypoint(self, wp):
        mode = self._entry_mode or {"kind": "append"}
        kind = mode.get("kind")
        i = mode.get("index")
        new_wp = fp_model.Waypoint(id=wp.id, type=wp.type, lat=wp.lat, lon=wp.lon,
                                    name=getattr(wp, "name", "") or "")
        if kind == "proc_airport":
            self._ensure_waypoint_index().recent.push(wp.id, wp)
            self._close_entry()
            self._proc_set_airport(wp.id)
            return
        if kind == "charts_airport":
            self._ensure_waypoint_index().recent.push(wp.id, wp)
            self._close_entry()
            self._charts_set_airport(wp.id)
            return
        if kind == "direct_to":
            if self._bridge.available:
                self._bridge.stage_direct_to(new_wp)
                self._bridge.command("DTO")
            self._message = ""  # a SELECT A WAYPOINT prompt is answered (#326)
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
        self._ensure_waypoint_index().recent.push(wp.id, wp)
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
        self._activate_leg(i + 1)

    def _activate_leg(self, slot):
        """Send ``ACT slot``, but first ask when the leg's from-fix is more
        than ACT_CONFIRM_NM from the aircraft (FPACT1): an approach later in
        the plan can start from a fix far behind, and the engine flies the
        leg it is given. No position, or slot 1 (the engine starts from the
        aircraft): no question."""
        if not self._bridge.available:
            return
        pos = self._valid_aircraft_position()
        if slot >= 2 and pos is not None and slot - 2 < len(self._plan.waypoints):
            frm = self._plan.waypoints[slot - 2]
            dist = fp_geo.distance_nm(pos[0], pos[1], frm.lat, frm.lon)
            if dist > ACT_CONFIRM_NM:
                self._act_confirm = {"slot": slot, "from_id": frm.id, "dist_nm": dist}
                self.update()
                return
        self._send_act(slot)

    def _act_confirm_yes(self):
        c = self._act_confirm
        self._act_confirm = None
        if c is not None and self._bridge.available:
            self._send_act(c["slot"])
        self.update()

    def _send_act(self, slot):
        """``ACT slot``; a refusal shows the engine's reason in plain words,
        as the PPOS hold's ACT does (G97, AER-6536)."""
        self._bridge.command("ACT", slot, on_ack=self._on_act_ack)

    def _on_act_ack(self, _seq, ok, msg):
        if not ok:
            self._act_refused.emit(str(msg or ""))

    @pyqtSlot(str)
    def _show_act_refusal(self, msg):
        self._message = fp_refusal.plain_reason(msg) or "LEG NOT ACTIVATED"
        self.update()

    def _act_confirm_no(self):
        self._act_confirm = None
        self.update()

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
        idents = graph.airways_through_fix(wp.id, at=(wp.lat, wp.lon))
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
            entry = picker["entry_wp"]
            expansion = graph.expand(picker["ident"], entry.id, exit_fix_id,
                                     entry_at=(entry.lat, entry.lon))
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
        if self._draft_open:
            # FPLACTLEG counts legs of the flown plan, not of the draft.
            return None
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
        before FROM are not repeated: the header still names the entry. A
        procedure (PA7) is the same, except that its first fix is inside the
        block: there is no plain entry row before it."""
        rows = []
        for k, seg in enumerate(self._plan.segments):
            first, last = self._plan.segment_span(k)
            if seg.kind == "waypoint":
                rows.extend(("wpt", i) for i in range(first, last + 1))
                continue
            if seg.kind == "airway":
                rows.append(("wpt", first))
            # PA7: a procedure is one named block, its first fix included --
            # the leg into it is part of the procedure.
            rows.append(("seg", k))
            if active_idx is None or not (self._segment_first_leg(k) <= active_idx <= last):
                continue
            rows.append(("fix", active_idx - 1, "from"))
            rows.append(("fix", active_idx, "to"))
            if active_idx + 1 <= last:
                rows.append(("fix", active_idx + 1, "next"))
            ahead = last - (active_idx + 1)
            if ahead > 0:
                rows.append(("fold", k, ahead))
        return rows

    def _segment_first_leg(self, k):
        """Flat index of the first leg segment *k*'s row stands for: an
        airway's entry fix has a row of its own, a procedure's does not."""
        first, _ = self._plan.segment_span(k)
        return first + 1 if self._plan.segments[k].kind == "airway" else first

    def _segment_active(self, k, active_idx):
        _, last = self._plan.segment_span(k)
        return active_idx is not None and self._segment_first_leg(k) <= active_idx <= last

    def _segment_color(self, k, active_idx):
        _, last = self._plan.segment_span(k)
        if active_idx is None or active_idx < self._segment_first_leg(k):
            return self.future_color
        if active_idx <= last:
            return self.active_color
        return self.past_color

    def _segment_length(self, k):
        _, last = self._plan.segment_span(k)
        start = max(self._segment_first_leg(k) - 1, 0)
        return sum(self._plan.leg(i)[1] for i in range(start, last))

    @staticmethod
    def _mea_text(wp):
        alt = (wp.alt or "").strip()
        above = fp_vocab.ALT_AT_OR_ABOVE
        return alt.lstrip(above) if alt.startswith(above) else alt

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

    def _brg_text(self, brg_true):
        """A bearing for display: magnetic with ``MAGVAR``, the same as the
        HSI and the map (``map.pointer_banner_text``); suffixed ``°T`` and
        left true when the gateway publishes no variation (pyEfis #335)."""
        var = self._bridge.magvar_or_none() if self._bridge.available else None
        if var is None:
            return "%03d°T" % (int(round(brg_true)) % 360 or 360)
        return "%03d°" % (int(round(brg_true + var)) % 360 or 360)

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
        self._activate_leg(first + 1)

    def _seg_menu_load_airway(self):
        # From the segment's last fix, which ends it: insert_airway starts
        # the new airway at the fix after it, so the fix keeps one slot.
        _, last = self._plan.segment_span(self._seg_menu)
        self._close_seg_menu()
        self._open_airway_picker(last, self._plan.waypoints[last])

    def _seg_load_airway_offered(self, k):
        seg = self._plan.segments[k]
        return seg.kind in ("airway", "departure") and bool(seg.legs[-1].id)

    def _seg_menu_select_procedure(self):
        kind = _SEGMENT_PAGE_KIND[self._plan.segments[self._seg_menu].kind]
        self._seg_menu = None
        self._open_proc_page(kind)

    def _seg_menu_remove_procedure(self):
        kind = _SEGMENT_PAGE_KIND[self._plan.segments[self._seg_menu].kind]
        self._seg_menu = None
        self._proc_remove(kind)

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
        self._activate_leg(i + 1)
        self.update()

    def _seg_fix_wpt_info(self):
        i = self._seg_fix_menu
        self._seg_fix_menu = None
        self._open_wpt_info(self._plan.waypoints[i])

    def _seg_fix_hold(self):
        i = self._seg_fix_menu
        self._seg_fix_menu = None
        self._seg_fixes = None
        self._open_hold_editor(i)

    def _seg_fix_remove_hold(self):
        i = self._seg_fix_menu
        self._seg_fix_menu = None
        self._seg_fixes = None
        try:
            self._plan.remove_hold(i)
        except fp_model.FlightPlanError as e:
            self._message = str(e)
            self.update()
            return
        self._plan_dirty = True
        self._commit()

    def _menu_item_offered(self, attr, i):
        """Whether a fix menu shows *attr* for flat waypoint *i*: Hold...
        where a hold can be built, Remove Hold on a hold the pilot built
        (a coded one goes with its procedure)."""
        if attr in _HOLD_MENU_ATTRS:
            return fp_hold.can_hold_at(self._plan, i)
        if attr == "_seg_fix_remove_hold":
            return fp_hold.is_pilot_hold(self._plan.waypoints[i])
        return True

    # -- FPL page: hold at a fix (HOLDFIX1, AER-6210) ---------------------------
    def _row_menu_hold(self):
        i = self._row_menu_index
        self._close_row_menu()
        self._open_hold_editor(i)

    def _hold_speed(self):
        """The speed a leg in minutes is flown at: ``hold_speed_kt``, or
        proc_load's default when the option is not a usable speed."""
        try:
            speed = float(self.hold_speed_kt)
        except (TypeError, ValueError):
            return fp_proc.HOLD_SPEED_KT
        if not math.isfinite(speed) or speed <= 0:
            return fp_proc.HOLD_SPEED_KT
        return speed

    def _aircraft_altitude(self):
        """``ALT`` in ft, or None when it is missing, failed or old."""
        try:
            item = fix.db.get_item("ALT")
        except KeyError:
            return None
        if item.fail or item.old:
            return None
        try:
            return float(item.value)
        except (TypeError, ValueError):
            return None

    def _open_hold_editor(self, i):
        """The hold clearance for flat waypoint *i*, prefilled the way a
        pilot holds as they arrive: inbound on the course of the leg into
        the fix, the pattern on the far side, right turns, and the AIM leg
        time for the present altitude. With no leg into the fix, the
        pattern lies north on the 360 radial until the pilot says
        otherwise.

        Fields: ``index`` and ``fix`` (the slot and its ident), ``direction``
        (a compass point), ``ref`` (``radial`` or ``inbound``, what
        ``course`` is), ``typed`` (the pilot entered the course; until then
        a new direction moves it), ``turn``, ``leg`` and ``unit``
        (``MIN``/``NM``), and ``message`` (why Insert refused).

        As published (HOLDFIX3, AER-6328): ``published`` lists the NASR
        holds at the fix (``fp_hold.published_holds``), ``choosing`` is
        True while the pilot picks one of several, ``page`` is the chooser
        page, ``applied`` is the hold the fields were filled from (None
        once the pilot changes one), and ``std_time`` says the leg is the
        AIM standard time because NASR publishes none."""
        if not fp_hold.can_hold_at(self._plan, i):
            self._message = "NO HOLD HERE"
            self.update()
            return
        var = self._bridge.magvar_or_none() if self._bridge.available else None
        crs = fp_hold.arrival_course(self._plan, i, 0.0 if var is None else var,
                                     self._valid_aircraft_position())
        if crs is None:
            direction, ref, course = "N", "radial", fp_hold.DIRECTION_BEARING["N"]
        else:
            direction = fp_hold.nearest_direction(crs + 180.0)
            ref, course = "inbound", crs
        self._hold_edit = {
            "index": i, "ppos": False, "fix": self._plan.waypoints[i].id,
            "direction": direction,
            "ref": ref, "course": course, "typed": False, "turn": fp_hold.DEFAULT_TURN,
            "leg": fp_hold.default_leg_minutes(self._aircraft_altitude()), "unit": "MIN",
            "message": "",
            "published": fp_hold.published_holds(self.navaid_db_path,
                                                 self._plan.waypoints[i]),
            "choosing": False, "page": 0, "applied": None, "std_time": False,
        }
        self.update()

    def _hold_published(self):
        """PUBLISHED: fill the fields from the fix's one published hold, or
        list them when there are several."""
        e = self._hold_edit
        if len(e["published"]) == 1:
            self._hold_apply_published(e["published"][0])
        elif e["published"]:
            e["choosing"], e["page"] = True, 0
            self.update()

    def _hold_apply_published(self, ph):
        """The clearance as NASR publishes it: side, inbound course, turns,
        and the leg in miles, or for a timed hold the AIM standard time for
        the present altitude, marked STD TIME."""
        e = self._hold_edit
        e.update(direction=ph.direction, ref="inbound", course=ph.inbound, typed=True,
                 turn=ph.turn, choosing=False, applied=ph, message="")
        if ph.leg_nm is not None:
            e.update(leg=ph.leg_nm, unit="NM", std_time=False)
        else:
            e.update(leg=fp_hold.default_leg_minutes(self._aircraft_altitude()),
                     unit="MIN", std_time=True)
        self.update()

    def _hold_close_chooser(self):
        self._hold_edit["choosing"] = False
        self.update()

    def _hold_chooser_more(self):
        e = self._hold_edit
        e["page"] = (e["page"] + 1) % self._hold_chooser_pages()
        self.update()

    def _hold_chooser_pages(self):
        per = self._HOLD_CHOOSER_ROWS
        return max(1, -(-len(self._hold_edit["published"]) // per))

    def _hold_changed(self):
        """A field the pilot changed: the hold is no longer the published
        one it was filled from."""
        self._hold_edit["applied"] = None

    def _close_hold_editor(self):
        self._hold_edit = None
        self._modal = None
        self.update()

    def _hold_set_direction(self, direction):
        e = self._hold_edit
        self._hold_changed()
        e["direction"] = direction
        if not e["typed"]:
            radial = fp_hold.DIRECTION_BEARING[direction]
            e["course"] = radial if e["ref"] == "radial" else fp_hold.norm_course(radial + 180.0)
        e["message"] = ""
        self.update()

    def _hold_toggle_ref(self):
        """Radial <-> inbound course. The number shown becomes its
        reciprocal, so the hold described does not change until the pilot
        types a new one."""
        e = self._hold_edit
        e["ref"] = "inbound" if e["ref"] == "radial" else "radial"
        e["course"] = fp_hold.norm_course(e["course"] + 180.0)
        e["message"] = ""
        self.update()

    def _hold_edit_course(self):
        title = "RADIAL" if self._hold_edit["ref"] == "radial" else "INBOUND COURSE"
        self._modal_open(title, "", True, 3, self._hold_course_entered)

    def _hold_course_entered(self, value):
        e = self._hold_edit
        if e is None:
            return
        try:
            course = float(value)
        except (TypeError, ValueError):
            course = -1.0
        if not 0.0 <= course <= 360.0:
            e["message"] = "BAD COURSE"
        else:
            e["course"] = fp_hold.norm_course(course)
            e["typed"] = True
            self._hold_changed()
            e["message"] = ""
        self.update()

    def _hold_set_turn(self, turn):
        if turn != self._hold_edit["turn"]:
            self._hold_changed()
        self._hold_edit["turn"] = turn
        self.update()

    def _hold_edit_leg(self):
        self._modal_open(f"LEG ({self._hold_edit['unit']})", "", True, 4,
                         self._hold_leg_entered)

    def _hold_leg_entered(self, value):
        e = self._hold_edit
        if e is None:
            return
        try:
            leg = float(value)
        except (TypeError, ValueError):
            leg = 0.0
        if not (math.isfinite(leg) and leg > 0.0):
            e["message"] = "BAD LEG"
        else:
            e["leg"] = leg
            e["message"] = ""
            e["std_time"] = False       # the pilot's time, not the standard
            self._hold_changed()
        self.update()

    def _hold_toggle_unit(self):
        """Minutes <-> miles, converted at the hold speed so the leg does
        not change until the pilot types a new one."""
        e = self._hold_edit
        speed = self._hold_speed()
        if e["unit"] == "MIN":
            e["unit"], e["leg"] = "NM", fp_hold.minutes_to_nm(e["leg"], speed)
        else:
            e["unit"], e["leg"] = "MIN", round(e["leg"] * 60.0 / speed, 1)
        e["message"] = ""
        self.update()

    def _hold_resolve(self):
        """``(waypoint, None)`` for the clearance as entered, or
        ``(None, reason)``."""
        e = self._hold_edit
        try:
            if e["ref"] == "radial":
                inbound = fp_hold.inbound_course(e["direction"], radial=e["course"])
            else:
                inbound = fp_hold.inbound_course(e["direction"], inbound=e["course"])
            dst = fp_hold.leg_nm(e["leg"], e["unit"], self._hold_speed())
            if e["ppos"]:
                pos = self._valid_aircraft_position()
                if pos is None:
                    return None, NO_GPS_POSITION
                at = fp_hold.present_position_waypoint(*pos)
            else:
                at = self._plan.waypoints[e["index"]]
            wp = fp_hold.hold_waypoint(at, inbound, e["turn"], dst)
        except (fp_hold.HoldError, IndexError) as ex:
            return None, str(ex)
        return wp, None

    def _hold_insert(self):
        """Insert the hold slot after its fix and commit. The engine keeps
        the active leg through the commit (HOLDFIX0, fix-gateway #223)."""
        e = self._hold_edit
        if e is None:
            return
        wp, error = self._hold_resolve()
        if wp is None:
            e["message"] = error
            self.update()
            return
        if e["ppos"]:
            self._hold_insert_ppos(wp)
            return
        try:
            self._plan.insert_hold(e["index"], wp)
        except fp_model.FlightPlanError as ex:
            e["message"] = str(ex)
            self.update()
            return
        self._hold_edit = None
        self._message = f"HOLD AT {wp.id}"
        self._plan_dirty = True
        self._commit()

    # -- FPL page: hold at present position (HOLDFIX2, AER-6322) ----------------
    def _menu_hold_ppos(self):
        self._menu_open = False
        self._open_ppos_hold_editor()

    def _present_track(self):
        """The ground track now, magnetic: ``TRACKM``, else ``TRACK`` with
        ``MAGVAR``. None when neither is usable."""
        for key in ("TRACKM", "TRACK"):
            try:
                item = fix.db.get_item(key)
            except KeyError:
                continue
            if item.fail or item.old:
                continue
            try:
                trk = float(item.value)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(trk):
                continue
            if key == "TRACK":
                var = self._bridge.magvar_or_none() if self._bridge.available else None
                if var is None:
                    return None
                trk += var
            return fp_hold.norm_course(trk)
        return None

    def _open_ppos_hold_editor(self):
        """The hold editor for a hold at present position, prefilled to
        hold on the present track: inbound on it, the pattern on the far
        side, right turns and the AIM leg time. The fix is ``PPOS`` where
        the aircraft is when Insert is pressed, so the hold starts with a
        direct entry at once. No usable GPS position: refused with a
        message. With no track, the pattern lies north on the 360 radial,
        as for a fix with no leg into it. A draft on the page gives way to
        the flown plan: the hold is built on the route being flown."""
        if self._valid_aircraft_position() is None:
            self._message = NO_GPS_POSITION
            self.update()
            return
        if self._draft_open:
            self._show_flown_plan()
        trk = self._present_track()
        if trk is None:
            direction, ref, course = "N", "radial", fp_hold.DIRECTION_BEARING["N"]
        else:
            direction = fp_hold.nearest_direction(trk + 180.0)
            ref, course = "inbound", trk
        self._hold_edit = {
            "index": None, "ppos": True, "fix": fp_hold.PPOS_IDENT, "direction": direction,
            "ref": ref, "course": course, "typed": False, "turn": fp_hold.DEFAULT_TURN,
            "leg": fp_hold.default_leg_minutes(self._aircraft_altitude()), "unit": "MIN",
            "message": "",
            # Present position has no published hold (AER-6328).
            "published": [], "choosing": False, "page": 0, "applied": None,
            "std_time": False,
        }
        self.update()

    def _hold_insert_ppos(self, wp):
        """Put the ``PPOS`` fix and its hold slot *wp* in front of the
        active leg's TO fix (:func:`fp_hold.ppos_insert_index`), commit, and
        ACT the hold slot once the engine has loaded the route."""
        e = self._hold_edit
        at = fp_hold.present_position_waypoint(wp.lat, wp.lon)
        active = self._active_index()
        plan = copy.deepcopy(self._plan)
        i = fp_hold.ppos_insert_index(plan, None if active is None else active + 1)
        try:
            plan.insert_before(i, at)
            plan.insert_hold(i, wp)
        except fp_model.FlightPlanError as ex:
            e["message"] = str(ex)
            self.update()
            return
        self._plan = plan
        self._hold_edit = None
        self._message = f"HOLD AT {at.id}"
        self._plan_dirty = True
        if self._bridge.available:
            self._pending_hold_act = {"slot": i + 2, "fix": at,
                                      "after_seq": self._bridge._get("FPLSEQ").value}
        self._commit()

    def _take_pending_hold_act(self, seq):
        """The engine loaded route *seq*: ACT the PPOS hold slot if this is
        the commit that carries it. A slot number means nothing on another
        route, so it is sent only when the loaded plan has this PPOS fix
        and its hold there. A refused commit (``_refuse``) or any other
        route drops it; nothing is activated on a route the pilot did not
        build. A route seen before the commit landed (*seq* still the one
        before it) leaves it waiting."""
        p = self._pending_hold_act
        if p is None or seq == p["after_seq"]:
            return
        self._pending_hold_act = None
        if fp_hold.is_ppos_pair(self._plan, p["slot"] - 2, p["fix"]):
            self._send_hold_act.emit(p["slot"])

    @pyqtSlot(int)
    def _act_hold_slot(self, slot):
        if self._bridge.available:
            self._bridge.command("ACT", slot, on_ack=self._on_hold_act_ack)

    def _on_hold_act_ack(self, _seq, ok, msg):
        if not ok:
            self._hold_act_refused.emit(str(msg or ""))

    @pyqtSlot(str)
    def _show_hold_act_refusal(self, msg):
        self._message = fp_refusal.plain_reason(msg) or "HOLD NOT ACTIVATED"
        self.update()

    # -- FPL page: footer / menu ---------------------------------------------
    def _footer_add(self):
        self._open_entry({"kind": "append", "index": None})

    def _footer_direct_to(self):
        self._open_dto_page()

    def _footer_catalog(self):
        self._open_catalog_page()

    def _footer_proc(self):
        self._open_proc_page()

    def _footer_charts(self):
        self._open_charts_page()

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
            resume = state == _STATE_SUSP or self._in_hm_hold()
            self._bridge.command("RESUME" if resume else "SUSP")
        self._menu_open = False
        self.update()

    def _obs_label(self):
        """The menu's OBS item: "OBS" to enter GPS OBS, "OBS Off" while the
        engine is in it (FPLSTATE = 4)."""
        state = int(self._engine_value("FPLSTATE", 0) or 0)
        return "OBS Off" if state == _STATE_OBS else "OBS"

    def _menu_obs(self):
        """Enter GPS OBS on the current desired track (FPLCRS), so the
        needle does not move until the pilot turns CRS; or leave it. The
        engine decides whether OBS is possible here, and a refusal shows
        its FPLMSG text."""
        if self._bridge.available:
            state = int(self._engine_value("FPLSTATE", 0) or 0)
            if state == _STATE_OBS:
                arg = "OFF"
            else:
                try:
                    arg = "%d" % (int(round(float(self._engine_value("FPLCRS", 0.0) or 0.0))) % 360)
                except (TypeError, ValueError):
                    arg = "0"
            self._bridge.command("OBS", arg, on_ack=self._on_obs_ack)
        self._menu_open = False
        self.update()

    def _on_obs_ack(self, _seq, ok, msg):
        if not ok:
            self._obs_refused.emit(str(msg or ""))

    @pyqtSlot(str)
    def _show_obs_refusal(self, msg):
        self._message = fp_refusal.plain_reason(msg) or "OBS REFUSED"
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
        # The DTO page's prompt must not outlive the page: it would read as
        # "the direct-to did not take" over the FPL header (#326).
        self._message = ""
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
        self._message = ""
        self.update()

    def _dto_select_nearest(self, wp):
        self._dto_target = ("wp", None, wp)
        self._message = ""
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

    # -- PROC page (PA7, billmallard/pyEfis#238) -------------------------------
    def _open_proc_page(self, kind=None):
        """The PROC page for *kind* (``departure``/``arrival``/``approach``),
        the approach by default, with the airport the guide would offer:
        the departure airport for a departure, the destination otherwise."""
        kind = kind if kind in fp_proc.PAGE_KINDS else "approach"
        self._proc = {"kind": kind, "airport": self._proc_default_airport(kind),
                      "proc": None, "transition": None, "runway": None, "message": ""}
        self._proc_picker = None
        self._page = "proc"
        self.update()

    def _close_proc(self):
        self._proc = None
        self._proc_picker = None
        self._page = "fpl"
        self.update()

    def _proc_select_kind(self, kind):
        if self._proc is None or self._proc["kind"] == kind:
            return
        self._open_proc_page(kind)

    def _proc_default_airport(self, kind):
        plain = [seg.legs[0] for seg in self._plan.segments if seg.kind == "waypoint"]
        airports = [w for w in plain if w.type == "airport"]
        if kind == "departure":
            wps = self._plan.waypoints
            if wps and wps[0].type == "airport":
                return wps[0].id
        elif airports:
            return airports[-1].id
        lat, lon = self._aircraft_position()
        near = self._ensure_waypoint_index().nearest(lat, lon, types=frozenset({"airport"}))
        return near[0][0].id if near else ""

    def _proc_set_airport(self, ident):
        if self._proc is None:
            return
        self._proc.update(airport=(ident or "").strip().upper(), proc=None, transition=None,
                          runway=None, message="")
        self.update()

    def _proc_choices(self, field):
        """The choice list behind *field*: ``[(label, value)]``."""
        st = self._proc
        index = self._ensure_procedure_index()
        if field == "proc":
            procs = index.procedures_at(st["airport"], fp_proc.PACK_KIND[st["kind"]])
            return [(fp_proc.procedure_name(pr), pr) for pr in procs]
        if st["proc"] is None:
            return []
        if field == "transition":
            return [(t, t) for t in fp_proc.transition_choices(index, st["proc"])]
        if field == "runway":
            return [(r, r) for r in fp_proc.runway_choices(index, st["proc"])]
        return []

    def _proc_open_field(self, field):
        st = self._proc
        if field == "airport":
            self._open_entry({"kind": "proc_airport"})
            return
        if field != "proc" and st["proc"] is None:
            st["message"] = f"SELECT {_PROC_KIND_LABELS[st['kind']].upper()} FIRST"
            self.update()
            return
        if not self._proc_choices(field):
            if field == "proc":
                st["message"] = (f"NO {_PROC_KIND_LABELS[st['kind']].upper()}S AT {st['airport']}"
                                 if self._ensure_procedure_index().ready
                                 else "NO PROCEDURES DATABASE")
            else:
                st["message"] = f"NO {field.upper()}S"
            self.update()
            return
        self._proc_picker = field
        self.update()

    def _proc_close_picker(self):
        self._proc_picker = None
        self.update()

    def _proc_pick(self, field, value):
        st = self._proc
        self._proc_picker = None
        st["message"] = ""
        if field == "proc":
            st.update(proc=value, transition=None, runway=None)
            # A single choice is no choice: take it (guide p. 3-64, "the
            # specified ... procedure appear[s] on the associated key").
            index = self._ensure_procedure_index()
            trans = fp_proc.transition_choices(index, value)
            runways = fp_proc.runway_choices(index, value)
            if len(trans) == 1:
                st["transition"] = trans[0]
            if len(runways) == 1:
                st["runway"] = runways[0]
        else:
            st[field] = value
        self.update()

    def _proc_field_value(self, field):
        st = self._proc
        if field == "airport":
            return st["airport"]
        if field == "proc":
            return fp_proc.procedure_name(st["proc"]) if st["proc"] else ""
        return st[field] or ""

    def _proc_fields(self):
        st = self._proc
        fields = list(_PROC_FIELDS[st["kind"]])
        if st["proc"] is not None and "runway" in fields and not fp_proc.needs_runway(
                self._ensure_procedure_index(), st["proc"]):
            fields.remove("runway")
        return fields

    def _proc_ready(self):
        st = self._proc
        return st["proc"] is not None and all(
            self._proc_field_value(f) for f in self._proc_fields())

    def _proc_airport_wp(self):
        st = self._proc
        for m in self._ensure_waypoint_index().lookup(st["airport"]):
            if m.type == "airport":
                return m
        return next((w for w in self._plan.waypoints
                     if w.type == "airport" and w.id == st["airport"]), None)

    def _resolve_navaid(self, ident, lat, lon):
        """An ``AF`` arc's centre: the navaid *ident* nearest (lat, lon)."""
        best = None
        for m in self._ensure_waypoint_index().lookup(ident or ""):
            if m.type not in ("vor", "ndb"):
                continue
            d = fp_geo.distance_nm(lat, lon, m.lat, m.lon)
            if best is None or d < best[0]:
                best = (d, m)
        return (best[1].lat, best[1].lon) if best is not None else None

    def _proc_assemble(self):
        st = self._proc
        origin = self._proc_airport_wp()
        if origin is None and st["kind"] == "departure":
            # A SID's first leg leaves the runway with no fix of its own.
            raise fp_proc.ProcedureLoadError(f"NO POSITION FOR {st['airport']}")
        var = self._bridge.magvar_or_none() if self._bridge.available else None
        try:
            hold_speed = float(self.hold_speed_kt)
        except (TypeError, ValueError):
            hold_speed = fp_proc.HOLD_SPEED_KT
        if not math.isfinite(hold_speed) or hold_speed <= 0:
            hold_speed = fp_proc.HOLD_SPEED_KT
        return fp_proc.assemble(self._ensure_procedure_index(), st["proc"], st["transition"],
                                st["runway"], magvar=0.0 if var is None else var,
                                hold_speed_kt=hold_speed, resolve_navaid=self._resolve_navaid,
                                origin=origin)

    def _proc_preview(self):
        """``(segments, error)`` for the selection as it stands; both None
        while it is incomplete."""
        if self._proc is None or not self._proc_ready():
            return None, None
        try:
            return self._proc_assemble(), None
        except fp_proc.ProcedureLoadError as e:
            return None, str(e)

    def _proc_load(self):
        """Load the selection into the flight plan, replacing a loaded
        procedure of the same kind, and open the FPL page (guide p. 3-73:
        "Tap Load Approach. The Active FPL page opens"). A procedure the
        engine refuses is reported there, from FPLMSG, by the refusal
        strip; this page only refuses what it cannot assemble."""
        st = self._proc
        if not self._proc_ready():
            missing = next(f for f in self._proc_fields() if not self._proc_field_value(f))
            label = (_PROC_KIND_LABELS[st["kind"]] if missing == "proc"
                     else _PROC_FIELD_LABELS[missing])
            st["message"] = f"SELECT {label.upper()}"
            self.update()
            return
        plan = copy.deepcopy(self._plan)
        try:
            notices = fp_proc.insert(plan, st["kind"], self._proc_assemble(), st["airport"])
        except (fp_proc.ProcedureLoadError, fp_model.FlightPlanError) as e:
            st["message"] = str(e)
            self.update()
            return
        self._plan = plan
        self._plan_dirty = True
        self._close_proc()
        self._message = "; ".join(notices)
        self._commit()

    def _proc_remove(self, kind=None):
        kind = kind or (self._proc["kind"] if self._proc else None)
        if kind is None:
            return
        plan = copy.deepcopy(self._plan)
        if not fp_proc.remove(plan, kind):
            return
        self._plan = plan
        self._plan_dirty = True
        self._close_proc()
        self._commit()

    def _proc_loaded_ident(self, kind):
        ks = fp_proc.loaded(self._plan, kind)
        return self._plan.segments[ks[0]].ident if ks else ""

    # -- Charts page (PA12) ---------------------------------------------------
    def _loaded_approach(self):
        """``(airport, procedure, name)`` for the loaded approach: its name as
        the FPL page shows it (``ILS07``), the airport it serves and its
        procedures-pack row. ``(None, None, "")`` with no approach loaded;
        the airport or the row is None when it cannot be found.

        The segment carries no airport, so the airport is the first one the
        approach's name is found at, trying the airports the plan flies to
        after it, then every airport in the plan, then the airports nearest
        the approach's last fix."""
        segs = self._plan.segments
        k = next((n for n, seg in enumerate(segs) if seg.kind == "approach"), None)
        if k is None:
            return None, None, ""
        name = (segs[k].ident or "").strip().upper().split(".")[0]

        def airports(seq):
            return [s.legs[0].id for s in seq
                    if s.kind == "waypoint" and s.legs[0].type == "airport"]

        candidates = airports(segs[k + 1:]) + airports(segs)
        fixed = [wp for wp in segs[k].legs if wp.lat is not None and wp.lon is not None]
        if fixed:
            near = self._ensure_waypoint_index().nearest(
                fixed[-1].lat, fixed[-1].lon, types=frozenset({"airport"}))
            candidates += [entry[0].id for entry in near[:5]]
        index = self._ensure_procedure_index()
        for apt in dict.fromkeys(candidates):
            for proc in index.procedures_at(apt, "approach"):
                if fp_proc.procedure_name(proc) == name:
                    return apt, proc, name
        return (candidates[0] if candidates else None), None, name

    def _open_charts_page(self):
        """The Charts page: the loaded approach's plate when exactly one
        chart is that approach's (``PlateIndex.plate_for_approach``), else
        the chart list of the airport it serves -- or, with no approach
        loaded, of the destination. The list starts with the airport
        diagram (CAP-207)."""
        airport, proc, name = self._loaded_approach()
        index = self._ensure_plate_index()
        plate, message = None, ""
        if name:
            if airport and proc is not None:
                plate = index.plate_for_approach(airport, proc.ident, proc.approach_type)
            if plate is None and index.plates_at(airport or ""):
                message = f"NO SINGLE PLATE FOR {name}"
        if not airport:
            airport = self._proc_default_airport("approach")
        self._charts = {"airport": airport or "", "plate": plate, "first": 0, "zoom": 0,
                        "centre": (0.5, 0.5), "message": message}
        self._plate_drag = None
        self._page = "charts"
        self.update()

    def _close_charts(self):
        self._charts = None
        self._plate_drag = None
        self._page = "fpl"
        self.update()

    def _charts_set_airport(self, ident):
        if self._charts is None:
            return
        self._charts.update(airport=(ident or "").strip().upper(), plate=None, first=0,
                            message="")
        self.update()

    def _charts_change_airport(self):
        self._open_entry({"kind": "charts_airport"})

    def _charts_show(self, plate):
        self._charts.update(plate=plate, zoom=0, centre=(0.5, 0.5), message="")
        self.update()

    def _charts_list(self):
        self._charts.update(plate=None, message="")
        self._plate_drag = None
        self.update()

    def _charts_zoom(self, step):
        st = self._charts
        st["zoom"] = max(0, min(len(CHART_ZOOMS) - 1, st["zoom"] + step))
        if st["zoom"] == 0:
            st["centre"] = (0.5, 0.5)
        self.update()

    def _charts_fit(self):
        self._charts.update(zoom=0, centre=(0.5, 0.5))
        self.update()

    def _charts_scroll(self, delta):
        self._charts["first"] = max(0, self._charts["first"] + delta)
        self.update()

    def _plate_drag_start(self, x, y):
        """A press on a zoomed chart starts a pan; True if it did."""
        view = self._plate_view
        if (view is None or self._charts is None or self._charts["zoom"] == 0
                or not view["rect"].contains(QPointF(x, y))):
            return False
        self._plate_drag = {"x": x, "y": y, "centre": self._charts["centre"]}
        return True

    def _plate_drag_move(self, x, y):
        drag, view = self._plate_drag, self._plate_view
        if view is None or self._charts is None:
            return
        cx, cy = drag["centre"]
        # The page moves with the finger, so the point at the centre moves
        # the other way.
        self._charts["centre"] = (cx - (x - drag["x"]) / view["w"],
                                  cy - (y - drag["y"]) / view["h"])
        self.update()

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
    def _modal_open(self, title, value, numeric, max_len, on_enter, rows=None, message=""):
        """*rows* replaces the keypad's rows (a route needs a space key);
        *message* is shown under the value until the next key."""
        self._modal = {"title": title, "value": value, "numeric": numeric,
                        "max_len": max_len, "on_enter": on_enter, "rows": rows,
                        "message": message}
        self.update()

    def _modal_spaces(self):
        """Whether the open modal takes a space (a route string)."""
        m = self._modal
        return m is not None and m.get("rows") is not None and " " in "".join(m["rows"])

    def _modal_paste(self, text):
        """A paste into the open modal: upper case, line breaks as spaces,
        cut to what it holds. Into a route, a paste is more tokens: it is
        kept apart from what was already typed."""
        m = self._modal
        if m is None:
            return
        words = str(text or "").upper().split()
        if self._modal_spaces():
            value = " ".join(([m["value"].rstrip()] if m["value"].strip() else []) + words)
        else:
            value = m["value"] + "".join(words)
        m["value"] = value[:m["max_len"]]
        m["message"] = ""
        self.update()

    def _modal_key(self, ch):
        m = self._modal
        if m is None:
            return
        if len(m["value"]) < m["max_len"]:
            m["value"] += ch
        m["message"] = ""
        self.update()

    def _modal_backspace(self):
        m = self._modal
        if m is None:
            return
        m["value"] = m["value"][:-1]
        m["message"] = ""
        self.update()

    def _modal_clear(self):
        m = self._modal
        if m is None:
            return
        m["value"] = ""
        m["message"] = ""
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
        if self._entry_dupe_choices:
            # The route's DUPLICATE FOUND (RTE1b) opens over the FPL page.
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
        elif event.matches(QKeySequence.StandardKey.Paste) and self._modal_spaces():
            # A route pasted from an EFB or a clearance (RTE1b). Before the
            # characters: Ctrl+V can carry the text "v".
            self._modal_paste(QGuiApplication.clipboard().text())
        elif text and (text.isalnum() or text in ".-") and len(text) == 1:
            self._keyboard_char(text.upper())
        elif text == " " and self._modal_spaces():
            self._keyboard_char(" ")
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
        return not kiosk.locked()

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
            self._enc_reveal_focus(ring)
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
                self._seg_fix_menu, None if self._proc is None else self._proc["kind"],
                self._proc_picker, self._act_confirm is not None,
                self._hold_edit is not None, self._offer_open, self._route_runway is not None,
                None if self._charts is None else (self._charts["airport"],
                                                   self._charts["plate"]))

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
        elif self._hold_edit is not None and self._hold_edit["choosing"]:
            self._hold_close_chooser()
        elif self._hold_edit is not None:
            self._close_hold_editor()
        elif self._entry_dupe_choices:
            self._cancel_dupe_chooser()
        elif self._route_runway is not None:
            self._route_cancel_runway()
        elif self._act_confirm is not None:
            self._act_confirm_no()
        elif self._offer_open:
            self._close_offer()
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
        elif self._proc_picker is not None:
            self._proc_close_picker()
        elif self._page == "entry":
            self._entry_cancel()
        elif self._page == "dto":
            self._close_dto()
        elif self._page == "catalog":
            self._close_catalog()
        elif self._page == "proc":
            self._close_proc()
        elif self._page == "charts" and self._charts is not None and self._charts["plate"]:
            self._charts_list()
        elif self._page == "charts":
            self._close_charts()
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

    def _hit(self, x, y):
        """The callback of the topmost tap target under (x, y), or None.

        A list row is only hit inside the list viewport: a row scrolled
        partly under the column header keeps its full rect (the encoder ring
        needs it), but the part outside the viewport is not tappable."""
        view = self._list_view
        for n in range(len(self._tap_targets) - 1, -1, -1):
            tx, ty, tw, th, callback = self._tap_targets[n]
            if not (tx <= x <= tx + tw and ty <= y <= ty + th):
                continue
            if (view is not None and view["taps"][0] <= n < view["taps"][1]
                    and not self._in_list_view(y)):
                continue
            return callback
        return None

    def mousePressEvent(self, event):
        # Any tap dismisses the toast; a callback that raises a new one below
        # sets it again (and restarts the timer).
        x, y = event.position().x(), event.position().y()
        on_message = (bool(self._message) and self._message_rect is not None
                      and self._message_rect.contains(x, y))
        self._clear_toast()
        if on_message:
            # The FPL message strip covers the bottom list row: a tap on it
            # only dismisses it, never selects the row hidden under it.
            event.accept()
            return
        flinging = self._fling_timer.isActive()
        self._stop_fling()
        if self._hit(x, y) is None and self._plate_drag_start(x, y):
            event.accept()
            return
        if self._in_list_view(y):
            # Not a tap yet: it fires on release if the finger stayed put.
            # A press that stops a fling only stops it.
            self._press = {"x": x, "y": y, "scroll": self._list_scroll, "drag": False,
                           "target": None if flinging else self._hit(x, y),
                           "samples": [(self._now(), y)]}
            event.accept()
            return
        callback = self._hit(x, y)
        if callback is not None:
            callback()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._plate_drag is not None:
            self._plate_drag_move(event.position().x(), event.position().y())
            event.accept()
            return
        press = self._press
        if press is None:
            super().mouseMoveEvent(event)
            return
        x, y = event.position().x(), event.position().y()
        thr = self._drag_threshold_px()
        if not press["drag"] and math.hypot(x - press["x"], y - press["y"]) >= thr:
            # A drag now: release will not tap the row it started on. Anchor
            # at the threshold, not at this event, so the list neither jumps
            # by the threshold nor loses travel Qt merged into this one move
            # (xcb coalesces queued motion under load; the Beelink lost whole
            # drags that way).
            dy = y - press["y"]
            press.update(drag=True, y=press["y"] + max(-thr, min(dy, thr)))
        if press["drag"]:
            self._scroll_list_to(press["scroll"] - (y - press["y"]))
            self._last_pilot_scroll = self._now()
        now = self._now()
        press["samples"] = [s for s in press["samples"] if now - s[0] <= _FLING_SAMPLE_S]
        press["samples"].append((now, y))
        event.accept()

    def mouseReleaseEvent(self, event):
        if self._plate_drag is not None:
            self._plate_drag = None
            event.accept()
            return
        press, self._press = self._press, None
        if press is None:
            super().mouseReleaseEvent(event)
            return
        if press["drag"]:
            now = self._now()
            samples = [s for s in press["samples"] if now - s[0] <= _FLING_SAMPLE_S]
            samples.append((now, event.position().y()))
            dt = samples[-1][0] - samples[0][0]
            if dt > 0:
                # The list moves opposite to the finger's travel.
                self._start_fling(-(samples[-1][1] - samples[0][1]) / dt)
        elif press["target"] is not None:
            press["target"]()
        event.accept()

    def wheelEvent(self, event):
        if self._list_view is None:
            super().wheelEvent(event)
            return
        self._stop_fling()
        steps = event.angleDelta().y() / 120.0
        if self._scroll_list_to(self._list_scroll - steps * self._list_view["row_h"]):
            self._last_pilot_scroll = self._now()
        event.accept()

    # -- FPL list scrolling (PA15, AER-2087) ------------------------------------
    @staticmethod
    def _now():
        return time.monotonic()

    def _drag_threshold_px(self):
        try:
            mm = float(self.drag_threshold_mm)
        except (TypeError, ValueError):
            mm = DRAG_THRESHOLD_MM
        if not math.isfinite(mm) or mm <= 0:
            mm = DRAG_THRESHOLD_MM
        return max(6.0, mm * self._px_per_mm())

    def _in_list_view(self, y):
        view = self._list_view
        return view is not None and view["top"] <= y < view["bottom"]

    def _scroll_list_to(self, offset):
        """Scroll the list to *offset* px, clamped to its ends. Returns True
        if it moved."""
        view = self._list_view
        if view is None:
            return False
        new = max(0.0, min(float(offset), view["max"]))
        if new == self._list_scroll:
            return False
        self._list_scroll = new
        self.update()
        return True

    def _start_fling(self, velocity):
        """*velocity* is list travel in px/s, positive scrolling down."""
        ppm = self._px_per_mm()
        if abs(velocity) < _FLING_MIN_MM_S * ppm:
            return
        limit = _FLING_MAX_MM_S * ppm
        self._fling_v = max(-limit, min(velocity, limit))
        self._fling_last = self._now()
        self._fling_timer.start()

    def _stop_fling(self):
        self._fling_timer.stop()
        self._fling_v = 0.0

    def _fling_tick(self):
        now = self._now()
        dt, self._fling_last = now - (self._fling_last or now), now
        self._fling_step(dt)

    def _fling_step(self, dt):
        dt = max(0.0, min(dt, 0.1))
        moved = self._scroll_list_to(self._list_scroll + self._fling_v * dt)
        self._fling_v *= math.exp(-dt / _FLING_TAU_S)
        if moved:
            self._last_pilot_scroll = self._now()
        # An end stop or a spent fling ends it.
        if not moved or abs(self._fling_v) < _FLING_STOP_MM_S * self._px_per_mm():
            self._stop_fling()

    def _pilot_scrolled_recently(self):
        if self._press is not None or self._fling_timer.isActive():
            return True
        last = self._last_pilot_scroll
        return last is not None and self._now() - last < float(self.scroll_hold_s)

    def _follow_active_row(self, display, active_idx, row_h, view_h, max_scroll):
        """When the active leg changes, bring it into view with the FROM row
        above it -- unless the pilot has scrolled recently, in which case it
        is left for a later paint once the hold runs out."""
        if active_idx == self._followed_active or self._pilot_scrolled_recently():
            return
        self._followed_active = active_idx
        pos = next((n for n, row in enumerate(display)
                    if (row[0] == "wpt" and row[1] == active_idx)
                    or (row[0] == "fix" and row[2] == "to")), None)
        if pos is None:
            return
        row_top = pos * row_h
        context_top = row_top - row_h if pos > 0 and view_h >= 2 * row_h else row_top
        if context_top < self._list_scroll or row_top + row_h > self._list_scroll + view_h:
            self._list_scroll = max(0.0, min(context_top, max_scroll))

    def _enc_reveal_focus(self, ring):
        """Scroll a list row the knob just focused into the viewport, so the
        encoder reaches every row a finger can."""
        view = self._list_view
        focus = self._enc_focus
        if view is None or focus is None or self._enc_layer_start != 0:
            return
        n = focus - (1 if ring and ring[0][0] == "field" else 0)
        if not (view["taps"][0] <= n < view["taps"][1]):
            return
        rect = ring[focus][1]
        if rect.top() < view["top"]:
            delta = rect.top() - view["top"]
        elif rect.bottom() > view["bottom"]:
            delta = rect.bottom() - view["bottom"]
        else:
            return
        if self._scroll_list_to(self._list_scroll + delta):
            self._last_pilot_scroll = self._now()

    # -- painting -------------------------------------------------------------
    def _font_scale(self):
        """Multiplier applied to every font size: user x fit.

        user -- ``font_percent`` as a fraction (0.8 = 80%, 1.5 = 150%); unset,
        zero, negative or non-numeric means 1.0. It arrives already normalised:
        both screen paths (apply_preferences into the builder, apply_options'
        setattr) run ``screenbuilder_preferences.normalize_font_percent``, so a
        YAML 150 is 1.5 here. Do not re-apply the "> 1 is a percent" rule -- a
        second pass turned 150 into 0.015 (G55, pyEfis #355).
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
        missing. A long plan no longer shrinks rows below this; the list
        scrolls instead (PA15, see _list_metrics).
        """
        try:
            mm = float(self.row_height_mm)
        except (TypeError, ValueError):
            mm = 14.0
        if not math.isfinite(mm) or mm <= 0:
            mm = 14.0
        return max(24.0, mm * self._px_per_mm())

    def _fitted_row_h(self, avail_h, count, minimum):
        """Row height for a list that does not scroll: the physical row
        (``_row_h_cap``), shrunk only when *count* rows would not otherwise
        fit in *avail_h*, and floored at *minimum*.

        The Direct-To FPL and NRST tabs, the waypoint picker and the Catalog
        list used ``avail_h / count`` uncapped, so a one-row list drew a row
        the height of the whole pane, and a font sized off it that clipped at
        the pane edge (pyEfis #400). A short list now draws its rows the same
        height as a long one."""
        return max(minimum, min(avail_h / max(count, 1), self._row_h_cap()))

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
        self._list_view = None
        self._plate_view = None
        self._message_rect = None
        self._enc_layer_start = 0
        self._enc_field = None
        p = QPainter(self if device is None else device)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            w, h = self.width(), self.height()
            p.fillRect(0, 0, w, h, QColor("#000000"))
            page = self._page if self._editable() else "fpl"
            if page == "entry":
                self._paint_entry(p, w, h)
            elif page == "dto":
                self._paint_dto(p, w, h)
            elif page == "catalog":
                self._paint_catalog(p, w, h)
            elif page == "proc" and self._proc is not None:
                self._paint_proc(p, w, h)
            elif page == "charts" and self._charts is not None:
                self._paint_charts(p, w, h)
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
    def _editable(self):
        """The plan can be edited here: the gateway's keys are present and
        this is not a demo kiosk (DEMO4: the FPL page is read-only there,
        so an attendee's edit never disagrees with the demo's route)."""
        return self._bridge.available and not kiosk.locked()

    def _paint_fpl(self, p, w, h):
        bus = self._bridge.available
        interactive = self._editable()
        # 2.0 because this header draws TWO lines -- name/badge/remaining in
        # the top half, approach state or the gateway warning in the bottom --
        # so it is worth two rows. The footer is a soft-key touch row: 1.3
        # rows is ~18 mm, comfortably above a fingertip.
        header_h = int(self._chrome_h(h, 2.0, 0.26))
        footer_h = int(self._chrome_h(h, 1.3, 0.18))

        # Suspended at the MAP (G49): the alert takes a soft-key-high strip
        # above the footer, and the list lays out above it so the active leg
        # and the missed approach fixes stay visible.
        banner_h = footer_h if bus and self._suspended_at_map() else 0
        # A refused commit (G61): its strip sits above that one.
        refusal_h = footer_h if bus and self._plan_refused() else 0
        # A plan offered for acceptance (EFB4b): its strip sits above both.
        offer_h = footer_h if bus and self._offer is not None else 0

        self._paint_header(p, w, header_h, bus)
        self._paint_list(p, w, header_h, h - footer_h - banner_h - refusal_h - offer_h,
                         self._row_h_cap(), interactive)
        self._paint_footer(p, w, h - footer_h, footer_h, interactive)
        overlay_open = (self._row_menu_index is not None or self._seg_menu is not None
                        or self._menu_open or self._seg_fixes is not None
                        or self._wpt_info is not None or self._seg_fix_menu is not None
                        or self._airway_picker is not None
                        or self._act_confirm is not None
                        or self._hold_edit is not None
                        or (self._offer_open and self._offer is not None)
                        or self._modal is not None or self._route_runway is not None
                        or bool(self._entry_dupe_choices))
        if overlay_open:
            # The list under an overlay neither scrolls nor takes a press.
            self._list_view = None
        if banner_h:
            # Under an overlay, or read-only, it is drawn but not tappable.
            self._paint_map_susp_banner(p, w, h - footer_h, banner_h,
                                        interactive and not overlay_open)
        if refusal_h:
            self._paint_refusal_banner(p, w, h - footer_h - banner_h, refusal_h,
                                       interactive and not overlay_open)
        if offer_h:
            self._paint_offer_banner(p, w, h - footer_h - banner_h - refusal_h, offer_h,
                                     interactive and not overlay_open)

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
        elif self._act_confirm is not None:
            self._paint_act_confirm(p, w, h)
        elif self._hold_edit is not None:
            self._paint_hold_editor(p, w, h)
            if self._modal is not None:
                self._paint_modal(p, w, h)
        elif self._offer_open and self._offer is not None:
            self._paint_offer_sheet(p, w, h, interactive)
        elif self._modal is not None:
            # Route entry (RTE1b), opened from the menu.
            self._paint_modal(p, w, h)
        elif self._route_runway is not None:
            self._paint_route_runway(p, w, h)
        elif self._entry_dupe_choices:
            self._paint_dupe_chooser(p, w, h)

        if self._message:
            # Above the soft keys and any alert strip, never on the header
            # (AER-6156): drawn over the bottom of the list while it is up.
            self._paint_message_strip(p, w, h - footer_h - banner_h - refusal_h - offer_h,
                                      footer_h, self._message)

    def _paint_message_strip(self, p, w, bottom, strip_h, text):
        """An FPL-page message (STORED, ROUTE FULL, an OBS refusal) in a
        strip above the soft keys, where the refused-commit banner sits, so
        every answer to a press shows in one place (AER-6156; Bill chose the
        place). It was drawn at pane fractions over the header, which is
        physical, so on a short pane it printed over the LEG/DIRECT badge.
        Text too long for two lines at the banner's size steps down."""
        top = bottom - strip_h
        rect = QRectF(1, top, w - 2, strip_h - 1)
        self._message_rect = rect
        p.setBrush(QBrush(QColor("#302c00")))
        p.setPen(QPen(QColor("#ffff00"), 2))
        p.drawRect(rect)
        text_rect = QRectF(8, top, w - 16, strip_h)
        flags = (Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap)
        f = QFont(self.font_family)
        size = self._px(int(strip_h * 0.40), 9)
        while True:
            f.setPixelSize(size)
            p.setFont(f)
            fits = p.boundingRect(text_rect, int(flags.value), text).height() <= strip_h
            if fits or size <= 9:
                break
            size -= 1
        p.drawText(text_rect, flags, text)

    def _hold_summary(self):
        """``(text, colour)``: the hold as it will be flown, or why it
        cannot be."""
        e = self._hold_edit
        if e["message"]:
            return e["message"], "#ff4040"
        wp, error = self._hold_resolve()
        if wp is None:
            return error, "#ff4040"
        leg = f"{wp.dst:g} NM"
        if e["unit"] == "MIN":
            leg = f"{e['leg']:g} MIN = {leg}"
        return f"INBOUND {fp_hold.course_text(wp.crs)}  {wp.turn} TURNS  {leg}", "#ffffff"

    #: Published holds listed per chooser page (BGQ has ten in 2611).
    _HOLD_CHOOSER_ROWS = 8
    #: The STD TIME mark on a timed published hold's leg (Bill, AER-6328).
    _HOLD_STD_TIME_COLOR = "#ffaa00"

    def _paint_hold_editor(self, p, w, h):
        """The hold clearance, in the order ATC gives it: the side of the
        fix (a compass rose around it), the radial or inbound course, the
        turns and the leg. Every field is a tap; the line above Insert says
        what will be flown. When the fix has published holds, a PUBLISHED
        row under the title fills the fields from one (AER-6328)."""
        self._paint_overlay_backdrop(p, w, h)
        e = self._hold_edit
        box_w = w * 0.9
        box_x = (w - box_w) / 2
        rows = 10 if e["published"] else 9
        row_h = max(1.0, min(self._row_h_cap(), h * 0.84 / rows))
        box_h = row_h * rows
        box_y = (h - box_h) / 2
        p.setBrush(QBrush(QColor("#202020")))
        p.setPen(QPen(QColor("#ffffff")))
        p.drawRect(QRectF(box_x, box_y, box_w, box_h))
        f = QFont(self.font_family)
        f.setPixelSize(self._px(int(row_h * 0.4), 10))
        p.setFont(f)
        label_w = box_w * 0.3
        pad = 4.0

        def button(x, y, bw, text, on, selected=False, color="#00ffff"):
            rect = QRectF(x + pad, y + pad, bw - 2 * pad, row_h - 2 * pad)
            p.setBrush(QBrush(QColor("#00ffff" if selected else "#202020")))
            p.setPen(QPen(QColor("#00ffff" if selected else "#555555")))
            p.drawRect(rect)
            p.setPen(QPen(QColor("#000000" if selected else color)))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
            self._tap(rect.x(), rect.y(), rect.width(), rect.height(), on, "row")

        def label(y, text):
            p.setPen(QPen(QColor("#9a9a9a")))
            p.drawText(QRectF(box_x + 10, y, label_w - 10, row_h),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)

        y = box_y
        p.setPen(QPen(QColor("#ffffff")))
        p.drawText(QRectF(box_x, y, box_w, row_h), Qt.AlignmentFlag.AlignCenter,
                   f"PUBLISHED HOLDS AT {e['fix']}" if e["choosing"] else f"HOLD AT {e['fix']}")
        y += row_h

        if e["choosing"]:
            per = self._HOLD_CHOOSER_ROWS
            shown = e["published"][e["page"] * per:(e["page"] + 1) * per]
            for ph in shown:
                button(box_x, y, box_w, fp_hold.published_text(ph),
                       (lambda ph=ph: self._hold_apply_published(ph)), color="#ffffff")
                y += row_h
            y = box_y + row_h * (rows - 1)
            if self._hold_chooser_pages() > 1:
                button(box_x, y, box_w / 2, "More", self._hold_chooser_more, color="#ffffff")
                button(box_x + box_w / 2, y, box_w / 2, "Back", self._hold_close_chooser,
                       color="#ff8080")
            else:
                button(box_x, y, box_w, "Back", self._hold_close_chooser, color="#ff8080")
            return

        if e["published"]:
            if e["applied"] is not None:
                text = f"PUBLISHED: {fp_hold.published_text(e['applied'])}"
            elif len(e["published"]) > 1:
                text = f"PUBLISHED ({len(e['published'])})"
            else:
                text = "PUBLISHED"
            button(box_x, y, box_w, text, self._hold_published,
                   selected=e["applied"] is not None)
            y += row_h

        # The side of the fix: a 3 x 3 rose with the fix in the middle.
        label(y + row_h, "SIDE")
        cell_w = (box_w - label_w) / 3
        rose = (("NW", "N", "NE"), ("W", None, "E"), ("SW", "S", "SE"))
        for names in rose:
            for c, name in enumerate(names):
                x = box_x + label_w + c * cell_w
                if name is None:
                    p.setPen(QPen(QColor("#ffffff")))
                    p.drawText(QRectF(x, y, cell_w, row_h), Qt.AlignmentFlag.AlignCenter,
                               e["fix"])
                    continue
                button(x, y, cell_w, name, (lambda d=name: self._hold_set_direction(d)),
                       selected=name == e["direction"])
            y += row_h

        half = (box_w - label_w) / 2
        button(box_x, y, label_w, "RADIAL" if e["ref"] == "radial" else "INBOUND",
               self._hold_toggle_ref, color="#ffffff")
        button(box_x + label_w, y, box_w - label_w, fp_hold.course_text(e["course"]),
               self._hold_edit_course)
        y += row_h

        label(y, "TURNS")
        for n, turn in enumerate(fp_hold.TURNS):
            button(box_x + label_w + n * half, y, half, "LEFT" if turn == "L" else "RIGHT",
                   (lambda t=turn: self._hold_set_turn(t)), selected=turn == e["turn"])
        y += row_h

        if e["std_time"]:
            # NASR publishes no leg time: say the time is the standard one.
            label(y - row_h * 0.22, "LEG")
            p.setPen(QPen(QColor(self._HOLD_STD_TIME_COLOR)))
            p.drawText(QRectF(box_x + 10, y + row_h * 0.22, label_w - 10, row_h),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "STD TIME")
        else:
            label(y, "LEG")
        button(box_x + label_w, y, half, f"{e['leg']:g}", self._hold_edit_leg)
        button(box_x + label_w + half, y, half, e["unit"], self._hold_toggle_unit,
               color="#ffffff")
        y += row_h

        text, color = self._hold_summary()
        p.setPen(QPen(QColor(color)))
        p.drawText(QRectF(box_x + 6, y, box_w - 12, row_h), Qt.AlignmentFlag.AlignCenter, text)
        y += row_h

        button(box_x, y, box_w / 2, "Insert", self._hold_insert, color="#80ff80")
        button(box_x + box_w / 2, y, box_w / 2, "Cancel", self._close_hold_editor,
               color="#ff8080")

    def _paint_act_confirm(self, p, w, h):
        # A tap anywhere off the box is No: the soft keys under the dimmed
        # page must not leave a stale question (and its slot) pending.
        self._tap(0, 0, w, h, self._act_confirm_no)
        self._paint_overlay_backdrop(p, w, h)
        c = self._act_confirm
        text = f"FROM {c['from_id']} {c['dist_nm']:.0f} NM\nACTIVATE LEG?"
        self._paint_confirm(p, w, h, text, self._act_confirm_yes, self._act_confirm_no)

    def _paint_map_susp_banner(self, p, w, bottom, banner_h, tappable):
        """Alert above the soft keys while suspended at the MAP (G49): the
        SUSP badge alone is easy to miss at the moment the pilot has to
        decide, so say it and put the continue action under a finger."""
        top = bottom - banner_h
        p.setBrush(QBrush(QColor("#302000")))
        p.setPen(QPen(QColor("#ffaa00"), 2))
        p.drawRect(QRectF(1, top, w - 2, banner_h - 1))
        f = QFont(self.font_family)
        f.setPixelSize(self._px(int(banner_h * 0.34), 9))
        p.setFont(f)
        p.drawText(QRectF(8, top, w * 0.5 - 8, banner_h),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "SUSP AT MAP")
        btn = (w * 0.5, top + banner_h * 0.12, w * 0.5 - 6, banner_h * 0.76)
        p.setBrush(QBrush(QColor("#ffaa00")))
        p.drawRect(QRectF(*btn))
        p.setPen(QPen(QColor("#000000")))
        p.drawText(QRectF(*btn), Qt.AlignmentFlag.AlignCenter, self._suspend_label())
        if tappable:
            self._tap(*btn, self._menu_suspend_resume, "soft")

    def _refusal_text(self):
        reason = self._refusal[1] if self._refusal else ""
        if self._draft_open:
            return f"DRAFT - NOT LOADED: {reason}"
        return f"EDIT REFUSED: {reason}"

    def _paint_refusal_banner(self, p, w, bottom, banner_h, tappable):
        """The engine refused the last route commit (G61, pyEfis #380):
        say so with the engine's FPLMSG reason in plain words (G61a), in the
        alert colour, above the soft keys, with the way to the other view
        under a finger -- the refused edit as a draft, or back from the draft
        to the flown plan."""
        top = bottom - banner_h
        p.setBrush(QBrush(QColor("#300000")))
        p.setPen(QPen(QColor("#ff4040"), 2))
        p.drawRect(QRectF(1, top, w - 2, banner_h - 1))
        f = QFont(self.font_family)
        f.setPixelSize(self._px(int(banner_h * 0.40), 9))
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(8, top, w * 0.64 - 8, banner_h),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                   | Qt.TextFlag.TextWordWrap, self._refusal_text())
        btn = (w * 0.66, top + banner_h * 0.12, w * 0.34 - 6, banner_h * 0.76)
        p.setBrush(QBrush(QColor("#ff4040")))
        p.drawRect(QRectF(*btn))
        p.setPen(QPen(QColor("#000000")))
        if self._draft_open:
            label, action = "Flown plan", self._show_flown_plan
        else:
            label, action = "Edit draft", self._reopen_draft
        p.drawText(QRectF(*btn), Qt.AlignmentFlag.AlignCenter, label)
        if tappable:
            self._tap(*btn, action, "soft")

    def _paint_offer_banner(self, p, w, bottom, banner_h, tappable):
        """A plan offered for acceptance (EFB4b): name it above the soft keys,
        with Review under a finger. Not an alert: nothing has changed until
        the pilot accepts it."""
        offer = self._offer
        top = bottom - banner_h
        p.setBrush(QBrush(QColor("#002830")))
        p.setPen(QPen(QColor("#00ffff"), 2))
        p.drawRect(QRectF(1, top, w - 2, banner_h - 1))
        f = QFont(self.font_family)
        f.setPixelSize(self._px(int(banner_h * 0.34), 9))
        p.setFont(f)
        n = offer["plan"].count
        p.drawText(QRectF(8, top, w * 0.64 - 8, banner_h),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                   | Qt.TextFlag.TextWordWrap,
                   f"{offer['title']}\n{n} WAYPOINT{'S' if n != 1 else ''}")
        btn = (w * 0.66, top + banner_h * 0.12, w * 0.34 - 6, banner_h * 0.76)
        p.setBrush(QBrush(QColor("#00ffff")))
        p.drawRect(QRectF(*btn))
        p.setPen(QPen(QColor("#000000")))
        p.drawText(QRectF(*btn), Qt.AlignmentFlag.AlignCenter, "Review")
        if tappable:
            self._tap(*btn, self._open_offer, "soft")

    def _offer_scroll_by(self, delta):
        self._menu_scroll_by("offer", delta)

    def _paint_offer_sheet(self, p, w, h, interactive):
        """The offered plan, read-only, before the pilot takes it: every
        fix with its type, the leg distance into it and the total, the note
        on what did not cross, and Accept / Reject / Later. A tap off the
        sheet is Later: the soft keys under it must not take a press while
        it is up, and the plan stays offered."""
        offer = self._offer
        plan = offer["plan"]
        wps = plan.waypoints

        row_h = self._row_h_cap()
        box_x, box_w = w * 0.04, w * 0.92
        box_top = h * 0.04
        box_h = h * 0.92
        # Both under the backdrop, so the encoder ring holds only the
        # sheet's own buttons; a tap on a fix row does nothing.
        self._tap(0, 0, w, h, self._close_offer)
        self._tap(box_x, box_top, box_w, box_h, _no_op)
        self._paint_overlay_backdrop(p, w, h)
        title_h = row_h
        note_h = row_h * 0.6
        head_h = row_h * 0.5
        foot_h = row_h
        list_top = box_top + title_h + note_h + head_h
        list_h = box_h - title_h - note_h - head_h - foot_h
        n = len(wps)
        fit = max(1, int(list_h // row_h))
        scrollable = n > fit
        visible = max(1, fit - 1) if scrollable else n
        stored_n, offset = self._menu_scroll.get("offer", (n, 0))
        offset = max(0, min(offset if stored_n == n else 0, n - visible))
        self._menu_scroll["offer"] = (n, offset)

        p.setPen(QPen(QColor("#00ffff")))
        p.setBrush(QBrush(QColor("#202020")))
        p.drawRect(QRectF(box_x, box_top, box_w, box_h))

        f = QFont(self.font_family)
        f.setPixelSize(self._px(int(row_h * 0.5), 9))
        bold = QFont(f)
        bold.setBold(True)
        small = QFont(f)
        small.setPixelSize(self._px(int(row_h * 0.36), 8))
        p.setFont(bold)
        p.setPen(QPen(QColor("#00ffff")))
        p.drawText(QRectF(box_x + 12, box_top, box_w - 24, title_h),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, offer["title"])
        p.setFont(small)
        p.setPen(QPen(QColor("#ffaa00")))
        p.drawText(QRectF(box_x + 12, box_top + title_h, box_w - 24, note_h),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, offer["note"])

        col_x = [box_x + box_w * f_ for f_ in (0.58, 0.76)]
        col_w = box_w * 0.18
        hy = box_top + title_h + note_h
        ir, icx, lx = self._row_icon_geometry(row_h)
        p.setPen(QPen(QColor("#9a9a9a")))
        p.drawText(QRectF(box_x + lx, hy, box_w * 0.3, head_h),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "FIX")
        for x, label in zip(col_x, ("DIS", "CUM")):
            p.drawText(QRectF(x, hy, col_w, head_h),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, label)
        p.setPen(QPen(QColor("#333333")))
        p.drawLine(QPointF(box_x, hy + head_h - 1), QPointF(box_x + box_w, hy + head_h - 1))

        y = list_top
        for i in range(offset, offset + visible):
            wp = wps[i]
            dist = plan.leg(i - 1)[1] if i > 0 else None
            p.setFont(f)
            p.setPen(QPen(QColor("#ffffff")))
            self._draw_type_icon(p, box_x + icx, y + row_h / 2, ir * 0.85, wp.type)
            # An ident longer than a route slot holds loads cut short; the
            # whole one is shown beside it.
            label = f"{wp.id} ({wp.name})" if wp.name else wp.id
            p.drawText(QRectF(box_x + lx, y, box_w * 0.58 - lx, row_h),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)
            texts = ("", "") if dist is None else (f"{dist:.0f}", f"{plan.cumulative(i):.0f}")
            for x, text in zip(col_x, texts):
                p.drawText(QRectF(x, y, col_w, row_h),
                           Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, text)
            y += row_h

        if scrollable:
            half = box_w / 2
            can_up, can_down = offset > 0, offset + visible < n
            for n_, (label, ok, d) in enumerate((("\u25b2", can_up, -visible),
                                                 ("\u25bc", can_down, visible))):
                rx = box_x + n_ * half
                p.setPen(QPen(QColor("#00ffff" if ok else "#505050")))
                p.drawText(QRectF(rx, y, half, row_h), Qt.AlignmentFlag.AlignCenter, label)
                if ok:
                    self._tap(rx, y, half, row_h, (lambda dd=d: self._offer_scroll_by(dd)))

        fy = box_top + box_h - foot_h
        p.setPen(QPen(QColor("#333333")))
        p.drawLine(QPointF(box_x, fy), QPointF(box_x + box_w, fy))
        p.setFont(f)
        third = box_w / 3
        for k, (label, color, action) in enumerate((
                ("Accept", "#80ff80", self._offer_accept),
                ("Reject", "#ff8080", self._offer_reject),
                ("Later", "#ffffff", self._close_offer))):
            rx = box_x + k * third
            p.setPen(QPen(QColor(color)))
            p.drawText(QRectF(rx, fy, third, foot_h), Qt.AlignmentFlag.AlignCenter, label)
            # Read-only (a demo kiosk): the sheet can be closed, not answered.
            if interactive or k == 2:
                self._tap(rx, fy, third, foot_h, action)

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

        # The procedure's type and cycle, right-aligned; left of LOI when the
        # integrity alarm is up, so neither covers the other.
        right = w - 4
        if self._engine_value("FPLINTEG", True) is False:
            p.setPen(QPen(QColor("#ff0000")))
            p.drawText(QRectF(w * 0.55, header_h * 0.52, w * 0.42, header_h * 0.46),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "LOI")
            right -= w * 0.03 + p.fontMetrics().horizontalAdvance("LOI  ")
        proc = self._procedure_text()
        if proc:
            p.setPen(QPen(QColor(proc[1])))
            p.drawText(QRectF(w * 0.30, header_h * 0.52, right - w * 0.30, header_h * 0.46),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, proc[0])

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

    def _list_metrics(self, top, bottom, max_row_h):
        """``(header_h, row_h)``. The header strip is half a physical row.
        Rows keep the physical height however many there are (PA15): a long
        route scrolls instead of shrinking every row below a fingertip. Only
        a pane too short for one whole row gets a shorter one."""
        hh = max(14.0, max_row_h * 0.5)
        row_h = max(14, min(bottom - top - hh, max_row_h))
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
        hh, row_h = self._list_metrics(top, bottom, max_row_h)
        self._paint_column_headers(p, w, top, hh, row_h, cols)

        view_top = top + hh
        view_h = max(0.0, bottom - view_top)
        content_h = len(display) * row_h
        max_scroll = max(0.0, content_h - view_h)
        self._follow_active_row(display, active_idx, row_h, view_h, max_scroll)
        self._list_scroll = max(0.0, min(self._list_scroll, max_scroll))

        f = QFont(self.font_family)
        f.setPixelSize(self._px(int(row_h * 0.5), 9))
        # Every row is painted and registers its tap target, offscreen ones
        # too, so the encoder ring can walk to them; the clip keeps them off
        # the header and footer, and _hit keeps them from being tapped there.
        taps_start = len(self._tap_targets)
        p.save()
        p.setClipRect(QRectF(0, view_top, w, view_h))
        y = view_top - self._list_scroll
        nest_top = None
        rh = row_h
        for row in display:
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
        p.restore()
        self._list_view = {"top": view_top, "bottom": view_top + view_h, "max": max_scroll,
                           "row_h": row_h, "taps": (taps_start, len(self._tap_targets))}
        if max_scroll > 0:
            self._paint_scroll_cue(p, w, view_top, view_h, content_h, row_h)

    def _paint_scroll_cue(self, p, w, view_top, view_h, content_h, row_h):
        """A thin bar down the right edge, only when the list overflows: the
        thumb's size is the share of the route on screen, its place where
        that share sits. Right of the columns (which end at 0.97 w)."""
        bar_w = max(4.0, 1.2 * self._px_per_mm())
        x = w - bar_w - 1
        thumb_h = max(row_h * 0.5, view_h * view_h / content_h)
        max_scroll = content_h - view_h
        thumb_y = view_top + (view_h - thumb_h) * (self._list_scroll / max_scroll)
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor("#303030")))
        p.drawRoundedRect(QRectF(x, view_top, bar_w, view_h), bar_w / 2, bar_w / 2)
        p.setBrush(QBrush(QColor("#9a9a9a")))
        p.drawRoundedRect(QRectF(x, thumb_y, bar_w, thumb_h), bar_w / 2, bar_w / 2)
        p.restore()

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
        if wp.pt in fp_hold.HOLD_PTS:
            label = f"{label} HOLD"
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

    def _segment_detail(self, k):
        """A segment row's second line: an airway's fix count and MEA; a
        procedure's kind, leg count and AIRAC cycle (PA7)."""
        seg = self._plan.segments[k]
        if seg.kind == "airway":
            detail = f"{len(seg.legs)} fixes"
            mea = self._segment_mea(k)
            if mea is not None:
                detail += f"   MEA {mea}"
            return detail
        kind = "MISSED APPROACH" if seg.kind == "missed" else seg.kind.upper()
        return f"{kind}   {self._segment_span_text(k)}"

    def _paint_segment_row(self, p, w, y, rh, k, active_idx, cols, interactive):
        """One airway or procedure: ident and entry -> exit on the first
        line, the detail beneath it in a smaller face. Same geometry whether
        or not the segment is active, so opening it never shifts the row."""
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
        # A procedure's name fills line 1 (ILS07.VECTORS); its ends go on
        # line 2, which the columns leave free across the row (PA7).
        procedure = seg.kind != "airway"
        if not procedure:
            p.drawText(QRectF(lx + ident_w, y, w * 0.42 - lx - ident_w, top_h),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
                       self._segment_span_text(k))

        detail = self._segment_detail(k)
        small = QFont(base)
        small.setPixelSize(max(9, int(base.pixelSize() * 0.86)))
        p.setFont(small)
        dim = QColor(color)
        dim.setAlpha(190)
        p.setPen(QPen(dim))
        p.drawText(QRectF(lx, y + top_h, (w * 0.97 if procedure else w * 0.42) - lx, rh - top_h),
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

    @staticmethod
    def _fix_label(wp):
        """A fix inside a segment as its rows, sheet and menu title name it:
        the leg label, the role, and HOLD on a hold the pilot built (HOLDFIX1),
        so it never reads as the same fix listed twice."""
        label = fp_proc.leg_label(wp)
        if ROLE_ABBREV.get(wp.role):
            label = f"{label} {ROLE_ABBREV[wp.role]}"
        if fp_hold.is_pilot_hold(wp):
            label = f"{label} HOLD"
        return label

    def _paint_nested_fix_row(self, p, w, y, rh, i, role, active_idx, cols, interactive):
        wp = self._plan.waypoints[i]
        color = {"from": self.past_color, "to": self.active_color}.get(role, self.future_color)
        p.setPen(QPen(QColor(color)))
        ir, icx, lx = self._row_icon_geometry(rh)
        dx = self._nest_indent(rh)
        self._draw_type_icon(p, icx + dx, y + rh / 2, ir * 0.85, wp.type)
        label = self._fix_label(wp)
        if role == "from":
            label = f"{label}  (from)"
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
        labels = ("ADD WPT", "DIRECT TO", "PROC", "CATALOG", "MENU")
        callbacks = (self._footer_add, self._footer_direct_to, self._footer_proc,
                     self._footer_catalog, self._footer_menu)
        if self.plates_path:
            # PA12: one tap to the loaded approach's plate. Only a screen
            # that names a plates pack grows the key.
            labels = labels[:4] + ("CHARTS",) + labels[4:]
            callbacks = callbacks[:4] + (self._footer_charts,) + callbacks[4:]
        seg = w / len(labels)
        f = QFont(self.font_family)
        f.setPixelSize(self._px(int(footer_h * 0.34), 9))
        p.setFont(f)
        # Read-only in a demo kiosk (DEMO4): the soft keys are greyed out.
        p.setPen(QPen(QColor("#555555" if kiosk.locked() else "#ffffff")))
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
        i = self._row_menu_index
        for label, attr in _ROW_MENU_ITEMS:
            if attr is not None and not self._menu_item_offered(attr, i):
                continue
            items.append((label, self._open_role_menu if attr is None else getattr(self, attr)))
        self._paint_menu_list(p, w, h, items, self._close_row_menu, scroll_key="row_menu")

    def _segment_span_text(self, k):
        seg = self._plan.segments[k]
        return f"{fp_proc.leg_label(seg.legs[0])} → {fp_proc.leg_label(seg.legs[-1])}"

    def _segment_title(self, k):
        return f"{self._plan.segments[k].ident}  {self._segment_span_text(k)}"

    def _paint_seg_menu(self, p, w, h):
        self._paint_overlay_backdrop(p, w, h)
        k = self._seg_menu
        first, _ = self._plan.segment_span(k)
        seg_kind = self._plan.segments[k].kind
        page_kind = _SEGMENT_PAGE_KIND.get(seg_kind)
        items = []
        for label, attr in (_SEG_MENU_ITEMS if page_kind is None else _PROC_SEG_MENU_ITEMS):
            if attr == "_seg_menu_load_airway":
                if not self._seg_load_airway_offered(k):
                    continue
                label = f"{label} at {self._plan.segments[k].exit}"
            elif attr == "_seg_menu_activate":
                label = f"Activate to {fp_proc.leg_label(self._plan.waypoints[first])}"
            elif page_kind is not None and attr in ("_seg_menu_select_procedure",
                                                    "_seg_menu_remove_procedure"):
                label = f"{label} {_PROC_KIND_LABELS[page_kind]}"
            items.append((label, getattr(self, attr)))
        self._paint_menu_list(p, w, h, items, self._close_seg_menu, scroll_key="seg_menu",
                              title=self._segment_title(k))

    def _paint_seg_fix_menu(self, p, w, h):
        self._paint_overlay_backdrop(p, w, h)
        i = self._seg_fix_menu
        wp = self._plan.waypoints[i]
        # A leg that ends without a fix (a climb, a vector) has nowhere to go
        # direct to and nothing to look up.
        items = [(label, getattr(self, attr)) for label, attr in _SEG_FIX_MENU_ITEMS
                 if (wp.id or attr == "_seg_fix_activate_leg")
                 and self._menu_item_offered(attr, i)]
        self._paint_menu_list(p, w, h, items, self._close_seg_fix_menu,
                              scroll_key="seg_fix_menu", title=self._fix_label(wp))

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
        if seg.cycle:
            cycle_text, cycle_color = self._cycle_text(seg.cycle)
            p.setPen(QPen(QColor(cycle_color)))
            p.drawText(QRectF(box_x + 12, box_top, box_w - 24, title_h),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       cycle_text)
        p.setPen(QPen(QColor("#9a9a9a")))

        # FIX | CRS | DIS | MEA, columns right-aligned like the route list. A
        # procedure's last column is the leg's altitude constraint as coded.
        procedure = seg.kind != "airway"
        col_x = [box_x + box_w * f_ for f_ in (0.40, 0.58, 0.76)]
        col_w = box_w * 0.18
        hy = box_top + title_h
        ir, icx, lx = self._row_icon_geometry(row_h)
        p.drawText(QRectF(box_x + lx, hy, box_w * 0.3, head_h),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "FIX")
        for x, label in zip(col_x, ("CRS", "DIS", "ALT" if procedure else "MEA")):
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
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       self._fix_label(wp))
            leg = self._leg_in(i) if (i > first or procedure) else None
            texts = ("", "", "") if leg is None else (
                f"{leg[0]:03.0f}°", f"{leg[1]:.0f}", wp.alt if procedure else self._mea_text(wp))
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

    def _paint_confirm(self, p, w, h, text, on_yes, on_no=None):
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
        self._tap(*no_rect, on_no or self._close_menu, "no")

    def _paint_menu(self, p, w, h):
        self._paint_overlay_backdrop(p, w, h)
        if self._confirm:
            text = "Clear flight plan?" if self._confirm == "clear" else "Delete flight plan?"
            on_yes = self._menu_clear_confirm if self._confirm == "clear" else self._menu_delete_confirm
            self._paint_confirm(p, w, h, text, on_yes)
            return
        susp_label = self._suspend_label()
        items = [
            ("Route", self._menu_route),
            ("Invert", self._menu_invert),
            ("Store", self._menu_store),
            ("Clear", self._menu_clear_request),
            ("Hold at PPOS", self._menu_hold_ppos),
            (susp_label, self._menu_suspend_resume),
            (self._obs_label(), self._menu_obs),
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
        lines.append(f"{self._brg_text(brg)}  {dist:.1f} NM")
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
        if wp.type == "user" and not kiosk.locked():
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
        row_h = self._fitted_row_h(h, len(rows), 18)
        f.setPixelSize(self._px(int(row_h * 0.5), 9))
        p.setFont(f)
        y = top
        for i, wp in enumerate(rows):
            rh = min(row_h, top + h - y)
            if rh <= 0:
                break
            selected = self._dto_target is not None and self._dto_target[:2] == ("fpl", i)
            p.setPen(QPen(QColor("#00ffff" if selected else "#ffffff")))
            label = fp_proc.leg_label(wp)
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
        row_h = self._fitted_row_h(h, len(results), 18)
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
            mid = f"{self._brg_text(brg)} {dist:.0f}NM"
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

    # -- PROC page (PA7) --------------------------------------------------------
    def _paint_proc(self, p, w, h):
        """The guide's procedure setup page (pp. 3-64, 3-69, 3-71, 3-73):
        a Departure/Arrival/Approach tab, one key per field showing the
        choice or underscores, a preview of the legs the selection loads,
        and Load / Remove. Every control is a tap target, so the encoder
        ring reaches each one too."""
        st = self._proc
        header_h = int(self._chrome_h(h, 1.3, 0.18))
        tabs_h = int(self._chrome_h(h, 1.0, 0.12))
        footer_h = int(self._chrome_h(h, 1.3, 0.18))
        row_h = self._row_h_cap()

        self._paint_proc_header(p, w, header_h)
        y = header_h
        self._paint_proc_tabs(p, w, y, tabs_h)
        y += tabs_h
        bottom = h - footer_h
        f = QFont(self.font_family)
        f.setPixelSize(self._px(int(row_h * 0.5), 9))
        for field in self._proc_fields():
            rh = min(row_h, bottom - y)
            if rh <= 0:
                break
            self._paint_proc_field(p, w, y, rh, field, f)
            y += rh
        self._paint_proc_status(p, w, y, bottom, row_h)
        self._paint_proc_footer(p, w, bottom, footer_h)

        if self._proc_picker is not None:
            self._paint_overlay_backdrop(p, w, h)
            field = self._proc_picker
            items = [(label, (lambda v=value, fld=field: self._proc_pick(fld, v)))
                     for label, value in self._proc_choices(field)]
            name = (_PROC_KIND_LABELS[st["kind"]] if field == "proc"
                    else _PROC_FIELD_LABELS[field])
            self._paint_menu_list(p, w, h, items, self._proc_close_picker,
                                  scroll_key=f"proc_{field}", title=f"Select {name}")
        if self._message:
            self._paint_toast(p, w, h, self._message)

    def _paint_proc_header(self, p, w, header_h):
        f = QFont(self.font_family)
        f.setPixelSize(self._px(int(header_h * 0.4), 10))
        p.setFont(f)
        p.setPen(QPen(QColor("#ffffff")))
        p.drawText(QRectF(0, 0, w, header_h), Qt.AlignmentFlag.AlignCenter, "PROCEDURES")
        cancel_rect = (w - header_h, 0, header_h, header_h)
        p.setPen(QPen(QColor("#ff8080")))
        p.drawText(QRectF(*cancel_rect), Qt.AlignmentFlag.AlignCenter, "X")
        self._tap(*cancel_rect, self._close_proc)

    def _paint_proc_tabs(self, p, w, top, tabs_h):
        seg = w / len(PROC_TABS)
        f = QFont(self.font_family)
        f.setPixelSize(self._px(int(tabs_h * 0.45), 9))
        p.setFont(f)
        for i, (label, kind) in enumerate(PROC_TABS):
            x = i * seg
            color = "#00ffff" if kind == self._proc["kind"] else "#808080"
            p.setPen(QPen(QColor(color)))
            p.drawText(QRectF(x, top, seg, tabs_h), Qt.AlignmentFlag.AlignCenter, label)
            self._tap(x, top, seg, tabs_h, (lambda k=kind: self._proc_select_kind(k)))
        p.setPen(QPen(QColor("#333333")))
        p.drawLine(QPointF(0, top + tabs_h - 1), QPointF(w, top + tabs_h - 1))

    def _paint_proc_field(self, p, w, y, rh, field, font):
        label = (_PROC_KIND_LABELS[self._proc["kind"]] if field == "proc"
                 else _PROC_FIELD_LABELS[field])
        value = self._proc_field_value(field)
        p.setFont(font)
        p.setPen(QPen(QColor("#222222")))
        p.drawRect(QRectF(2, y + 2, w - 4, rh - 4))
        p.setPen(QPen(QColor("#9a9a9a")))
        p.drawText(QRectF(10, y, w * 0.4, rh),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)
        # Underscores until chosen, as the guide's keys show (p. 3-64).
        p.setPen(QPen(QColor("#00ffff" if value else "#808080")))
        p.drawText(QRectF(w * 0.4, y, w * 0.6 - 12, rh),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   value or "_____")
        self._tap(0, y, w, rh, (lambda fld=field: self._proc_open_field(fld)), "row")

    def _paint_proc_status(self, p, w, top, bottom, row_h):
        """Below the keys: what is loaded, a refusal or the page's message,
        then the legs the selection would load."""
        st = self._proc
        f = QFont(self.font_family)
        f.setPixelSize(self._px(int(row_h * 0.42), 9))
        p.setFont(f)
        line_h = max(14.0, row_h * 0.62)
        y = top + 4
        lines = []
        loaded = self._proc_loaded_ident(st["kind"])
        lines.append((f"LOADED: {loaded}" if loaded else "NONE LOADED", "#9a9a9a"))
        segments, error = self._proc_preview()
        if self._plan_refused():
            lines.append((self._refusal_text(), "#ff4040"))
        if st["message"] or error:
            lines.append((st["message"] or error, "#ff4040"))
        for text, color in lines:
            if y + line_h > bottom:
                return
            p.setPen(QPen(QColor(color)))
            p.drawText(QRectF(10, y, w - 20, line_h),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
            y += line_h
        if not segments:
            return
        title = segments[0].ident
        if st["proc"].runway:
            title += f"   RWY {st['proc'].runway}"
        legs = [(seg.kind, wp) for seg in segments for wp in seg.legs]
        if y + line_h > bottom:
            return
        p.setPen(QPen(QColor("#ffffff")))
        p.drawText(QRectF(10, y, w - 20, line_h),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title)
        if segments[0].cycle:
            # Right-aligned so an expired cycle keeps its own colour.
            cycle_text, cycle_color = self._cycle_text(segments[0].cycle)
            p.setPen(QPen(QColor(cycle_color)))
            p.drawText(QRectF(10, y, w - 20, line_h),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, cycle_text)
        y += line_h
        fit = max(0, int((bottom - y) // line_h))
        shown = legs if len(legs) <= fit else legs[:max(0, fit - 1)]
        for seg_kind, wp in shown:
            role = ROLE_ABBREV.get(wp.role, "")
            label = fp_proc.leg_label(wp) + (f" {role}" if role else "")
            p.setPen(QPen(QColor("#00ffff" if seg_kind == "missed" else "#ffffff")))
            p.drawText(QRectF(24, y, w * 0.5, line_h),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)
            p.drawText(QRectF(w * 0.5, y, w * 0.16, line_h),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, wp.pt)
            p.drawText(QRectF(w * 0.66, y, w * 0.32, line_h),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, wp.alt)
            y += line_h
        if len(shown) < len(legs):
            p.setPen(QPen(QColor("#9a9a9a")))
            p.drawText(QRectF(24, y, w - 34, line_h),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       f"+ {len(legs) - len(shown)} more")

    def _paint_proc_footer(self, p, w, top, footer_h):
        kind = _PROC_KIND_LABELS[self._proc["kind"]]
        f = QFont(self.font_family)
        f.setPixelSize(self._px(int(footer_h * 0.34), 9))
        p.setFont(f)
        p.setPen(QPen(QColor("#333333")))
        p.drawLine(QPointF(0, top), QPointF(w, top))
        half = w / 2
        load_rect = (0, top, half, footer_h)
        p.setPen(QPen(QColor("#00ff00" if self._proc_ready() else "#4a7a4a")))
        p.drawText(QRectF(*load_rect), Qt.AlignmentFlag.AlignCenter, f"LOAD {kind.upper()}")
        self._tap(*load_rect, self._proc_load, "activate")
        remove_rect = (half, top, half, footer_h)
        loaded = bool(self._proc_loaded_ident(self._proc["kind"]))
        p.setPen(QPen(QColor("#ff8080" if loaded else "#505050")))
        p.drawText(QRectF(*remove_rect), Qt.AlignmentFlag.AlignCenter,
                   f"REMOVE {kind.upper()}")
        if loaded:
            self._tap(*remove_rect, self._proc_remove, "soft")

    # -- Charts page (PA12) -------------------------------------------------------
    def _paint_charts(self, p, w, h):
        """The airport's chart list, or one chart drawn to fit the pane. No
        ownship is drawn on any chart (brief guardrail 5)."""
        st = self._charts
        plate = st["plate"]
        header_h = int(self._chrome_h(h, 1.3, 0.18))
        info_h = int(self._chrome_h(h, 0.7, 0.08))
        footer_h = int(self._chrome_h(h, 1.3, 0.18))
        title = plate.chart_name if plate else f"CHARTS  {st['airport']}"
        self._paint_charts_header(p, w, header_h, title)
        top, bottom = header_h + info_h, h - footer_h
        plates = [] if plate else self._ensure_plate_index().plates_at(st["airport"])
        self._paint_charts_info(p, w, header_h, info_h, plate or (plates[0] if plates else None))
        if plate:
            self._paint_plate(p, w, top, bottom, plate)
            self._paint_charts_footer(p, w, bottom, footer_h, (
                ("LIST", self._charts_list, True),
                ("ZOOM -", lambda: self._charts_zoom(-1), st["zoom"] > 0),
                ("FIT", self._charts_fit, st["zoom"] > 0),
                ("ZOOM +", lambda: self._charts_zoom(1), st["zoom"] < len(CHART_ZOOMS) - 1)))
        else:
            more_up, more_down, page_rows = self._paint_charts_list(p, w, top, bottom, plates)
            self._paint_charts_footer(p, w, bottom, footer_h, (
                ("AIRPORT", self._charts_change_airport, True),
                ("▲", lambda: self._charts_scroll(-page_rows), more_up),
                ("▼", lambda: self._charts_scroll(page_rows), more_down)))
        if self._message:
            self._paint_toast(p, w, h, self._message)

    def _paint_charts_header(self, p, w, header_h, title):
        f = QFont(self.font_family)
        f.setPixelSize(self._px(int(header_h * 0.4), 10))
        p.setFont(f)
        p.setPen(QPen(QColor("#ffffff")))
        p.drawText(QRectF(header_h * 0.2, 0, w - header_h * 1.4, header_h),
                   Qt.AlignmentFlag.AlignCenter, title)
        cancel_rect = (w - header_h, 0, header_h, header_h)
        p.setPen(QPen(QColor("#ff8080")))
        p.drawText(QRectF(*cancel_rect), Qt.AlignmentFlag.AlignCenter, "X")
        self._tap(*cancel_rect, self._close_charts)

    def _paint_charts_info(self, p, w, top, info_h, plate):
        """The page's message, or the chart's airport and amendment, and on
        the right the cycle the chart is from -- amber once it has expired
        (PA9's annunciation: expired data is shown, never refused)."""
        st = self._charts
        f = QFont(self.font_family)
        f.setPixelSize(self._px(int(info_h * 0.6), 9))
        p.setFont(f)
        rect = QRectF(10, top, w - 20, info_h)
        left, color = "", "#9a9a9a"
        if st["message"]:
            left, color = st["message"], "#ff4040"
        elif plate is not None and st["plate"] is not None:
            amdt = " ".join(v for v in (plate.amdt_num, plate.amdt_date) if v)
            left = plate.icao_ident + (f"  AMDT {amdt}" if amdt else "")
        p.setPen(QPen(QColor(color)))
        p.drawText(rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, left)
        if plate is not None and plate.cycle:
            text, cycle_color = self._cycle_text(plate.cycle)
            p.setPen(QPen(QColor(cycle_color)))
            p.drawText(rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, text)

    def _paint_charts_list(self, p, w, top, bottom, plates):
        """One row per chart, a page at a time; returns ``(more above, more
        below, rows per page)``."""
        st = self._charts
        f = QFont(self.font_family)
        if not plates:
            f.setPixelSize(self._px(int((bottom - top) * 0.06), 10))
            p.setFont(f)
            p.setPen(QPen(QColor("#808080")))
            text = (f"NO CHARTS FOR {st['airport']}" if self._ensure_plate_index().ready
                    else "NO CHARTS DATABASE")
            p.drawText(QRectF(0, top, w, bottom - top), Qt.AlignmentFlag.AlignCenter, text)
            return False, False, 1
        row_h = self._row_h_cap()
        rows = max(1, int((bottom - top) // row_h))
        st["first"] = max(0, min(st["first"], len(plates) - rows))
        f.setPixelSize(self._px(int(row_h * 0.42), 9))
        p.setFont(f)
        y = top
        for plate in plates[st["first"]:st["first"] + rows]:
            p.setPen(QPen(QColor("#222222")))
            p.drawRect(QRectF(2, y + 2, w - 4, row_h - 4))
            p.setPen(QPen(QColor("#ffffff")))
            p.drawText(QRectF(10, y, w * 0.72 - 10, row_h),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       plate.chart_name)
            p.setPen(QPen(QColor("#9a9a9a")))
            p.drawText(QRectF(w * 0.72, y, w * 0.28 - 10, row_h),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       _CHART_LABELS.get(plate.chart_code, plate.chart_code))
            self._tap(0, y, w, row_h, (lambda pl=plate: self._charts_show(pl)), "row")
            y += row_h
        return st["first"] > 0, st["first"] + rows < len(plates), rows

    def _paint_plate(self, p, w, top, bottom, plate):
        """The chart's page, fitted to the pane and then zoomed, with the
        point ``_charts["centre"]`` at the middle of the view as far as the
        page's edges allow."""
        st = self._charts
        view = QRectF(0, top, w, bottom - top)
        renderer = self._plate_renderer
        index = self._ensure_plate_index()

        def fetch():
            return index.pdf_bytes(plate.pdf_name)

        size = renderer.page_size(plate.pdf_name, fetch) if renderer.available else None
        image = None
        if size is not None:
            pw, ph = size
            fit = min(view.width() / pw, view.height() / ph)
            zoom = CHART_ZOOMS[st["zoom"]]
            iw, ih = round(pw * fit * zoom), round(ph * fit * zoom)
            image = renderer.render(plate.pdf_name, fetch, iw, ih)
        if image is None:
            f = QFont(self.font_family)
            f.setPixelSize(self._px(int(view.height() * 0.035), 9))
            p.setFont(f)
            p.setPen(QPen(QColor("#ffb000")))
            text = renderer.unavailable_reason or "CHART CANNOT BE DRAWN"
            p.drawText(view, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, text)
            return

        def place(length, span, start, centre):
            if length <= span:
                return start + (span - length) / 2
            return min(start, max(start + span - length, start + span / 2 - centre * length))

        x = place(iw, view.width(), view.left(), st["centre"][0])
        y = place(ih, view.height(), view.top(), st["centre"][1])
        st["centre"] = ((view.center().x() - x) / iw, (view.center().y() - y) / ih)
        p.save()
        p.setClipRect(view)
        p.drawImage(QPointF(x, y), image)
        p.restore()
        self._plate_view = {"rect": view, "w": iw, "h": ih}

    def _paint_charts_footer(self, p, w, top, footer_h, keys):
        """Soft keys ``(label, callback, enabled)``; a disabled key is grey
        and takes no tap."""
        p.setPen(QPen(QColor("#333333")))
        p.drawLine(QPointF(0, top), QPointF(w, top))
        seg = w / len(keys)
        f = QFont(self.font_family)
        f.setPixelSize(self._px(int(footer_h * 0.34), 9))
        p.setFont(f)
        for i, (label, callback, enabled) in enumerate(keys):
            x = i * seg
            p.setPen(QPen(QColor("#ffffff" if enabled else "#505050")))
            p.drawText(QRectF(x, top, seg, footer_h), Qt.AlignmentFlag.AlignCenter, label)
            if enabled:
                self._tap(x, top, seg, footer_h, callback, "soft")

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
        row_h = self._fitted_row_h(bottom - top, len(entries), 18)
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
        self._paint_confirm(p, w, h, text, self._catalog_confirm_yes, self._catalog_confirm_no)

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
        value_rect = QRectF(box_x + 8, box_y + box_h * 0.1, box_w - 16, box_h * 0.12)
        if m.get("rows") is not None:
            # A route runs long: wrapped, in a font small enough to fit.
            fv = QFont(f)
            while fv.pixelSize() > 8 and QFontMetrics(fv).boundingRect(
                    value_rect.toRect(), Qt.TextFlag.TextWordWrap,
                    m["value"] or " ").height() > value_rect.height():
                fv.setPixelSize(fv.pixelSize() - 1)
            p.setFont(fv)
        p.setPen(QPen(QColor("#00ffff")))
        p.drawText(value_rect, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                   m["value"] or " ")
        p.setFont(f)
        if m.get("message"):
            p.setPen(QPen(QColor("#ff0000")))
            p.drawText(QRectF(box_x + 8, box_y + box_h * 0.22, box_w - 16, box_h * 0.06),
                       Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, m["message"])

        cancel_size = box_h * 0.08
        cancel_rect = (box_x, box_y + 2, cancel_size, cancel_size)
        p.setPen(QPen(QColor("#ff8080")))
        p.drawText(QRectF(*cancel_rect), Qt.AlignmentFlag.AlignCenter, "X")
        self._tap(*cancel_rect, self._modal_do_cancel)

        rows = m.get("rows") or (KEYPAD_NUMERIC_ROWS if m["numeric"] else KEYPAD_ROWS)
        # A route's modal makes room for its refusal under the value.
        kp_frac = 0.28 if m.get("rows") is not None else 0.24
        kp_top = box_y + box_h * kp_frac
        kp_h = box_h * (1 - kp_frac)
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
                p.drawText(QRectF(x, y, seg, row_h), Qt.AlignmentFlag.AlignCenter,
                           "SPACE" if ch == " " else ch)
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
        row_h = self._fitted_row_h(list_h, len(rows), 14)
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
                       f"{self._brg_text(brg)} {dist:.0f}NM")
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

    def _paint_route_runway(self, p, w, h):
        """A SID or STAR in the route needs a runway (RTE1b): its choices,
        and the route expands again with the one picked."""
        self._paint_overlay_backdrop(p, w, h)
        e = self._route_runway
        items = [(rw, (lambda r=rw: self._route_choose_runway(r))) for rw in e.choices]
        self._paint_menu_list(p, w, h, items, self._route_cancel_runway,
                              scroll_key="route_runway",
                              title=f"{e.airport} {e.procedure} RUNWAY")

    def _paint_dupe_chooser(self, p, w, h):
        self._paint_overlay_backdrop(p, w, h)
        items = [(" ".join(t for t in (wp.id, wp.type, getattr(wp, "region", ""),
                                       wp.name or "") if t),
                  (lambda w_=wp: self._choose_duplicate(w_)))
                 for wp in self._entry_dupe_choices]
        self._paint_menu_list(p, w, h, items, self._cancel_dupe_chooser, scroll_key="dupe_chooser")
