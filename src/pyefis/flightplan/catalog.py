#  SPDX-License-Identifier: GPL-2.0-or-later
"""Stored-route catalog (FP4): ``<userdir>/routes/<slug>.json``. See
``makerplane/briefs/flight_plan_plan.md`` section 3.4 and
billmallard/pyEfis#183.

Slugs beginning ``managed_`` are reserved for configurator-delivered routes
(FP9) and are read-only on the device -- ``save``/``delete`` refuse them so a
device-authored edit can never collide with a cloud-authored one.

Routes are stored as ``mp-route/2`` (RS2, billmallard/pyEfis#305): segments,
each airway with the AIRAC cycle it was expanded from. ``load`` given an
``AirwayGraph`` re-expands any airway whose cycle differs from the installed
pack, and when the fix list changed it says so in ``FlightPlan.notices``
("V27 changed since this plan was saved") -- the plan always loads, and never
silently keeps flying fixes the current data no longer publishes (route
segments brief guardrail 3). ``mp-route/1`` files load as plain waypoints
and are rewritten as ``mp-route/2`` on their next save.

``invert()`` returns the inverted plan without writing it to the catalog,
matching the GNX guide's "Invert & Activate (a copy; the stored plan is
unchanged)" -- the caller decides whether to activate it, save it under a new
name via ``save``, or discard it. ``copy()`` is the catalog write: it persists
the duplicate under the new name immediately.

Qt-free: nothing here may import PyQt6.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .model import FlightPlan, FlightPlanError

MANAGED_PREFIX = "managed_"

_SLUG_RE = re.compile(r"[^A-Za-z0-9_-]+")


class CatalogError(ValueError):
    """A caller mistake -- a bad slug, a missing route, or a write refused
    because it targets a ``managed_`` (configurator-owned) slug."""


class ManagedRouteError(CatalogError):
    pass


@dataclass
class CatalogEntry:
    slug: str
    name: str
    total_nm: float
    count: int
    comment: str
    mtime: float


def slugify(name: str) -> str:
    slug = _SLUG_RE.sub("_", (name or "").strip()).strip("_")
    return slug or "route"


class Catalog:
    """Construct-never-raises: the directory need not exist yet (it is
    created on first ``save``)."""

    def __init__(self, directory):
        self._dir = Path(directory)

    def _path(self, slug: str) -> Path:
        if not slug or _SLUG_RE.search(slug):
            raise CatalogError(f"invalid catalog slug {slug!r}")
        return self._dir / f"{slug}.json"

    @staticmethod
    def _check_writable(slug: str) -> None:
        if slug.startswith(MANAGED_PREFIX):
            raise ManagedRouteError(
                f"{slug!r} is configurator-managed and read-only on this device")

    def list(self) -> list[CatalogEntry]:
        if not self._dir.is_dir():
            return []
        entries = []
        for path in sorted(self._dir.glob("*.json")):
            try:
                plan = FlightPlan.from_json(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                continue
            entries.append(CatalogEntry(
                slug=path.stem, name=plan.name or plan.default_name(),
                total_nm=plan.total_nm, count=plan.count, comment=plan.comment,
                mtime=path.stat().st_mtime))
        return entries

    def load(self, slug: str, graph=None) -> FlightPlan:
        """*graph*, an ``airways.AirwayGraph``, enables the AIRAC check:
        without it (or with no pack loaded) the stored legs are used as
        saved."""
        path = self._path(slug)
        if not path.is_file():
            raise CatalogError(f"no stored route {slug!r}")
        plan = FlightPlan.from_json(json.loads(path.read_text(encoding="utf-8")))
        if graph is not None and getattr(graph, "ready", False):
            refresh_airways(plan, graph)
        return plan

    def save(self, plan: FlightPlan, slug: str | None = None) -> str:
        """Save *plan* under *slug* (default: slugified plan name). Atomic:
        writes a ``.tmp`` file then ``os.replace``s it into place, so a
        failure between the two leaves any existing file untouched.
        Returns the slug written."""
        slug = slug or slugify(plan.name or plan.default_name())
        self._check_writable(slug)
        path = self._path(slug)
        self._dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc).isoformat()
        if not plan.created:
            plan.created = now
        plan.modified = now
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(plan.to_json(), indent=2), encoding="utf-8")
        os.replace(tmp, path)
        return slug

    def delete(self, slug: str) -> None:
        self._check_writable(slug)
        path = self._path(slug)
        if path.is_file():
            path.unlink()

    def copy(self, slug: str, new_name: str) -> str:
        """Load *slug*, rename to *new_name*, and save as a new catalog
        entry. The original entry is untouched."""
        plan = self.load(slug)
        plan.name = new_name
        plan.created = ""
        return self.save(plan, slugify(new_name))

    def invert(self, slug: str, graph=None) -> FlightPlan:
        """Return *slug*'s plan inverted (roles cleared). Not persisted --
        the stored plan is unchanged; save the result under a new slug to
        keep it. A plan with airways needs *graph* for the one-way check;
        a refusal raises ``FlightPlanError`` with the reason."""
        plan = self.load(slug, graph)
        inverted = plan.invert(graph)
        inverted.notices = list(plan.notices)
        return inverted


def refresh_airways(plan: FlightPlan, graph) -> None:
    """Re-expand every airway in *plan* whose stored AIRAC cycle differs from
    the one *graph* has installed, in place. A changed fix list is applied
    and noted; an airway that can no longer be expanded (withdrawn, a fix
    gone, now one-way against the route) keeps its stored legs and is
    noted, so the plan still loads and the pilot is told."""
    for k, seg in enumerate(plan.segments):
        if seg.kind != "airway":
            continue
        installed = graph.cycle(seg.ident)
        if installed is not None and installed == seg.cycle:
            continue
        before = [w.id for w in seg.legs]
        try:
            new = plan.change_exit(k, seg.exit, graph)
        except FlightPlanError as e:
            plan.notices.append(f"{seg.ident} could not be checked against the current "
                                f"data ({e}); flying the fixes saved with the plan")
            continue
        if [w.id for w in new.legs] != before:
            plan.notices.append(f"{seg.ident} changed since this plan was saved "
                                f"({' '.join(before)} -> {' '.join(w.id for w in new.legs)})")
