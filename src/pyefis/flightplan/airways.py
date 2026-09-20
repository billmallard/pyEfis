#  SPDX-License-Identifier: GPL-2.0-or-later
"""Airway lookup + expansion over the ``procedures`` pack's ``airways`` /
``airway_legs`` tables (PA2, billmallard/pyEfis#235, AER-1601).

See ``makerplane/briefs/procedures_and_airways_plan.md`` section 3.4. The
pack is built by ``makerplane-data`` PA1 (AER-1600):
``airways(id, ident, cycle)`` + ``airway_legs(airway_id, seq, fix_id,
fix_lat, fix_lon, fix_type, min_alt_ft, max_alt_ft, direction)`` with
indexes ``idx_awy_ident``, ``idx_awyleg_awy(airway_id, seq)`` and
``idx_awyleg_fix(fix_id)``. Every query here is shaped to hit one of those
three indexes -- none of them is a table scan.

An airway segment is a ``TF`` leg (great circle, fly-by), so no leg model is
needed to route one: :meth:`AirwayGraph.expand` returns ordinary
``model.Waypoint`` (``type="fix"``) instances the caller inserts straight
into a :class:`pyefis.flightplan.model.FlightPlan`, exactly as the brief
specifies ("the expansion is inserted collapsed... and emits the
intermediate fixes as ordinary TYPE=fix waypoints"). Per-leg altitude
constraints are a different thing (PA3's leg model owns those) and are
deliberately not smuggled onto the emitted waypoints; see
:meth:`AirwayGraph.altitude_range` for the MEA/ceiling check instead.

Construction never raises: a missing or unreadable pack just leaves
``ready`` False and every query answers as if the airway table were empty
-- mirrors ``ai/obstacle_db.py`` ``ObstacleDB`` (CLAUDE.md "construct-never-
raises database loaders").

Qt-free: nothing here may import PyQt6.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from . import model

log = logging.getLogger(__name__)


class AirwayError(ValueError):
    """Base class for every airway-insertion refusal -- always a caller
    mistake (an unknown ident, a fix not on the airway, a one-way violation),
    never an internal fault, so callers can catch this one class and show
    ``str(exc)`` to the pilot."""


class AirwayNotFoundError(AirwayError):
    pass


class FixNotOnAirwayError(AirwayError):
    pass


class AirwayDirectionError(AirwayError):
    """Raised when the requested entry/exit direction of travel crosses a
    leg coded one-way against it (ARINC 424 5.4 Direction Restriction)."""


@dataclass
class AirwayLeg:
    seq: int
    fix_id: str
    lat: float
    lon: float
    fix_type: str | None
    min_alt_ft: int | None
    max_alt_ft: int | None
    direction: str | None  # None (both directions) | "F" | "B"


def _norm(ident: str) -> str:
    return (ident or "").strip().upper()


class AirwayGraph:
    """Lookup + expansion service over one ``procedures`` pack's airway
    tables. One instance per pack; safe to hold for the process lifetime."""

    def __init__(self, procedures_db_path: str | Path | None = None):
        self._path = Path(procedures_db_path) if procedures_db_path else None
        self._con: sqlite3.Connection | None = None
        if self._path is None or not self._path.is_file():
            log.info("AirwayGraph: %s not found -- airway lookup disabled",
                      self._path)
            return
        try:
            con = sqlite3.connect(str(self._path), check_same_thread=False)
            con.row_factory = sqlite3.Row
            con.execute("SELECT 1 FROM airways LIMIT 1")
            self._con = con
        except Exception as e:
            log.warning("AirwayGraph: cannot open %s: %s", self._path, e)
            self._con = None

    @property
    def ready(self) -> bool:
        return self._con is not None

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------
    def airways_through_fix(self, fix_id: str) -> list[str]:
        """Idents of every airway passing through *fix_id*, sorted --
        drives the "LOAD AIRWAY" fix-selection step. Hits
        ``idx_awyleg_fix``. Empty if not ready or the fix is on no
        airway."""
        if not self.ready:
            return []
        norm = _norm(fix_id)
        rows = self._con.execute(
            "SELECT DISTINCT a.ident FROM airway_legs al "
            "JOIN airways a ON a.id = al.airway_id "
            "WHERE al.fix_id = ? ORDER BY a.ident", (norm,)).fetchall()
        return [r["ident"] for r in rows]

    def legs(self, ident: str) -> list[AirwayLeg]:
        """Every leg of *ident*, in published (ascending ``seq``) order --
        drives the exit-fix picker once an airway is chosen. Hits
        ``idx_awy_ident`` then ``idx_awyleg_awy``. Empty if not ready or
        *ident* is unknown."""
        if not self.ready:
            return []
        norm = _norm(ident)
        rows = self._con.execute(
            "SELECT al.seq, al.fix_id, al.fix_lat, al.fix_lon, al.fix_type, "
            "al.min_alt_ft, al.max_alt_ft, al.direction "
            "FROM airway_legs al JOIN airways a ON a.id = al.airway_id "
            "WHERE a.ident = ? ORDER BY al.seq", (norm,)).fetchall()
        return [AirwayLeg(seq=r["seq"], fix_id=r["fix_id"],
                           lat=r["fix_lat"], lon=r["fix_lon"],
                           fix_type=r["fix_type"],
                           min_alt_ft=r["min_alt_ft"], max_alt_ft=r["max_alt_ft"],
                           direction=(r["direction"] or None))
                for r in rows]

    # ------------------------------------------------------------------
    # Expansion
    # ------------------------------------------------------------------
    def expand(self, ident: str, entry_fix_id: str, exit_fix_id: str) -> list[model.Waypoint]:
        """The published fix sequence of *ident* between *entry_fix_id* and
        *exit_fix_id*, inclusive of both ends, in the direction of travel
        implied by their order on the airway (reversed if *entry_fix_id*
        has the higher ``seq``). Raises :class:`AirwayNotFoundError` if
        *ident* is unknown or the pack is not loaded,
        :class:`FixNotOnAirwayError` if either fix is not on *ident*,
        :class:`AirwayError` if entry and exit are the same fix, and
        :class:`AirwayDirectionError` if the requested direction crosses a
        leg coded one-way against it."""
        segment = self._resolve_segment(ident, entry_fix_id, exit_fix_id)
        return [model.Waypoint(id=leg.fix_id, type="fix",
                                lat=leg.lat, lon=leg.lon)
                for leg in segment]

    def altitude_range(self, ident: str, entry_fix_id: str,
                        exit_fix_id: str) -> tuple[int | None, int | None]:
        """``(min_alt_ft, max_alt_ft)`` enforceable over the segment of
        *ident* between *entry_fix_id* and *exit_fix_id* -- the highest
        published leg minimum (the MEA a pilot must be at or above for the
        whole segment) and the lowest published leg maximum. Either may be
        ``None`` if the pack carries no restriction. Same errors as
        :meth:`expand`. The caller (PA6/PA9) compares this against the
        planned altitude and states the actual figure in the warning --
        this method only enforces direction, per brief section 3.4."""
        segment = self._resolve_segment(ident, entry_fix_id, exit_fix_id)
        mins = [leg.min_alt_ft for leg in segment if leg.min_alt_ft is not None]
        maxs = [leg.max_alt_ft for leg in segment if leg.max_alt_ft is not None]
        return (max(mins) if mins else None, min(maxs) if maxs else None)

    def _resolve_segment(self, ident: str, entry_fix_id: str,
                          exit_fix_id: str) -> list[AirwayLeg]:
        if not self.ready:
            raise AirwayNotFoundError(
                f"no procedures pack loaded -- cannot resolve airway {ident!r}")
        entry_norm, exit_norm = _norm(entry_fix_id), _norm(exit_fix_id)
        if entry_norm == exit_norm:
            raise AirwayError(
                f"{ident}: entry and exit fix must differ ({entry_fix_id!r})")

        rows = self.legs(ident)
        if not rows:
            raise AirwayNotFoundError(f"unknown airway {ident!r}")

        entry_idx = next((i for i, r in enumerate(rows) if _norm(r.fix_id) == entry_norm), None)
        if entry_idx is None:
            raise FixNotOnAirwayError(f"{entry_fix_id!r} is not on airway {ident}")
        exit_idx = next((i for i, r in enumerate(rows) if _norm(r.fix_id) == exit_norm), None)
        if exit_idx is None:
            raise FixNotOnAirwayError(f"{exit_fix_id!r} is not on airway {ident}")

        # Direction Restriction (ARINC 424 5.4) is coded on the row of the
        # fix that TERMINATES a leg, describing that one leg (the segment
        # from the previous seq to this one): "F" = forward (ascending seq)
        # only, "B" = backward (descending seq) only, blank = both. Walking
        # forward crosses the terminating rows of every leg strictly after
        # entry up to and including exit; walking backward crosses the same
        # rows, checked against the opposite restriction.
        if entry_idx < exit_idx:
            traversed = rows[entry_idx + 1:exit_idx + 1]
            violation = next((r for r in traversed if r.direction == "B"), None)
            if violation is not None:
                raise AirwayDirectionError(
                    f"{ident} is one-way (backward only) at seq {violation.seq} "
                    f"({violation.fix_id}) -- cannot fly {entry_fix_id} -> {exit_fix_id}")
            return rows[entry_idx:exit_idx + 1]
        else:
            traversed = rows[exit_idx + 1:entry_idx + 1]
            violation = next((r for r in traversed if r.direction == "F"), None)
            if violation is not None:
                raise AirwayDirectionError(
                    f"{ident} is one-way (forward only) at seq {violation.seq} "
                    f"({violation.fix_id}) -- cannot fly {entry_fix_id} -> {exit_fix_id}")
            return list(reversed(rows[exit_idx:entry_idx + 1]))
