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

Every airway leg is a ``TF`` leg (great circle, fly-by):
:meth:`AirwayGraph.expand` returns ordinary ``model.Waypoint`` legs, which
:meth:`pyefis.flightplan.model.FlightPlan.insert_airway` wraps in one
``airway`` segment (RS2, billmallard/pyEfis#305). Each waypoint's ``type``
comes from the pack's ``fix_type`` (``vor``/``ndb``/``airport`` carry over;
``waypoint``, ``runway`` and blank become ``fix``), so a VOR inside an
airway publishes the same ``FPLfTYPE`` as the same VOR entered by name
(RS5, AER-5267). Each leg carries the MEA of the airway leg that ends at it
as its packed altitude constraint (``alt="+7000"``), so the bridge can
publish it as ``FPLfALT`` (route segments brief section 3); the entry fix
carries none, because the leg into it is not on the airway.
:meth:`AirwayGraph.altitude_range` still answers the segment-wide
MEA/ceiling question.

Which leg a row's altitudes describe (RS5, AER-5267). An ``ER`` record's
Minimum Altitude, Maximum Altitude, Route Distance From and Outbound Course
all describe the segment FROM the record's fix TO the next fix in sequence
order -- not the leg that ends at it. Settled from two FAA sources, cycle
2611 (2026-10-29): (1) FAA NASR ``AWY_SEG_ALT.csv`` publishes the MEA per
named from/to segment, and on V27 it gives KWANG->GOLET 4,000 and
GOLET->GVO 6,400 -- the values on the KWANG and GOLET rows of FAACIFP18
(the GOLET row's 18.7 nm route distance is GOLET->GVO too). (2) Across all
1,244 airways in FAACIFP18 the first record always carries a Minimum
Altitude and the end-of-route record (description code ``E``) never does:
the last fix starts no segment. The ARINC 424 field text itself (5.30) is
not public and was not consulted. So the MEA of the leg between two
adjacent fixes is on the row with the LOWER ``seq`` of the pair, in either
direction of travel. Before AER-5267 ``expand`` took it from the row of the
fix that ends the leg in travel order, which put every airway MEA one leg
off: flying V27 GVO->GOLET->KWANG published GOLET ``+6000`` (record 6,400,
over the Santa Ynez range) and KWANG ``+6400`` (record 4,000).

Reverse-direction MEA (RS6, AER-5469). The record's second Minimum
Altitude (cols 89-93) is the MEA for travel AGAINST sequence order where it
differs: 639 FAACIFP18 rows in cycle 2611, e.g. V1 INLET->PLANN is 2,100
north-east bound, 5,000 south-west bound in both CIFP and NASR. The pack
carries it as ``airway_legs.min_alt2_ft`` (makerplane-data#193, AER-5460),
NULL where the record leaves it blank, in which case ``min_alt_ft`` applies
both ways. The column is additive (``schema_version`` stays 3), so packs
built before it lack it entirely: :class:`AirwayGraph` probes
``PRAGMA table_info`` once and, when it is absent, backward travel uses the
forward MEA as before. V27 has no second MEA. The Direction Restriction convention (see
:meth:`AirwayGraph._resolve_segment`) is likewise unverified: FAACIFP18
codes no direction restriction on any airway, so the data cannot settle it.

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
    # MEA against seq order (RS6); None = blank or an old-shape pack, so
    # min_alt_ft applies both ways.
    min_alt2_ft: int | None = None

    def mea(self, backward: bool) -> int | None:
        """MEA of the leg this row starts, flown forward (ascending seq) or
        *backward*."""
        if backward and self.min_alt2_ft is not None:
            return self.min_alt2_ft
        return self.min_alt_ft


#: Pack ``fix_type`` -> ``model.Waypoint.type``. Anything not listed
#: (``waypoint``, ``runway``, blank) is a plain ``fix``.
_PACK_FIX_TYPES = {"vor": "vor", "ndb": "ndb", "airport": "airport"}


def _norm(ident: str) -> str:
    return (ident or "").strip().upper()


class AirwayGraph:
    """Lookup + expansion service over one ``procedures`` pack's airway
    tables. One instance per pack; safe to hold for the process lifetime."""

    def __init__(self, procedures_db_path: str | Path | None = None):
        self._path = Path(procedures_db_path) if procedures_db_path else None
        self._con: sqlite3.Connection | None = None
        self._has_min_alt2 = False
        if self._path is None or not self._path.is_file():
            log.info("AirwayGraph: %s not found -- airway lookup disabled",
                      self._path)
            return
        con = None
        try:
            con = sqlite3.connect(str(self._path), check_same_thread=False)
            con.row_factory = sqlite3.Row
            con.execute("SELECT 1 FROM airways LIMIT 1")
            cols = {r["name"] for r in con.execute("PRAGMA table_info(airway_legs)")}
            self._has_min_alt2 = "min_alt2_ft" in cols
            self._con = con
        except Exception as e:
            log.warning("AirwayGraph: cannot open %s: %s", self._path, e)
            self._con = None
            if con is not None:
                con.close()

    @property
    def ready(self) -> bool:
        return self._con is not None

    def close(self) -> None:
        """Release the underlying connection. Not needed for the one
        process-lifetime instance production holds (interpreter exit reclaims
        it), but callers that construct short-lived instances -- tests doing
        it once per case being the case in point -- should call this rather
        than let it ride on the cyclic GC: sqlite3's per-connection prepared-
        statement cache holds a reference back to the connection, so a
        connection that has executed any query is part of a reference cycle
        and cannot be reclaimed by refcounting alone. ``close()`` is
        idempotent and safe on an already-closed or never-opened instance."""
        if self._con is not None:
            self._con.close()
            self._con = None

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
            "al.min_alt_ft, al.max_alt_ft, al.direction, "
            + ("al.min_alt2_ft " if self._has_min_alt2 else "NULL AS min_alt2_ft ") +
            "FROM airway_legs al JOIN airways a ON a.id = al.airway_id "
            "WHERE a.ident = ? ORDER BY al.seq", (norm,)).fetchall()
        return [AirwayLeg(seq=r["seq"], fix_id=r["fix_id"],
                           lat=r["fix_lat"], lon=r["fix_lon"],
                           fix_type=r["fix_type"],
                           min_alt_ft=r["min_alt_ft"], max_alt_ft=r["max_alt_ft"],
                           direction=(r["direction"] or None),
                           min_alt2_ft=r["min_alt2_ft"])
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
        # The MEA of a leg is coded on the row of the fix that STARTS it in
        # published (ascending seq) order -- the lower seq of the pair, in
        # either direction of travel; flown backward, that row's second MEA
        # applies where it has one (module docstring).
        backward = segment[0].seq > segment[-1].seq
        out = []
        for n, leg in enumerate(segment):
            mea = None
            if n > 0:
                mea = min(segment[n - 1], leg, key=lambda r: r.seq).mea(backward)
            out.append(model.Waypoint(id=leg.fix_id,
                                       type=_PACK_FIX_TYPES.get(leg.fix_type or "", "fix"),
                                       lat=leg.lat, lon=leg.lon,
                                       alt=f"+{int(mea)}" if mea else ""))
        return out

    def cycle(self, ident: str) -> str | None:
        """The AIRAC cycle *ident* was built from (``airways.cycle``), or
        ``None`` if not ready or unknown. A stored route compares this with
        the cycle it saved to decide whether to re-expand (RS2)."""
        if not self.ready:
            return None
        row = self._con.execute("SELECT cycle FROM airways WHERE ident = ? LIMIT 1",
                                 (_norm(ident),)).fetchone()
        return None if row is None else (row["cycle"] or None)

    def altitude_range(self, ident: str, entry_fix_id: str,
                        exit_fix_id: str) -> tuple[int | None, int | None]:
        """``(min_alt_ft, max_alt_ft)`` enforceable over the segment of
        *ident* between *entry_fix_id* and *exit_fix_id* -- the highest
        published leg minimum (the MEA a pilot must be at or above for the
        whole segment) and the lowest published leg maximum, each leg's
        minimum taken for the direction of travel. Either may be
        ``None`` if the pack carries no restriction. Same errors as
        :meth:`expand`. The caller (PA6/PA9) compares this against the
        planned altitude and states the actual figure in the warning --
        this method only enforces direction, per brief section 3.4."""
        segment = self._resolve_segment(ident, entry_fix_id, exit_fix_id)
        # Each row describes the leg it starts (module docstring), so the
        # highest-seq fix of the segment contributes nothing: its row is the
        # leg beyond the exit (or the entry, flying backward).
        backward = segment[0].seq > segment[-1].seq
        flown = sorted(segment, key=lambda r: r.seq)[:-1]
        mins = [m for m in (leg.mea(backward) for leg in flown) if m is not None]
        maxs = [leg.max_alt_ft for leg in flown if leg.max_alt_ft is not None]
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

        # Direction Restriction (ARINC 424 5.4) is read here as coded on the
        # row of the fix that TERMINATES a leg -- the opposite of the row's
        # altitudes (module docstring), and unverified: FAACIFP18 codes no
        # direction restriction, so no real row can settle it. Read so, it
        # describes the segment from the previous seq to this one: "F" = forward (ascending seq)
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
