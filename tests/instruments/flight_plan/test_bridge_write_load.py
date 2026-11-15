#  SPDX-License-Identifier: GPL-2.0-or-later
"""The FPL page re-reads the route only when the route on the bus changes.

The fix-gateway flight-plan engine rewrites every one of its outputs each
guidance cycle (25 keys at ``rate_hz``, 5 Hz by default), changed or not,
and the bridge calls its listeners on each write. The route block's writer
order (RS1, ``FixBridge.publish``) is that ``FPLSEQ`` goes last and
"consumers act only on the ``FPLSEQ`` change", so a write of ``WPDIS`` is
no reason to read 14 fields of every slot, rebuild the plan and deep-copy
it. Measured on the Beelink bench with an 18-waypoint plan and two
``flight_plan`` widgets loaded, that work held the GUI thread about a
quarter of a core, in blocks long enough to drop synthetic-vision frames.

These tests use a ``flight_plan`` widget on its own: there is no moving map
in the process, and the widget must not need one.
"""

from pyefis.flightplan import catalog as fp_catalog
from pyefis.flightplan import fixbridge
from pyefis.flightplan import model as fp_model
from tests.instruments.flight_plan import test_flight_plan as base
from tests.instruments.flight_plan import test_refused_commit as refused


def _engine_cycle(fix, wpdis):
    """One guidance cycle as the engine writes it: every output key, most
    of them with the value they already hold."""
    for key in fixbridge.ENGINE_OUTPUT_KEYS:
        item = fix.db.get_item(key)
        fix.db.set_value(key, wpdis if key == "WPDIS" else item.value)


def _count_route_reads(w, monkeypatch):
    reads = []
    read_route = w._bridge.read_route

    def counted():
        reads.append(1)
        return read_route()

    monkeypatch.setattr(w._bridge, "read_route", counted)
    return reads


class _Clock:
    """The widget's clock, moved by hand (``w._clock``)."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _flying_with_clock(fix, qtbot):
    w = refused._flying(fix, qtbot)
    w._clock = clock = _Clock()
    w._route_checked_at = clock.now
    return w, clock


def test_engine_output_writes_do_not_reread_the_route(fix, qtbot, monkeypatch):
    w, _clock = _flying_with_clock(fix, qtbot)
    reads = _count_route_reads(w, monkeypatch)

    for n in range(5):
        _engine_cycle(fix, 12.0 - n)

    assert reads == []
    assert refused._ids(w._plan) == ["ALPHA", "BRAVO", "CHARL"]


def test_the_route_is_checked_against_the_bus_at_most_once_a_second(fix, qtbot, monkeypatch):
    w, clock = _flying_with_clock(fix, qtbot)
    reads = _count_route_reads(w, monkeypatch)

    for n in range(10):                 # two seconds of 5 Hz engine cycles
        clock.now += 0.2
        _engine_cycle(fix, 12.0 - n)

    assert len(reads) == 2
    assert refused._ids(w._plan) == ["ALPHA", "BRAVO", "CHARL"]


def test_a_slot_written_after_the_key_still_reaches_the_page(fix, qtbot):
    """A gateway reconnect re-sends the database in its own order, and a
    writer can break the FPLSEQ-last order: the slots then differ from the
    route last read with no change of the key. The page converges on the
    bus within route_verify_s."""
    w, clock = _flying_with_clock(fix, qtbot)

    fix.db.set_value("FPL2ID", "LATE")          # no FPLSEQ write
    _engine_cycle(fix, 6.0)
    assert refused._ids(w._plan) == ["ALPHA", "BRAVO", "CHARL"]

    clock.now += w.route_verify_s
    _engine_cycle(fix, 5.9)
    assert refused._ids(w._plan) == ["ALPHA", "LATE", "CHARL"]


def test_the_check_leaves_an_uncommitted_working_copy_alone(fix, qtbot, tmp_path):
    w, clock = _flying_with_clock(fix, qtbot)
    base._install_catalog(w, fp_catalog.Catalog(tmp_path))
    slug = w._ensure_catalog().save(fp_model.FlightPlan(
        name="AB", waypoints=[fp_model.Waypoint(id="A", type="fix", lat=0, lon=0)]))
    w._catalog_edit(slug)

    for _ in range(3):
        clock.now += w.route_verify_s
        _engine_cycle(fix, 5.0)

    assert refused._ids(w._plan) == ["A"]       # the bus route did not change


def test_engine_outputs_still_reach_the_page_on_every_write(fix, qtbot):
    w = refused._flying(fix, qtbot)

    _engine_cycle(fix, 7.5)
    assert w._engine_value("WPDIS") == 7.5
    _engine_cycle(fix, 7.25)
    assert w._engine_value("WPDIS") == 7.25


def test_a_commit_from_another_display_is_still_taken(fix, qtbot, monkeypatch):
    w, _clock = _flying_with_clock(fix, qtbot)
    reads = _count_route_reads(w, monkeypatch)
    _engine_cycle(fix, 9.0)

    refused._other_display(fix).publish(refused._refused())
    refused._accept(fix)

    assert refused._ids(w._plan) == ["XRAYA", "XRAYB"]
    assert refused._ids(w._flown_plan) == ["XRAYA", "XRAYB"]
    assert reads != []
    del reads[:]
    _engine_cycle(fix, 8.0)
    assert reads == []


def test_catalog_edit_working_copy_survives_engine_writes(fix, qtbot, tmp_path):
    """Catalog "Edit" loads a stored plan into the working copy without
    publishing it; the route on the bus is untouched until the next edit
    commits. The engine writing its outputs is not a commit, and must not
    put the bus route back on the page."""
    w = refused._flying(fix, qtbot)
    base._install_catalog(w, fp_catalog.Catalog(tmp_path))
    slug = w._ensure_catalog().save(fp_model.FlightPlan(
        name="AB", waypoints=[fp_model.Waypoint(id="A", type="fix", lat=0, lon=0)]))

    w._catalog_edit(slug)
    _engine_cycle(fix, 5.0)

    assert refused._ids(w._plan) == ["A"]
    assert int(fix.db.get_item("FPLCOUNT").value) == 3   # bus untouched


def test_route_key_tracks_the_keys_a_commit_writes_last(fix, qtbot):
    refused._bus(fix)
    bridge = fixbridge.FixBridge(fix)
    before = bridge.route_key()

    bridge.publish(refused._flown())
    committed = bridge.route_key()
    assert committed != before
    assert committed[:2] == (int(fix.db.get_item("FPLSEQ").value), 3)

    refused._accept(fix)
    loaded = bridge.route_key()
    assert loaded != committed                   # FPLLDSEQ is part of it

    fix.db.set_value("WPDIS", 3.0)
    assert bridge.route_key() == loaded          # an engine output is not


def test_route_key_without_fplldseq_reads_none_for_the_loaded_seq(fix, qtbot):
    refused._bus(fix, loaded=False)
    bridge = fixbridge.FixBridge(fix)
    bridge.publish(refused._flown())
    assert bridge.route_key()[3] is None


# pyEfis #480 (FPLWRITE2): an engine output write reads nothing. The page
# used to build its engine dict (27 lookups) on every write, 25 writes a
# cycle, for each widget loaded, hidden or not; now a write marks it stale
# and the next read of a value rebuilds it.


def _count_lookups(w, monkeypatch):
    calls = []
    get = w._bridge._get

    def counted(key):
        calls.append(key)
        return get(key)

    monkeypatch.setattr(w._bridge, "_get", counted)
    return calls


def test_an_engine_output_write_reads_nothing_from_the_bus(fix, qtbot, monkeypatch):
    w, _clock = _flying_with_clock(fix, qtbot)
    lookups = _count_lookups(w, monkeypatch)

    for key in fixbridge.ENGINE_OUTPUT_KEYS:
        if key != "WPDIS":
            fix.db.set_value(key, fix.db.get_item(key).value)
    fix.db.set_value("WPDIS", 4.0)

    assert lookups == []
    assert w._engine_value("WPDIS") == 4.0


def test_the_engine_outputs_are_read_once_however_many_writes(fix, qtbot, monkeypatch):
    w, _clock = _flying_with_clock(fix, qtbot)
    reads = []
    read_engine = w._bridge.read_engine
    monkeypatch.setattr(w._bridge, "read_engine", lambda: (reads.append(1), read_engine())[1])

    for n in range(5):
        _engine_cycle(fix, 12.0 - n)
    assert reads == []

    assert w._engine_value("WPDIS") == 8.0
    assert w._engine_value("FPLSTATE") == fix.db.get_item("FPLSTATE").value
    assert reads == [1]


def test_a_hidden_page_reads_nothing_on_engine_output_writes(fix, qtbot, monkeypatch):
    w, _clock = _flying_with_clock(fix, qtbot)
    w.hide()
    lookups = _count_lookups(w, monkeypatch)

    for n in range(5):
        _engine_cycle(fix, 12.0 - n)

    assert lookups == []
