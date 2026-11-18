#  SPDX-License-Identifier: GPL-2.0-or-later
"""``PlateIndex`` over the ``plates`` packs: FAA d-TPP charts by airport, and
the approach plate for a CIFP approach (PA12, billmallard/pyEfis#241,
AER-1611).

The pack is built by ``makerplane-data`` PA11 (``docs/plates.md``,
``packtools/build/plates.py``): one sqlite pack per region, with
``plate_files(pdf_name, sha256, bytes, data)`` holding each distinct PDF
once, ``plates(id, state, city, apt_ident, icao_ident, military,
chart_code, chart_name, procuid, pdf_name, amdt_num, amdt_date, cycle)``
one row per catalog record, indexed ``idx_plates_airport(icao_ident,
chart_code)``, and ``plate_georef``. This module never reads
``plate_georef``: no ownship is drawn on any plate (brief guardrail 5), so
the georeferencing result has no consumer yet.

A pilot may install several regions, so the index opens every pack it is
given -- a pack file, or a directory searched for packs -- and answers from
all of them. An airport is in one region only; if two packs answer for it,
the first one opened wins.

Matching an approach to its plate. Nothing in the d-TPP metafile links a
chart to its CIFP procedure (``procuid`` is a d-TPP number, ``faanfd18`` is
never set on an IAP), so :func:`plate_for_approach` compares names: the
CIFP ident's type letter, runway and suffix (``I07``, ``R07-Y``, ``H16LZ``,
``RNV-F``) against each alternative in the chart name (``ILS OR LOC RWY
07``, ``RNAV (GPS) Y RWY 07``, ``RNAV (RNP) Z RWY 16L``, ``RNAV (GPS)-F``).
A match must agree on all three. Of several matches, a plain chart beats
one with a note (an ILS that also has ``(SA CAT I)``, ``(CAT II - III)``,
``COPTER`` or ``HI-`` versions), then the type the letter names beats a
looser reading (``D`` is ``VOR/DME`` before ``VOR``). If that still leaves
more than one, or none at all, there is no single answer and the caller
shows the airport's chart list instead.
The viewer never guesses which chart the pilot meant.

Construction never raises: a missing or unreadable pack leaves ``ready``
False and every query answers empty (CLAUDE.md "construct-never-raises
database loaders"). An expired chart still opens; currency is annunciated
by the viewer, never enforced here (brief guardrail 3).

Qt-free: nothing here may import PyQt6.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

#: The chart types the viewer lists, in the order it lists them: the airport
#: diagram first (CAP-207), then approaches, then the rest.
CHART_ORDER = ("APD", "IAP", "DP", "ODP", "STR", "MIN", "HOT", "LAH", "DAU")

# The chart-name approach types a CIFP approach type letter (ARINC 424
# 5.10, ``procedures.approach_type``) may appear under, best first. An ``L``
# (localizer) approach is the LOC half of an "ILS OR LOC" chart; a VOR with
# DME may be charted either way, and an ``R`` approach is now and then
# charted RNAV (RNP).
_FAMILIES = {
    "I": ("ILS",),
    "L": ("LOC", "LOC/DME"),
    "B": ("LOC BC", "LOC/DME BC"),
    "R": ("RNAV (GPS)", "GPS", "RNAV (RNP)"),
    "H": ("RNAV (RNP)",),
    "P": ("GPS", "RNAV (GPS)"),
    "V": ("VOR", "VOR/DME"),
    "D": ("VOR/DME", "VOR"),
    "S": ("VOR", "VOR/DME"),
    "N": ("NDB", "NDB/DME"),
    "Q": ("NDB/DME", "NDB"),
    "X": ("LDA", "LDA/DME"),
    "U": ("SDF",),
    "J": ("GLS",),
    "T": ("TACAN",),
}

# A circling approach's CIFP ident spells its type in three letters.
_CIRCLING_TYPES = {
    "RNV": "R", "GPS": "P", "VOR": "V", "VDM": "D", "NDB": "N", "NDM": "Q",
    "LOC": "L", "LDM": "L", "LBC": "B", "LDA": "X", "SDF": "U",
}

_RUNWAY_IDENT = re.compile(r"^([A-Z])(\d{2}[LRC]?)-?([A-Z])?$")
_CIRCLING_IDENT = re.compile(r"^([A-Z]{3})-([A-Z])$")
# What sets a chart apart from the plain one for the same approach: a
# category or converging note, a helicopter or high-altitude version. A
# noted chart matches, but loses to a plain one.
_NOTES = re.compile(r"\((?:SA )?CAT [^)]*\)|\(CONVERGING\)|^CONVERGING |^COPTER |^HI-")
_CHART_ALT = re.compile(r"^(?P<type>.+?)(?: (?P<suffix>[A-Z]))?(?: RWY (?P<rwy>\S+)|-(?P<circ>[A-Z]))?$")


def _norm(ident: str | None) -> str:
    return (ident or "").strip().upper()


def _norm_runway(runway: str | None) -> str:
    """``"7"``, ``"07"`` and ``"RW07"`` are one runway: ``"7"``."""
    return _norm(runway).removeprefix("RW").lstrip("0")


@dataclass(frozen=True)
class Plate:
    """One chart record. ``cycle`` is the AIRAC cycle the chart was
    published in."""

    icao_ident: str
    chart_code: str
    chart_name: str
    pdf_name: str
    amdt_num: str
    amdt_date: str
    cycle: str


@dataclass(frozen=True)
class ApproachKey:
    """What a chart name and a CIFP approach ident have in common: the type
    letter, the runway (``"7"``, ``"16L"``), the suffix (``"Y"``) and, for a
    circling approach, its letter (``"A"``) with ``runway=""``."""

    family: str
    runway: str
    suffix: str
    circling: str = ""


def approach_key(ident: str, approach_type: str | None = None) -> ApproachKey | None:
    """The :class:`ApproachKey` of a CIFP approach *ident* (``I07``,
    ``R07-Y``, ``H16LZ``, ``RNV-F``), or None for an ident this does not
    read. *approach_type* is the pack's letter, used when given."""
    ident = _norm(ident)
    m = _RUNWAY_IDENT.match(ident)
    if m:
        family = _norm(approach_type) or m.group(1)
        return ApproachKey(family, _norm_runway(m.group(2)), m.group(3) or "")
    m = _CIRCLING_IDENT.match(ident)
    if m:
        family = _norm(approach_type) or _CIRCLING_TYPES.get(m.group(1), "")
        return ApproachKey(family, "", "", m.group(2)) if family else None
    return None


def _strip_notes(chart_name: str) -> tuple[str, bool]:
    name = _norm(chart_name)
    stripped = _NOTES.sub("", name).strip()
    while stripped != name:
        name, stripped = stripped, _NOTES.sub("", stripped).strip()
    return stripped, stripped != _norm(chart_name)


def _runways(token: str | None) -> frozenset[str]:
    """``"30L/R"`` is runways 30L and 30R; ``"07"`` is runway 7."""
    rwy = _norm_runway(token)
    if "/" not in rwy:
        return frozenset({rwy})
    first, *rest = rwy.split("/")
    number = first.rstrip("LRC")
    return frozenset({first, *(number + side for side in rest)})


def chart_alternatives(chart_name: str) -> list[tuple[str, str, frozenset, str]]:
    """Each approach a chart name offers, ``(type, suffix, runways,
    circling)``, notes removed: ``ILS Y OR LOC Y RWY 23`` gives
    ``ILS``/``Y``/``{23}`` and ``LOC``/``Y``/``{23}``. The runway or
    circling letter is written once, at the end, and belongs to every
    alternative."""
    name, _noted = _strip_notes(chart_name)
    parsed = []
    for part in name.split(" OR "):
        m = _CHART_ALT.match(part.strip())
        if not m:
            return []
        rwy = m.group("rwy")
        parsed.append([m.group("type"), m.group("suffix") or "",
                       _runways(rwy) if rwy else frozenset({""}), m.group("circ") or ""])
    runways, circling = parsed[-1][2], parsed[-1][3]
    for alt in parsed[:-1]:
        if alt[2] == frozenset({""}):
            alt[2] = runways
        alt[3] = alt[3] or circling
    return [tuple(alt) for alt in parsed]


def chart_rank(chart_name: str, key: ApproachKey) -> tuple[int, int] | None:
    """How well *chart_name* fits *key*: ``(noted, type preference)``, lower
    is better, or None when it is not that approach's chart at all."""
    types = _FAMILIES.get(key.family, ())
    ranks = [types.index(t) for t, s, rw, c in chart_alternatives(chart_name)
             if t in types and s == key.suffix and key.runway in rw and c == key.circling]
    if not ranks:
        return None
    return int(_strip_notes(chart_name)[1]), min(ranks)


def chart_matches(chart_name: str, key: ApproachKey) -> bool:
    return chart_rank(chart_name, key) is not None


class PlateIndex:
    """Chart lookup over one or more ``plates`` packs. One instance per
    configured path; safe to hold for the process lifetime."""

    def __init__(self, plates_path: str | Path | None = None):
        self._cons: list[sqlite3.Connection] = []
        if not plates_path:
            return
        for pack in self._find_packs(Path(plates_path).expanduser()):
            con = None
            try:
                con = sqlite3.connect(f"file:{pack}?mode=ro", uri=True,
                                      check_same_thread=False)
                con.execute("SELECT 1 FROM plates LIMIT 1")
                con.execute("SELECT 1 FROM plate_files LIMIT 1")
                self._cons.append(con)
            except Exception as e:
                log.warning("PlateIndex: cannot open %s: %s", pack, e)
                if con is not None:
                    con.close()
        if not self._cons:
            log.info("PlateIndex: no plates pack at %s -- charts disabled", plates_path)

    @staticmethod
    def _find_packs(path: Path) -> list[Path]:
        if path.is_file():
            return [path]
        if not path.is_dir():
            return []
        # The device installs a pack as <kind>/<pack id>/current/<file>, so
        # three levels is deep enough for any layout the updater writes.
        found = []
        for pattern in ("*", "*/*", "*/*/*", "*/*/*/*"):
            found += [p for p in sorted(path.glob(pattern))
                      if p.is_file() and p.suffix in (".sqlite", ".pack")]
        return found

    @property
    def ready(self) -> bool:
        return bool(self._cons)

    def plates_at(self, airport: str) -> list[Plate]:
        """Every chart for *airport*, in :data:`CHART_ORDER` then catalog
        order. Empty if not ready or the airport has none. *airport* is the
        ICAO ident, or the FAA ident for an airport the metafile files with
        no ICAO ident (``W99``), as the CIFP does; the returned plates carry
        that ident."""
        apt = _norm(airport)
        for con in self._cons:
            rows = con.execute(
                "SELECT ?, chart_code, chart_name, pdf_name, amdt_num, amdt_date, cycle "
                "FROM plates WHERE icao_ident = ? OR (icao_ident = '' AND apt_ident = ?) "
                "ORDER BY id",
                (apt, apt, apt)).fetchall()
            if rows:
                plates = [Plate(*(v if v is not None else "" for v in r)) for r in rows]
                rank = {c: n for n, c in enumerate(CHART_ORDER)}
                return sorted(plates, key=lambda pl: rank.get(pl.chart_code, len(rank)))
        return []

    def airport_diagram(self, airport: str) -> Plate | None:
        return next((pl for pl in self.plates_at(airport) if pl.chart_code == "APD"), None)

    def plate_for_approach(self, airport: str, ident: str,
                           approach_type: str | None = None) -> Plate | None:
        """The one approach chart for CIFP approach *ident* at *airport*, or
        None when no chart, or more than one, matches (see the module
        docstring)."""
        key = approach_key(ident, approach_type)
        if key is None:
            return None
        ranked = [(rank, pl) for pl in self.plates_at(airport) if pl.chart_code == "IAP"
                  for rank in [chart_rank(pl.chart_name, key)] if rank is not None]
        if not ranked:
            return None
        best = min(rank for rank, _pl in ranked)
        winners = [pl for rank, pl in ranked if rank == best]
        return winners[0] if len(winners) == 1 else None

    def pdf_bytes(self, pdf_name: str) -> bytes | None:
        for con in self._cons:
            row = con.execute("SELECT data FROM plate_files WHERE pdf_name = ?",
                              (pdf_name,)).fetchone()
            if row is not None:
                return bytes(row[0])
        return None
