"""Safety advisories from status.json (BACKLOG L5, AER-5152).

Guards: the version rule matches the makerplane-data reference
(``packtools/advisories.py::software_match``; the table is its
``test_software_range`` verbatim); an unknown ``software: pyefis`` target is
settled against the running version, and one that settles to "no" drops the
advisory only when nothing else could still apply; unknown is never read as
"does not apply"; an off, absent or malformed block shows nothing; the feed
age line stays quiet until the last verified fetch is a cycle old."""

import datetime as dt

import pytest

import pyefis
from pyefis import advisories as adv

RANGE = {"software": "pyefis", "introduced": "2.1.0", "fixed": "2.1.3"}


@pytest.mark.parametrize("version,want", [
    ("2.0.9", adv.NO), ("2.1", adv.YES), ("2.1.0", adv.YES),
    ("2.1.0rc1", adv.YES),        # a pre-release of the introducing release
    ("2.1.2", adv.YES), ("2.1.3rc1", adv.YES),   # not yet the fixed release
    ("2.1.3.dev0", adv.YES), ("2.1.3", adv.NO), ("2.1.3+g1a2b", adv.NO),
    ("2.2", adv.NO), ("garbage", adv.UNKNOWN), (None, adv.UNKNOWN),
])
def test_software_range_matches_the_reference_table(version, want):
    assert adv.software_match(RANGE, version) == want


def test_open_ended_ranges_and_exact_versions():
    assert adv.software_match({"software": "x", "fixed": "1.0"}, "0.1") == adv.YES
    assert adv.software_match({"software": "x", "introduced": "1.0"}, "9.9") == adv.YES
    assert adv.software_match({"software": "x"}, "0.0.1") == adv.YES
    t = {"software": "x", "versions": ["1.2.0"]}
    assert adv.software_match(t, "1.2") == adv.YES
    assert adv.software_match(t, "1.2.1") == adv.NO


def _entry(**kw):
    e = {"id": "MPA-2026-001", "issued": "2026-12-01", "severity": "warning",
         "title": "Altitude tape can freeze", "description": "d", "action": "Update.",
         "applies": "unknown",
         "affects": [dict(RANGE, result="unknown")]}
    e.update(kw)
    return e


def _block(*entries, **kw):
    b = {"enabled": True, "sequence": 3, "generated": "2026-12-01T00:00:00Z",
         "checked": "2026-12-02T09:15:03Z", "error": None, "active": list(entries)}
    b.update(kw)
    return b


def test_unknown_pyefis_target_inside_the_range_applies():
    [a] = adv.resolve(_block(_entry()), "2.1.2")
    assert a["applies"] == adv.YES
    assert a["affects"][0]["result"] == adv.YES


def test_unknown_pyefis_target_outside_the_range_drops_the_advisory():
    assert adv.resolve(_block(_entry()), "2.1.3") == []


def test_default_version_is_the_running_pyefis(monkeypatch):
    monkeypatch.setattr(pyefis, "__version__", "2.1.1")
    assert adv.resolve(_block(_entry()))[0]["applies"] == adv.YES
    monkeypatch.setattr(pyefis, "__version__", "2.2.1")
    assert adv.resolve(_block(_entry())) == []


def test_another_unknown_target_keeps_it_unknown():
    e = _entry(affects=[dict(RANGE, result="unknown"),
                        {"software": "pyefis-gauges", "fixed": "1.0", "result": "unknown"}])
    [a] = adv.resolve(_block(e), "2.2.1")
    assert a["applies"] == adv.UNKNOWN
    assert adv.unknown_components(a) == ["pyefis-gauges"]


def test_a_pack_hit_still_applies_after_pyefis_settles_no():
    e = _entry(applies="yes", affects=[
        dict(RANGE, result="unknown"),
        {"pack": "obstacles-conus", "cycles": ["260611"], "result": "yes"}])
    [a] = adv.resolve(_block(e), "2.2.1")
    assert a["applies"] == adv.YES


def test_unknown_version_never_reads_as_not_applying():
    [a] = adv.resolve(_block(_entry()), "dev-build")
    assert a["applies"] == adv.UNKNOWN


def test_malformed_pyefis_target_is_left_unknown_not_guessed():
    bad = {"software": "pyefis", "introduced": "2.1", "fixed": "2.0", "result": "unknown"}
    [a] = adv.resolve(_block(_entry(affects=[bad])), "2.2.1")
    assert a["applies"] == adv.UNKNOWN


def test_an_entry_the_updater_settled_is_left_alone():
    e = _entry(applies="yes", affects=[dict(RANGE, result="yes")])
    [a] = adv.resolve(_block(e), "2.2.1")
    assert a["applies"] == adv.YES and a["affects"][0]["result"] == adv.YES


def test_order_is_yes_first_then_most_severe():
    out = adv.resolve(_block(
        _entry(id="MPA-2026-003", severity="advisory", applies="yes",
               affects=[{"pack": "p", "cycles": ["1"], "result": "yes"}]),
        _entry(id="MPA-2026-002", severity="warning",
               affects=[{"pack": "p", "cycles": ["1"], "result": "unknown"}]),
        _entry(id="MPA-2026-001", severity="caution", applies="yes",
               affects=[{"pack": "p", "cycles": ["1"], "result": "yes"}]),
    ), "2.2.1")
    assert [a["id"] for a in out] == ["MPA-2026-001", "MPA-2026-003", "MPA-2026-002"]


def test_unrecognised_severity_shows_as_warning():
    [a] = adv.resolve(_block(_entry(severity="urgent")), "2.1.1")
    assert a["severity"] == "warning"


@pytest.mark.parametrize("block", [
    None, {"enabled": False}, {}, "nope", {"enabled": "yes", "active": [_entry()]},
])
def test_off_absent_or_malformed_block_resolves_to_none(block):
    assert adv.resolve(block, "2.1.1") is None


def test_malformed_active_entries_never_raise():
    assert adv.resolve(_block("x", None, {"affects": "x"}), "2.1.1") == [
        {"affects": [], "severity": "warning", "applies": "unknown"}]
    assert adv.resolve(dict(_block(), active="x"), "2.1.1") == []


NOW = dt.datetime(2026, 12, 10, tzinfo=dt.timezone.utc)


def test_feed_health_is_silent_while_the_feed_is_fresh_even_after_a_failure():
    assert adv.feed_health(_block(), NOW) is None
    assert adv.feed_health(_block(error="network unreachable"), NOW) is None


def test_feed_health_reports_a_stale_feed_with_the_last_failure():
    b = _block(checked="2026-11-01T00:00:00Z", error="signature did not verify")
    assert adv.feed_health(b, NOW) == (
        "Safety advisories last verified 2026-11-01 (39 days ago). "
        "Last check: signature did not verify.")
    assert adv.feed_health(dict(b, error=None), NOW) == (
        "Safety advisories last verified 2026-11-01 (39 days ago).")


def test_feed_health_reports_no_verified_feed_yet():
    b = _block(checked=None, error="no verified advisory feed yet")
    assert adv.feed_health(b, NOW) == (
        "Safety advisories: no verified feed on this device yet.")
    assert adv.feed_health(dict(b, error="signature did not verify"), NOW) == (
        "Safety advisories: no verified feed on this device yet. "
        "Last check: signature did not verify.")


def test_feed_health_off_is_silent():
    assert adv.feed_health({"enabled": False}, NOW) is None
    assert adv.feed_health(None, NOW) is None
