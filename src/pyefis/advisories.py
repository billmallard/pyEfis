#  Copyright (c) 2026 MakerPlane
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.

"""Safety advisories from the ``pyefis-data`` updater (BACKLOG L5).

The updater fetches, verifies and matches the signed advisory feed, and
writes the result into ``status.json`` as an ``advisories`` block beside
``packs`` (makerplane-data ``docs/advisories.md``, "status.json: what the
About/System screen reads"). pyEfis only reads that block: no network,
nothing written back.

One piece of the match is ours. The updater usually cannot see pyEfis's
version, so a ``"software": "pyefis"`` target reaches us as
``result: "unknown"``. ``resolve`` settles those against the running version
with the same rule as the reference, makerplane-data
``packtools/advisories.py::software_match``. Unknown never counts as "does
not apply".
"""

import datetime as _dt
import re

import pyefis

# Most severe first; the words of the feed schema (advisory-feed/1).
SEVERITIES = ("warning", "caution", "advisory")

YES, NO, UNKNOWN = "yes", "no", "unknown"

# The cached feed stays in force after a failed check, but past one 28-day
# navdata cycle without a verified fetch the screen says how old it is.
STALE_AFTER = _dt.timedelta(days=28)

_VERSION_RE = re.compile(r"^(\d+(?:\.\d+)*)(.*)$")
_TIME_FMT = "%Y-%m-%dT%H:%M:%SZ"
_NO_FEED_YET = "no verified advisory feed yet"


def parse_version(v):
    """``(release, final)`` or None when ``v`` has no leading numeric release.
    ``release`` drops trailing zeros (``2.1`` == ``2.1.0``); ``final`` is
    False for any suffix other than a ``+local`` label."""
    if not isinstance(v, str):
        return None
    m = _VERSION_RE.match(v.strip())
    if not m:
        return None
    release = [int(x) for x in m.group(1).split(".")]
    while len(release) > 1 and release[-1] == 0:
        release.pop()
    suffix = m.group(2)
    return tuple(release), suffix == "" or suffix.startswith("+")


def _bound_ok(v):
    p = parse_version(v)
    return p is not None and p[1] and v == v.strip()


def _target_ok(t):
    """The reference's validation of a software target, reduced to yes/no.
    A target it would refuse stays unknown rather than being guessed at."""
    if "versions" in t:
        vs = t["versions"]
        return ("introduced" not in t and "fixed" not in t and isinstance(vs, list)
                and bool(vs) and all(isinstance(v, str) and v for v in vs))
    for k in ("introduced", "fixed"):
        if k in t and not _bound_ok(t[k]):
            return False
    if "introduced" in t and "fixed" in t:
        return parse_version(t["introduced"]) < parse_version(t["fixed"])
    return True


def software_match(target, version):
    """YES / NO / UNKNOWN for one software target against a version (None =
    not known). Same rule and results as the makerplane-data reference."""
    if version is None:
        return UNKNOWN
    if "versions" in target:
        mine = parse_version(version)
        return YES if any(version == v or (mine and parse_version(v) == mine)
                          for v in target["versions"]) else NO
    mine = parse_version(version)
    if mine is None:
        return UNKNOWN
    lo, hi = target.get("introduced"), target.get("fixed")
    # A pre-release counts as inside the range at both ends.
    if lo is not None and mine[0] < parse_version(lo)[0]:
        return NO
    if hi is not None and mine >= (parse_version(hi)[0], True):
        return NO
    return YES


def _settle(entry, version):
    """A copy of one ``active`` entry with its unknown pyEfis targets matched
    against ``version``, or None when that shows it does not apply here."""
    affects = entry.get("affects") if isinstance(entry.get("affects"), list) else []
    targets, settled = [], False
    for t in affects:
        if (isinstance(t, dict) and t.get("software") == "pyefis"
                and "pack" not in t and t.get("result") == UNKNOWN and _target_ok(t)):
            t = dict(t, result=software_match(t, version))
            settled = settled or t["result"] != UNKNOWN
        targets.append(t)
    out = dict(entry, affects=targets)
    if not settled:
        return out                      # the updater's verdict stands
    results = {t.get("result") if isinstance(t, dict) else UNKNOWN for t in targets}
    if YES in results:
        out["applies"] = YES
    elif results == {NO} and all(isinstance(entry.get(k), str) and entry[k].strip()
                                 for k in ("id", "title", "action")):
        return None
    else:
        out["applies"] = UNKNOWN
    return out


def resolve(block, version=None):
    """The advisories to show, from a status.json ``advisories`` block.

    ``None`` when the block is absent, malformed or the channel is off;
    otherwise the ``active`` entries that still apply once pyEfis targets are
    matched against ``version`` (default: the running pyEfis), "yes" first,
    then most severe first. An entry with an unrecognised severity is shown
    as a warning, as the updater does. Never raises."""
    if not isinstance(block, dict) or block.get("enabled") is not True:
        return None
    version = pyefis.__version__ if version is None else version
    out = []
    active = block.get("active")
    for a in active if isinstance(active, list) else []:
        if not isinstance(a, dict):
            continue
        a = _settle(a, version)
        if a is None:
            continue
        if a.get("severity") not in SEVERITIES:
            a["severity"] = "warning"
        if a.get("applies") != YES:
            a["applies"] = UNKNOWN
        out.append(a)
    rank = {s: i for i, s in enumerate(SEVERITIES)}
    out.sort(key=lambda r: (r["applies"] != YES, rank[r["severity"]], str(r.get("id", ""))))
    return out


def unknown_components(entry):
    """Names of the targets the device could not match, for "may apply"."""
    names = []
    for t in entry.get("affects") or []:
        if isinstance(t, dict) and t.get("result") == UNKNOWN:
            name = t.get("software") or t.get("pack")
            if isinstance(name, str) and name and name not in names:
                names.append(name)
    return names


def feed_health(block, now=None):
    """One line about the feed's freshness, or None when there is nothing to
    say. Silent while the last verified fetch is within ``STALE_AFTER``, even
    if a later check failed: the cached feed is still in force, and a missed
    daily check is not news. Never raises."""
    if not isinstance(block, dict) or block.get("enabled") is not True:
        return None
    now = now or _dt.datetime.now(_dt.timezone.utc)
    error = block.get("error") if isinstance(block.get("error"), str) else None
    try:
        checked = _dt.datetime.strptime(block.get("checked"), _TIME_FMT).replace(
            tzinfo=_dt.timezone.utc)
    except (TypeError, ValueError):
        checked = None
    if checked is None:
        line = "Safety advisories: no verified feed on this device yet."
        # The updater's own text for this state says the same thing.
        return (f"{line} Last check: {error}."
                if error and error != _NO_FEED_YET else line)
    age = now - checked
    if age < STALE_AFTER:
        return None
    line = (f"Safety advisories last verified {checked:%Y-%m-%d} "
            f"({age.days} days ago).")
    return f"{line} Last check: {error}." if error else line
