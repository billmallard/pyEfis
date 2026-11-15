#  SPDX-License-Identifier: GPL-2.0-or-later
"""``ProcedureIndex`` lookup service over the ``procedures`` pack's
``procedures`` / ``transitions`` / ``legs`` tables (PA5, billmallard/pyEfis#236,
AER-1604).

See ``makerplane/briefs/procedures_and_airways_plan.md`` section 3.3. The
pack is built by ``makerplane-data`` PA1 (AER-1600):
``procedures(id, airport, kind, ident, runway, approach_type, rnp, cycle)``
+ ``transitions(id, proc_id, role, ident)`` + ``legs(transition_id, seq,
path_term, fix_id, fix_lat, fix_lon, fix_type, recd_navaid, theta, rho,
course, dist_nm, time_min, alt_desc, alt1_ft, alt2_ft, speed_kt, turn_dir,
rnp, flags, centre_fix, centre_lat, centre_lon, arc_radius_nm)`` with
indexes ``idx_proc_airport(airport, kind)``, ``idx_trans_proc(proc_id)`` and
``idx_legs_trans(transition_id, seq)``. Every query here is shaped to hit
one of those three indexes -- none of them is a table scan.

``kind`` is one of ``sid`` | ``star`` | ``approach``. ``transitions.role``
is one of ``enroute`` | ``runway`` | ``common`` (``makerplane-data``
``arinc424.transition_role`` -- a SID/STAR's runway-specific legs and an
approach/SID/STAR's shared legs land on ``runway``/``common`` transitions;
there is no separate ``missed`` role, the missed-approach segment is legs
within a transition flagged in ``legs.flags``, whose bit encoding belongs to
the leg model (PA3/PA4), not this lookup layer -- deliberately left as an
opaque int here, same reasoning as ``airways.py``'s ``altitude_range``
leaving per-leg constraint *enforcement* to the caller).

This is a lookup and query service only -- it does not assemble a
transition's legs into a flyable route (that needs the PA3 leg model and
belongs to PA7/PA9) and it does not enforce guardrail 1 (whole-procedure
rejection on an unsupported leg type -- that is the engine's job, PA4).

Construction never raises: a missing or unreadable pack just leaves
``ready`` False and every query answers as if the procedures table were
empty -- mirrors ``airways.py`` ``AirwayGraph`` and ``ai/obstacle_db.py``
``ObstacleDB`` (CLAUDE.md "construct-never-raises database loaders"). An
expired pack (see ``data_status``/CAP-116) still opens and answers queries
normally -- currency is annunciated, never enforced here (brief guardrail 3
-- pyEfis/CLAUDE.md).

Qt-free: nothing here may import PyQt6.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

PROCEDURE_KINDS = frozenset({"sid", "star", "approach"})
TRANSITION_ROLES = frozenset({"enroute", "runway", "common"})


def _norm(ident: str | None) -> str:
    return (ident or "").strip().upper()


def _norm_runway(runway: str | None) -> str:
    """Normalise a runway designator to the FAA 2-digit-number form ("7L" ->
    "07L", "25" -> "25"). Matches how both ``procedures.runway`` (approaches)
    and a SID/STAR's ``RWnn[L|R|C]`` runway-transition ident are coded."""
    norm = _norm(runway).removeprefix("RW")
    if len(norm) >= 1 and norm[0].isdigit() and (len(norm) == 1 or not norm[1].isdigit()):
        norm = "0" + norm
    return norm


@dataclass
class Procedure:
    id: int
    airport: str
    kind: str              # sid | star | approach
    ident: str
    runway: str | None      # approach only -- e.g. "07L"
    approach_type: str | None
    rnp: float | None
    cycle: str


@dataclass
class Transition:
    id: int
    proc_id: int
    role: str               # enroute | runway | common
    ident: str | None


@dataclass
class ProcedureLeg:
    seq: int
    path_term: str
    fix_id: str | None
    lat: float | None
    lon: float | None
    fix_type: str | None
    recd_navaid: str | None
    theta: float | None
    rho: float | None
    course: float | None
    dist_nm: float | None
    time_min: float | None
    alt_desc: str | None
    alt1_ft: int | None
    alt2_ft: int | None
    speed_kt: int | None
    turn_dir: str | None
    rnp: float | None
    flags: int
    centre_fix: str | None
    centre_lat: float | None
    centre_lon: float | None
    arc_radius_nm: float | None


class ProcedureIndex:
    """Lookup + query service over one ``procedures`` pack. One instance per
    pack; safe to hold for the process lifetime."""

    def __init__(self, procedures_db_path: str | Path | None = None):
        self._path = Path(procedures_db_path) if procedures_db_path else None
        self._con: sqlite3.Connection | None = None
        if self._path is None or not self._path.is_file():
            log.info("ProcedureIndex: %s not found -- procedure lookup disabled",
                      self._path)
            return
        try:
            con = sqlite3.connect(str(self._path), check_same_thread=False)
            con.row_factory = sqlite3.Row
            con.execute("SELECT 1 FROM procedures LIMIT 1")
            self._con = con
        except Exception as e:
            log.warning("ProcedureIndex: cannot open %s: %s", self._path, e)
            self._con = None

    @property
    def ready(self) -> bool:
        return self._con is not None

    # ------------------------------------------------------------------
    # Procedures (by airport, kind, runway)
    # ------------------------------------------------------------------
    def procedures_at(self, airport: str, kind: str | None = None,
                       runway: str | None = None) -> list[Procedure]:
        """Every procedure at *airport*, optionally filtered by *kind*
        (``sid``/``star``/``approach``) and/or *runway* -- ordered by
        ident. Hits ``idx_proc_airport``. For an approach, *runway* matches
        ``procedures.runway`` directly (a circling approach with no runway
        of its own is excluded by a runway filter). For a SID/STAR,
        *runway* matches against that procedure's ``runway``-role
        transition idents instead (an extra, per-procedure query -- the
        per-airport candidate count is small enough that this is not a
        table scan in practice). Empty if not ready or *airport* has none."""
        if not self.ready:
            return []
        airport_norm = _norm(airport)
        sql = "SELECT * FROM procedures WHERE airport = ?"
        params: list = [airport_norm]
        if kind is not None:
            sql += " AND kind = ?"
            params.append(_norm(kind).lower())
        sql += " ORDER BY ident"
        rows = self._con.execute(sql, params).fetchall()
        procs = [self._to_procedure(r) for r in rows]
        if runway is None:
            return procs
        runway_norm = _norm_runway(runway)
        out = []
        for p in procs:
            if p.kind == "approach":
                if p.runway and _norm_runway(p.runway) == runway_norm:
                    out.append(p)
            elif self._has_runway_transition(p.id, runway_norm):
                out.append(p)
        return out

    def find(self, airport: str, kind: str, ident: str) -> Procedure | None:
        """Exact-ident lookup, e.g. resolving a PROC-page selection back to
        its row. ``None`` if not ready or unknown."""
        if not self.ready:
            return None
        row = self._con.execute(
            "SELECT * FROM procedures WHERE airport = ? AND kind = ? AND ident = ?",
            (_norm(airport), _norm(kind).lower(), _norm(ident))).fetchone()
        return self._to_procedure(row) if row else None

    def runways_at(self, airport: str, kind: str = "approach") -> list[str]:
        """Sorted distinct runway designators serving *kind* procedures at
        *airport* -- for a SID/STAR this is derived from ``runway``-role
        transition idents (approaches carry it directly on the row).
        Circling-only approaches contribute nothing. Empty if not ready."""
        if not self.ready:
            return []
        kind_norm = _norm(kind).lower()
        if kind_norm == "approach":
            rows = self._con.execute(
                "SELECT DISTINCT runway FROM procedures "
                "WHERE airport = ? AND kind = 'approach' AND runway IS NOT NULL",
                (_norm(airport),)).fetchall()
            return sorted({r["runway"] for r in rows})
        rows = self._con.execute(
            "SELECT DISTINCT t.ident FROM transitions t "
            "JOIN procedures p ON p.id = t.proc_id "
            "WHERE p.airport = ? AND p.kind = ? AND t.role = 'runway'",
            (_norm(airport), kind_norm)).fetchall()
        out = set()
        for r in rows:
            rw = _norm_runway(r["ident"])
            if rw:
                out.add(rw)
        return sorted(out)

    def _has_runway_transition(self, proc_id: int, runway_norm: str) -> bool:
        rows = self._con.execute(
            "SELECT ident FROM transitions WHERE proc_id = ? AND role = 'runway'",
            (proc_id,)).fetchall()
        return any(_norm_runway(r["ident"]) == runway_norm for r in rows)

    # ------------------------------------------------------------------
    # Transitions
    # ------------------------------------------------------------------
    def transitions_for(self, proc_id: int, role: str | None = None) -> list[Transition]:
        """Every transition of *proc_id*, optionally filtered by *role*
        (``enroute``/``runway``/``common``) -- ordered by id (published
        order). Hits ``idx_trans_proc``. Empty if not ready or *proc_id*
        is unknown."""
        if not self.ready:
            return []
        sql = "SELECT * FROM transitions WHERE proc_id = ?"
        params: list = [proc_id]
        if role is not None:
            sql += " AND role = ?"
            params.append(_norm(role).lower())
        sql += " ORDER BY id"
        rows = self._con.execute(sql, params).fetchall()
        return [self._to_transition(r) for r in rows]

    # ------------------------------------------------------------------
    # Legs
    # ------------------------------------------------------------------
    def legs_for(self, transition_id: int) -> list[ProcedureLeg]:
        """Every leg of *transition_id*, in published (ascending ``seq``)
        order. Hits ``idx_legs_trans``. Empty if not ready or
        *transition_id* is unknown."""
        if not self.ready:
            return []
        rows = self._con.execute(
            "SELECT * FROM legs WHERE transition_id = ? ORDER BY seq",
            (transition_id,)).fetchall()
        return [self._to_leg(r) for r in rows]

    # ------------------------------------------------------------------
    # Row -> dataclass
    # ------------------------------------------------------------------
    @staticmethod
    def _to_procedure(row) -> Procedure:
        return Procedure(id=row["id"], airport=row["airport"], kind=row["kind"],
                          ident=row["ident"], runway=row["runway"],
                          approach_type=row["approach_type"], rnp=row["rnp"],
                          cycle=row["cycle"])

    @staticmethod
    def _to_transition(row) -> Transition:
        return Transition(id=row["id"], proc_id=row["proc_id"],
                           role=row["role"], ident=row["ident"])

    @staticmethod
    def _to_leg(row) -> ProcedureLeg:
        keys = row.keys()
        return ProcedureLeg(
            seq=row["seq"], path_term=row["path_term"], fix_id=row["fix_id"],
            lat=row["fix_lat"], lon=row["fix_lon"], fix_type=row["fix_type"],
            recd_navaid=row["recd_navaid"], theta=row["theta"], rho=row["rho"],
            course=row["course"], dist_nm=row["dist_nm"], time_min=row["time_min"],
            alt_desc=row["alt_desc"], alt1_ft=row["alt1_ft"], alt2_ft=row["alt2_ft"],
            speed_kt=row["speed_kt"], turn_dir=row["turn_dir"], rnp=row["rnp"],
            flags=row["flags"],
            centre_fix=(row["centre_fix"] if "centre_fix" in keys else None),
            centre_lat=(row["centre_lat"] if "centre_lat" in keys else None),
            centre_lon=(row["centre_lon"] if "centre_lon" in keys else None),
            arc_radius_nm=(row["arc_radius_nm"] if "arc_radius_nm" in keys else None))
