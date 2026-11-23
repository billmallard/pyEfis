#  SPDX-License-Identifier: GPL-2.0-or-later
"""FPA2 (AER-6419): Store keeps what the bus does not carry.

After a commit the page's plan is the route read back off the bus
(``route_to_plan``), and the bus has no slot for a waypoint's name, planned
altitude, comment or extra fields, nor for the plan's comment, created
stamp, source or extra fields, and it carries one ``FPLDBCYC`` for the
whole plan. Storing a catalog route the pilot had activated used to
rewrite its file without them, with a fresh ``created``.

The page now keeps the off-bus fields of the plan it committed and puts
them back when the route it reads is that commit (same ``FPLSEQ``, same
fixes). Every field the bus carries still comes from the bus, and a route
another writer committed (the map, a second display) is read from the bus
alone.
"""

import json

from pyefis.flightplan import catalog as fp_catalog
from pyefis.flightplan import fixbridge
from pyefis.flightplan import model as fp_model
from tests.instruments.flight_plan import test_flight_plan as base
from tests.instruments.flight_plan import test_refused_commit as rc


def _stored_route():
    """A catalog route with everything the bus drops: waypoint names, a
    planned altitude, comments and extra fields, a plan comment, source and
    extra field, and two airways expanded from different AIRAC cycles."""
    def wp(ident, lat, **kw):
        return fp_model.Waypoint(id=ident, type="fix", lat=lat, lon=-119.0, **kw)

    return fp_model.FlightPlan(
        name="COAST RUN", comment="Coastal VFR, fuel at KSMX",
        created="2026-01-02T03:04:05+00:00", source="configurator",
        extra={"author": "bill"},
        segments=[
            fp_model.waypoint_segment(wp("ALPHA", 34.0, name="Alpha Field",
                                         alt_ft=4500.0, comment="depart east",
                                         extra={"freq": "122.8"})),
            fp_model.Segment(kind="airway", ident="V27", cycle="2610",
                             legs=[wp("BRAVO", 34.1, name="Bravo Int"),
                                   wp("CHARL", 34.2)]),
            fp_model.Segment(kind="airway", ident="V25", cycle="2611",
                             legs=[wp("CHARL", 34.2), wp("DELTA", 34.3)],
                             extra={"note": "MEA 6000"}),
            fp_model.waypoint_segment(wp("ECHOO", 34.4, comment="land")),
        ])


def _activate_stored(fix, qtbot, tmp_path):
    rc._bus(fix)
    w = rc._widget(qtbot)
    cat = fp_catalog.Catalog(tmp_path)
    base._install_catalog(w, cat)
    slug = cat.save(_stored_route())
    w._catalog_activate(slug)
    rc._accept(fix)
    w._on_bridge_change("FPLLDSEQ")
    return w, slug


def _stored(tmp_path, slug):
    return json.loads((tmp_path / f"{slug}.json").read_text(encoding="utf-8"))


def test_store_after_activate_keeps_the_off_bus_fields(fix, qtbot, tmp_path):
    """The DoD repro: load a catalog route with waypoint names and a
    comment, commit it, let the bridge sync, Store: the file still has
    them, the created stamp it was saved with, and each airway's cycle."""
    w, slug = _activate_stored(fix, qtbot, tmp_path)
    before = _stored(tmp_path, slug)
    assert int(fix.db.get_item("FPLLDSEQ").value) == int(fix.db.get_item("FPLSEQ").value)

    w._menu_store()

    assert w._message == "STORED"
    after = _stored(tmp_path, slug)
    for field in ("name", "comment", "created", "source", "author"):
        assert after[field] == before[field], field
    assert after["segments"] == before["segments"]
    assert after["modified"] >= before["modified"]


def test_bus_fields_still_come_from_the_bus(fix, qtbot, tmp_path):
    """The off-bus fields ride along; the route itself is the one read
    back. A slot field the engine wrote under the same FPLSEQ is kept."""
    w, _slug = _activate_stored(fix, qtbot, tmp_path)
    assert w._plan.waypoints[0].name == "Alpha Field"
    assert w._plan.waypoints[1].crs is None
    fix.db.set_value("FPL1LAT", 34.05)
    w._sync_plan_from_bridge()
    assert w._plan.waypoints[0].lat == 34.05
    assert w._plan.waypoints[0].name == "Alpha Field"


def test_route_from_another_writer_comes_from_the_bus(fix, qtbot, tmp_path):
    """The same route -- same fixes, same airways -- committed by another
    writer (the map, a second display) is a new FPLSEQ: the page reads it
    from the bus and keeps nothing of its own commit."""
    w, slug = _activate_stored(fix, qtbot, tmp_path)
    other = rc._other_display(fix)
    other.publish(fixbridge.route_to_plan(other.read_route()))
    rc._accept(fix)
    w._on_bridge_change("FPLLDSEQ")

    assert [wp.id for wp in w._plan.waypoints] == ["ALPHA", "BRAVO", "CHARL", "CHARL",
                                                   "DELTA", "ECHOO"]
    assert all(wp.name == "" and wp.comment == "" for wp in w._plan.waypoints)
    assert w._plan.comment == ""
    w._menu_store()
    after = _stored(tmp_path, slug)
    assert after["comment"] == ""
    assert after["created"] != "2026-01-02T03:04:05+00:00"


def test_changed_fixes_under_the_same_seq_come_from_the_bus(fix, qtbot, tmp_path):
    """A slot rewritten without a new FPLSEQ (a writer that did not write
    it last) no longer matches the commit: nothing is carried onto a
    different route."""
    w, _slug = _activate_stored(fix, qtbot, tmp_path)
    fix.db.set_value("FPL1ID", "ZULUU")
    w._sync_plan_from_bridge()
    assert w._plan.waypoints[0].id == "ZULUU"
    assert all(wp.name == "" and wp.comment == "" for wp in w._plan.waypoints)
    assert w._plan.comment == ""
