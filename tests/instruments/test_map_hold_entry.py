#  SPDX-License-Identifier: GPL-2.0-or-later
"""The hold entry on the moving map (HOLDENT2): the parallel or teardrop
path the fix-gateway engine reports on ``FPLHOLDENT`` for the hold on
``FPLHOLDSLOT``, drawn with the racetrack, and its name at the fix.

The geometry is checked against the engine itself: its ``_hold_geometry``
in the ENTRY phase, loaded from the fix-gateway checkout CI fetches
(``FIXGW_FLIGHTPLAN_ENGINE``; locally ``FIX_GATEWAY_SRC``). The map tests
fly the KSMX RNAV (GPS) RWY 30 missed approach to the WINCH hold (HM,
left turns, inbound 121.4 mag, 4 NM), the route block fix-gateway's
encoder builds from FAA CIFP (``tests/flightplan/fixtures/
fplroute_blocks.json``).
"""

import importlib.util
import math
import os
import pathlib
import sys
import types

import pytest
from PyQt6.QtGui import QColor, QImage, QPainter

from pyefis.flightplan import geo
from pyefis.flightplan import leg_paths as fp_legs
from pyefis.instruments import map as moving_map
from pyefis.instruments.map.layers import flight_plan as fp_layer
from tests.flightplan.test_fplroute_conformance import FIXTURE, _route_block
from tests.instruments.test_map_flight_plan_layer import _define, _define_all_fp1_keys, _owner

KSMX = "fp8-ksmx-rnav30-missed"
MAGVAR = FIXTURE["profiles"][KSMX]["magvar_deg"]
WINCH_SLOT = 11
BLACK = QColor(0, 0, 0)
ENTRIES = (fp_legs.HOLD_ENTRY_PARALLEL, fp_legs.HOLD_ENTRY_TEARDROP)


# ---------------------------------------------------------------------------
# The engine, from the fix-gateway checkout. engine.py needs only fixgw.geo,
# which needs only math, so the two files load without the rest of the
# gateway; sys.modules is restored after.
# ---------------------------------------------------------------------------
def _engine_path():
    env = os.environ.get("FIXGW_FLIGHTPLAN_ENGINE")
    if env:
        return pathlib.Path(env), True
    root = pathlib.Path(os.environ.get("FIX_GATEWAY_SRC") or "/nonexistent")
    return root / "src" / "fixgw" / "plugins" / "flightplan" / "engine.py", False


@pytest.fixture(scope="module")
def engine_mod():
    path, required = _engine_path()
    geo_path = path.parents[2] / "geo.py"
    if not (path.is_file() and geo_path.is_file()):
        if required:
            pytest.fail(f"FIXGW_FLIGHTPLAN_ENGINE={path} or {geo_path} does not exist")
        pytest.skip("set FIX_GATEWAY_SRC to a fix-gateway checkout; CI sets FIXGW_FLIGHTPLAN_ENGINE")
    saved = {k: sys.modules.get(k) for k in ("fixgw", "fixgw.geo")}
    try:
        pkg = types.ModuleType("fixgw")
        spec = importlib.util.spec_from_file_location("fixgw.geo", geo_path)
        fgeo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fgeo)
        pkg.geo = fgeo
        sys.modules["fixgw"], sys.modules["fixgw.geo"] = pkg, fgeo
        spec = importlib.util.spec_from_file_location("_holdent2_engine", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
    return mod


def _engine_entry_line(mod, fix, inbound_mag, turn, entry, magvar):
    """The engine's ENTRY-phase geometry for this hold, as a function of
    the aircraft position: ``(atd, xtk, dtk_true)``."""
    eng = mod.Engine.__new__(mod.Engine)
    eng._leg_phase = mod.LEGPHASE_ENTRY
    eng._hold_entry = entry
    eng._hold_entry_nm = fp_legs.HOLD_ENTRY_NM
    eng._hold_r_nm = fp_legs.TURN_RADIUS_NM
    wp = types.SimpleNamespace(lat=fix[0], lon=fix[1], id="HOLD", crs=inbound_mag, turn=turn, dst=4.0)

    def at(lat, lon):
        _anchor, atd, xtk, dtk = eng._hold_geometry(wp, lat, lon, magvar)
        return atd, xtk, dtk
    return at


def test_entry_constants_are_the_engines(engine_mod):
    assert fp_legs.HOLD_ENTRY_LEG_S == engine_mod.HOLD_ENTRY_LEG_S
    assert fp_legs.HOLD_TEARDROP_OFFSET_DEG == engine_mod.HOLD_TEARDROP_OFFSET_DEG
    assert (fp_legs.HOLD_ENTRY_DIRECT, fp_legs.HOLD_ENTRY_TEARDROP, fp_legs.HOLD_ENTRY_PARALLEL) == (
        engine_mod.HOLD_ENTRY_DIRECT, engine_mod.HOLD_ENTRY_TEARDROP, engine_mod.HOLD_ENTRY_PARALLEL)


@pytest.mark.parametrize("turn", ["R", "L"])
@pytest.mark.parametrize("entry", ENTRIES)
@pytest.mark.parametrize("inbound_mag,magvar", [(121.4, MAGVAR), (0.0, 0.0), (275.0, 14.0)])
def test_entry_leg_is_the_engines_entry_leg(engine_mod, entry, turn, inbound_mag, magvar):
    """The drawn entry leg is the line the engine steers in its ENTRY
    phase: every point on it is on the engine's line (XTK 0), on its
    desired track, and it ends where the engine's leg ends (ATD 0) at
    NOMINAL_GS_KT."""
    fix = (35.07348, -120.6628)
    pts = fp_legs.hold_entry_pattern(fix, fp_legs._true(inbound_mag, magvar), turn, entry)
    at = _engine_entry_line(engine_mod, fix, inbound_mag, turn, entry, magvar)
    end = pts[1]
    assert pts[0] == fix and pts[-1] == fix
    assert geo.distance_nm(*fix, *end) == pytest.approx(2.0, abs=1e-6)
    atd, xtk, _dtk = at(*end)
    assert abs(atd) < 0.01 and abs(xtk) < 0.01
    for f in (0.25, 0.5, 0.75):
        mid = geo.destination_point(*fix, geo.initial_bearing(*fix, *end), 2.0 * f)
        atd, xtk, dtk = at(*mid)
        assert abs(xtk) < 0.01
        assert atd == pytest.approx(2.0 * (1.0 - f), abs=0.01)
        brg = geo.initial_bearing(*mid, *end)
        assert abs((dtk - brg + 180.0) % 360.0 - 180.0) < 0.2


def _side(fix, inbound_true, p):
    """+1 when *p* is right of the inbound course line through *fix*."""
    loc = fp_legs._Local(*fix)
    x, y = loc.xy(*p)
    ix, iy = math.sin(math.radians(inbound_true)), math.cos(math.radians(inbound_true))
    return 1 if ix * y - iy * x < 0 else -1


@pytest.mark.parametrize("turn", ["R", "L"])
def test_entries_turn_back_toward_the_holding_side(turn):
    """A parallel flies out on the inbound course and turns back over the
    holding side; a teardrop flies out over the holding side and turns in
    the hold's own direction. Both end at the fix, where the engine's
    inbound leg ends."""
    fix, inbound = (35.0, -120.0), 40.0
    holding = 1 if turn == "R" else -1
    race = fp_legs.hold_pattern(fix, inbound, turn, 4.0)
    assert {_side(fix, inbound, p) for p in race[3:-3]} == {holding}
    par = fp_legs.hold_entry_pattern(fix, inbound, turn, "PARALLEL")
    turn_pts = par[2:-2]
    assert sum(_side(fix, inbound, p) == holding for p in turn_pts) > 0.9 * len(turn_pts)
    tdp = fp_legs.hold_entry_pattern(fix, inbound, turn, "TEARDROP")
    assert _side(fix, inbound, tdp[1]) == holding
    # The teardrop turn is in the hold's direction: heading changes with the
    # sign of the turn all the way round.
    hdgs = [geo.initial_bearing(*a, *b) for a, b in zip(tdp[1:-1], tdp[2:-1]) if a != b]
    steps = [(b - a + 180.0) % 360.0 - 180.0 for a, b in zip(hdgs, hdgs[1:])]
    assert all(s * holding > -1e-6 for s in steps)
    assert par[-1] == fix and tdp[-1] == fix


@pytest.mark.parametrize("entry,turn", [("DIRECT", "R"), ("", "R"), ("SIDEWAYS", "L"),
                                        ("PARALLEL", ""), ("TEARDROP", "E")])
def test_direct_or_unknown_entry_draws_nothing_extra(entry, turn):
    assert fp_legs.hold_entry_pattern((35.0, -120.0), 90.0, turn, entry) == []


# ---------------------------------------------------------------------------
# The layer, on the KSMX missed approach.
# ---------------------------------------------------------------------------
def _writes(seq=1):
    return [(k, seq if k == "FPLSEQ" else v) for k, v in FIXTURE["profiles"][KSMX]["writes"]]


def _load(fix, hold=None, define=True):
    """KSMX's route on the bus, loaded (FPLLDSEQ 1). *hold* is ``(slot,
    entry, committed)`` for FPLHOLDSLOT/ENT/COMMIT, None for a gateway
    without the keys."""
    if define:
        _define_all_fp1_keys(fix)
        _define(fix, "FPLAPRTYPE", "str", "")
        _define(fix, "MAGVAR", "float", MAGVAR)
        _define(fix, "FPLLDSEQ", "int", 1)
        if hold is not None:
            _define(fix, "FPLHOLDSLOT", "int", hold[0])
            _define(fix, "FPLHOLDENT", "str", hold[1])
            _define(fix, "FPLHOLDCOMMIT", "bool", hold[2])
    for key, value in _writes():
        fix.db.set_value(key, value)


def _layer(qtbot):
    layer = fp_layer.FlightPlanLayer()
    layer.configure(_owner(qtbot))
    return layer


def _route():
    return _route_block(_writes())


def _winch():
    w = _route().waypoints[WINCH_SLOT - 1]
    return (w.lat, w.lon)


def _render(layer, centre=None, range_nm=6.0, size=500):
    centre = centre or _winch()
    x = moving_map.MapTransform(centre[0], centre[1], range_nm, 0.0, size, size, 0.5)
    img = QImage(size, size, QImage.Format.Format_RGB32)
    img.fill(0)
    p = QPainter(img)
    layer.paint(p, x)
    p.end()
    return img, x


def _ink_near(img, c, rad=2):
    return any(img.pixelColor(int(round(c.x())) + dx, int(round(c.y())) + dy) != BLACK
               for dx in range(-rad, rad + 1) for dy in range(-rad, rad + 1))


def _dense(points, step_nm=0.05):
    """*points* with every segment filled in at *step_nm*."""
    out = []
    for a, b in zip(points, points[1:]):
        d = geo.distance_nm(*a, *b)
        n = max(1, int(d / step_nm))
        brg = geo.initial_bearing(*a, *b)
        out += [geo.destination_point(*a, brg, d * i / n) for i in range(n)]
    return out + points[-1:]


def _entry_only_points(entry):
    """Points on *entry*'s path at WINCH well clear of the racetrack and of
    the leg into the fix, where only the entry can put ink."""
    route = _route()
    w = route.waypoints[WINCH_SLOT - 1]
    inbound = fp_legs._true(w.crs, MAGVAR)
    pts = fp_legs.hold_entry_pattern((w.lat, w.lon), inbound, w.turn, entry)
    race = fp_legs.hold_pattern((w.lat, w.lon), inbound, w.turn, w.dst)
    prev = route.waypoints[WINCH_SLOT - 3]
    others = _dense(race) + _dense([(prev.lat, prev.lon), _winch()])
    return [p for p in pts if min(geo.distance_nm(*p, *q) for q in others) > 0.4]


def test_the_planned_missed_approach_predicts_a_parallel_entry(engine_mod):
    """The KSMX fixture's arrival from HANNU, through the engine's own
    hold_entry: PARALLEL, the case the map tests below draw."""
    route = _route()
    w, prev = route.waypoints[WINCH_SLOT - 1], route.waypoints[WINCH_SLOT - 3]
    arrival = geo.initial_bearing(prev.lat, prev.lon, w.lat, w.lon)
    assert engine_mod.hold_entry(fp_legs._true(w.crs, MAGVAR), w.turn, arrival) == "PARALLEL"


@pytest.mark.parametrize("entry", ENTRIES)
def test_the_entry_is_drawn_with_the_racetrack(fix, qtbot, entry):
    _load(fix, hold=(WINCH_SLOT, entry, False))
    img, x = _render(_layer(qtbot))
    pts = _entry_only_points(entry)
    assert len(pts) >= 5
    assert all(_ink_near(img, x.to_screen(*p), rad=3) for p in pts)


@pytest.mark.parametrize("hold", [None, (WINCH_SLOT, "", False), (0, "", False),
                                  (WINCH_SLOT, "DIRECT", False), (WINCH_SLOT, "DIRECT", True)])
def test_no_key_empty_key_or_direct_draws_the_racetrack_alone(fix, qtbot, hold):
    """No entry path for an older gateway, an empty entry, slot 0 or a
    direct entry: the legs and racetrack are pixel-identical to a gateway
    without the keys, apart from the label a named entry carries."""
    _load(fix, hold=None)
    base, x = _render(_layer(qtbot), range_nm=6.0)
    if hold is not None:
        _define(fix, "FPLHOLDSLOT", "int", hold[0])
        _define(fix, "FPLHOLDENT", "str", hold[1])
        _define(fix, "FPLHOLDCOMMIT", "bool", hold[2])
    img, _ = _render(_layer(qtbot), range_nm=6.0)
    # Compare away from the label above WINCH.
    c = x.to_screen(*_winch())
    diff = [(px, py) for px in range(0, img.width(), 2) for py in range(0, img.height(), 2)
            if img.pixelColor(px, py) != base.pixelColor(px, py)
            and not (abs(px - c.x()) < 70 and c.y() - 45 < py < c.y())]
    assert diff == []
    for entry in ENTRIES:
        assert not any(_ink_near(img, x.to_screen(*p)) for p in _entry_only_points(entry))


class _Recorder:
    """Records the pen style at each drawPolyline and every drawText, for a
    real QPainter underneath."""

    def __init__(self, img):
        self.p = QPainter(img)
        self.polylines = []
        self.texts = []

    def __getattr__(self, name):
        return getattr(self.p, name)

    def drawPolyline(self, poly):
        self.polylines.append((poly, self.p.pen().style()))
        self.p.drawPolyline(poly)

    def drawText(self, *args):
        self.texts.append(args[-1])
        self.p.drawText(*args)


def _record(layer, size=500):
    x = moving_map.MapTransform(*_winch(), 6.0, 0.0, size, size, 0.5)
    img = QImage(size, size, QImage.Format.Format_RGB32)
    img.fill(0)
    rec = _Recorder(img)
    layer.paint(rec, x)
    rec.p.end()
    return rec


@pytest.mark.parametrize("committed,style", [(False, "DashLine"), (True, "SolidLine")])
def test_a_predicted_entry_is_dashed_and_a_committed_one_solid(fix, qtbot, committed, style):
    _load(fix, hold=(WINCH_SLOT, "TEARDROP", committed))
    layer = _layer(qtbot)
    rec = _record(layer)
    poly = layer._snapshot.entry_poly
    got = [s for p, s in rec.polylines if p is poly]
    assert len(got) == 1
    assert got[0].name == style


def test_the_fix_carries_the_entry_name_and_it_follows_the_engine(fix, qtbot):
    _load(fix, hold=(WINCH_SLOT, "PARALLEL", False))
    layer = _layer(qtbot)
    assert "PARALLEL" in _record(layer).texts
    fix.db.set_value("FPLHOLDENT", "TEARDROP")
    layer.collect(None)
    texts = _record(layer).texts
    assert "TEARDROP" in texts and "PARALLEL" not in texts
    fix.db.set_value("FPLHOLDENT", "")
    layer.collect(None)
    texts = _record(layer).texts
    assert not {"TEARDROP", "PARALLEL", "DIRECT"} & set(texts)
    assert layer._snapshot.entry_poly is None


def _reroute_without_hannu(fix, seq):
    """Commit the same missed approach with HANNU (slot 9) deleted: the hold
    moves to slot 10."""
    w = dict(_writes())
    names = [n for n, _t, _b in fp_layer.fp_fixbridge.SLOT_FIELDS]
    for n in names:
        w[f"FPL9{n}"] = w[f"FPL10{n}"]
        w[f"FPL10{n}"] = w[f"FPL11{n}"]
    blanks = {n: b for n, _t, b in fp_layer.fp_fixbridge.SLOT_FIELDS}
    for n in names:
        w[f"FPL11{n}"] = blanks[n]
    w["FPLCOUNT"] = 10
    w["FPLS2LAST"] = 10
    w["FPLSEQ"] = seq
    for key, value in w.items():
        if key != "FPLSEQ":
            fix.db.set_value(key, value)
    fix.db.set_value("FPLLDSEQ", seq)
    fix.db.set_value("FPLSEQ", seq)


def test_the_entry_follows_a_reroute(fix, qtbot):
    """A re-route that moves the hold to another slot: the entry and its
    label move with the engine's FPLHOLDSLOT, and a slot that is no longer
    a hold draws none."""
    _load(fix, hold=(WINCH_SLOT, "PARALLEL", False))
    layer = _layer(qtbot)
    before = layer._snapshot.entry_poly
    _reroute_without_hannu(fix, 2)
    layer.collect(None)
    # The engine has not yet re-published: slot 11 is empty now, not a hold.
    assert layer._snapshot.entry is None
    fix.db.set_value("FPLHOLDSLOT", 10)
    fix.db.set_value("FPLHOLDENT", "TEARDROP")
    layer.collect(None)
    snap = layer._snapshot
    assert snap.entry == (10, "TEARDROP", False)
    assert snap.entry_poly is not None and snap.entry_poly is not before
    assert "TEARDROP" in _record(layer).texts
    pts = _entry_only_points("TEARDROP")
    img, x = _render(layer)
    assert all(_ink_near(img, x.to_screen(*p), rad=3) for p in pts)


def _keys(slot, entry, commit=False):
    from tests.instruments.test_map_flight_plan_layer import _engine
    return _engine(FPLHOLDSLOT=slot, FPLHOLDENT=entry, FPLHOLDCOMMIT=commit)


def test_hold_entry_key_reads_only_a_hold_slot():
    route = _route()
    assert fp_layer.hold_entry_key(route, _keys(WINCH_SLOT, "PARALLEL", True)) == (WINCH_SLOT, "PARALLEL", True)
    # Slot 10 is the TF into WINCH, at the same fix: not a hold, no entry.
    assert fp_layer.hold_entry_key(route, _keys(WINCH_SLOT - 1, "PARALLEL")) is None
    assert fp_layer.hold_entry_key(route, _keys(WINCH_SLOT + 1, "PARALLEL")) is None
    assert fp_layer.hold_entry_key(route, _keys(0, "PARALLEL")) is None
    assert fp_layer.hold_entry_key(route, _keys(WINCH_SLOT, "")) is None
    assert fp_layer.hold_entry_key(route, _keys(WINCH_SLOT, "parallel")) is None
    no_commit = _keys(WINCH_SLOT, "PARALLEL")
    del no_commit["FPLHOLDCOMMIT"]
    assert fp_layer.hold_entry_key(route, no_commit) is None


@pytest.mark.parametrize("entry,full,short", [("PARALLEL", "PARALLEL", "PAR"),
                                              ("TEARDROP", "TEARDROP", "TDP"),
                                              ("DIRECT", "DIRECT", "DIR")])
def test_entry_label_short_form(entry, full, short):
    assert fp_layer.hold_entry_label(entry, lambda t: True) == full
    assert fp_layer.hold_entry_label(entry, lambda t: False) == short


def test_entry_is_built_once_per_change_never_per_frame(fix, qtbot, monkeypatch):
    _load(fix, hold=(WINCH_SLOT, "PARALLEL", False))
    layer = _layer(qtbot)
    calls = []
    real = fp_legs.hold_entry_pattern
    monkeypatch.setattr(fp_legs, "hold_entry_pattern", lambda *a, **k: calls.append(a) or real(*a, **k))
    for _ in range(3):
        _render(layer)
        fix.db.set_value("FPLXTK", 0.1 * len(calls))
        layer.collect(None)
    assert calls == []
    fix.db.set_value("FPLHOLDCOMMIT", True)
    layer.collect(None)
    layer.collect(None)
    assert len(calls) == 1
    assert layer._snapshot.entry == (WINCH_SLOT, "PARALLEL", True)


def test_a_commit_flip_asks_for_a_frame(fix, qtbot):
    """Reaching the fix flips FPLHOLDCOMMIT: the entry turns solid in the
    next frame, without waiting for anything else to move."""
    _load(fix, hold=(WINCH_SLOT, "PARALLEL", False))
    owner = _owner(qtbot)
    frames = []
    owner.request_frame = lambda: frames.append(1)
    layer = fp_layer.FlightPlanLayer()
    layer.configure(owner)
    fix.db.set_value("FPLHOLDCOMMIT", True)
    qtbot.wait(10)
    assert frames and layer._snapshot.entry == (WINCH_SLOT, "PARALLEL", True)
    del frames[:]
    fix.db.set_value("FPLHOLDCOMMIT", True)
    qtbot.wait(10)
    assert frames == []

