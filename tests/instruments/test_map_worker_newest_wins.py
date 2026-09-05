"""MP2: newest-wins publication in the four map worker loops
(briefs/map_gesture_perf_plan.md section 4, pyEfis #98).

Each worker loop used to discard a finished render/collect if
self._job had moved on to a newer key while the work was in flight
(the #89 same-key repost guard, over-applied to the publish step too).
paint() already blits a stale image by its own meta and re-requests on
key mismatch, so discarding was pure waste -- during a gesture it made
the display update only after the LAST superseded job happened to
finish, instead of showing every frame that completed along the way.
These tests drive the worker loops directly (bypassing the real
render/collect/query bodies) so they run fast and without GIS data."""

import threading
import time

from pyefis.instruments.map.layers.airports import AirportsLayer
from pyefis.instruments.map.layers.navaids import NavaidsLayer
from pyefis.instruments.map.layers.roads import RoadsLayer
from pyefis.instruments.map.layers.terrain import TerrainLayer


class _Owner:
    def update(self):
        pass


def _wait_for(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _stage_two_jobs(layer, patch_attr, make_fake, job_a, job_b):
    """Common drill: both job A's and job B's worker call block on their
    own event, so the test can pin exactly when each starts/finishes --
    without that, job B (posted the instant A is released) can race
    straight through to publish before a polling assertion ever
    observes A's stale-but-published result. Returns
    (calls, key_a, key_b, started_b, release_b) so the caller can drive
    the second half of the sequence."""
    key_a, key_b = job_a[0], job_b[0]
    started_a = threading.Event()
    release_a = threading.Event()
    started_b = threading.Event()
    release_b = threading.Event()
    calls = []

    fake = make_fake(calls, key_a, key_b, started_a, release_a,
                     started_b, release_b)
    setattr(layer, patch_attr, fake)
    layer._owner = _Owner()
    layer._job = job_a

    t = threading.Thread(target=layer._worker_loop,
                         name="test-" + getattr(layer, "id", "layer"),
                         daemon=True)
    t.start()

    assert started_a.wait(2.0), "worker never started job A"
    # Job B supersedes A while A is still being worked -- the in-flight
    # case the #89 guard used to mishandle at the publish step.
    with layer._lock:
        layer._job = job_b
    release_a.set()
    return calls, key_a, key_b, started_b, release_b


def _assert_newest_wins_no_busy_loop(layer, publish_attr, key_getter,
                                     calls, key_a, key_b, started_b,
                                     release_b):
    # The worker must reach job B's work call before it can have
    # published anything past A -- that ordering is guaranteed by the
    # loop being single-threaded, so once started_b fires, A's publish
    # (if any) has already happened; no polling race here.
    assert started_b.wait(2.0), "worker never started job B"
    published = getattr(layer, publish_attr)
    assert published is not None and key_getter(published) == key_a, (
        "superseded job A was never published")

    release_b.set()
    # The worker then finishes the newer job and its result becomes the
    # final published one.
    assert _wait_for(
        lambda: key_getter(getattr(layer, publish_attr)) == key_b), (
        "final published result does not carry the latest key")
    # No busy loop: once job == last (B done, nothing newer requested)
    # the worker must be sleeping, not re-invoking render/collect/query.
    time.sleep(0.15)
    assert [c[0] for c in calls] == [key_a, key_b], (
        "worker kept calling the work function after job == last")


def _blocking_fake(calls, key_a, key_b, started_a, release_a, started_b,
                   release_b, result_of):
    def fake(job):
        key = job[0]
        calls.append(job)
        started, release = ((started_a, release_a) if key == key_a
                            else (started_b, release_b))
        started.set()
        assert release.wait(2.0), f"job {key} never released"
        return result_of(job)
    return fake


def test_terrain_worker_publishes_superseded_then_latest():
    layer = TerrainLayer()
    job_a = ("A", 1.0, 2.0, 10.0, 400, 400, 200.0)
    job_b = ("B", 3.0, 4.0, 20.0, 400, 400, 200.0)

    def make_fake(*args):
        return _blocking_fake(*args,
                              result_of=lambda job: (f"img-{job[0]}",
                                                     (job[0], "meta")))

    calls, key_a, key_b, started_b, release_b = _stage_two_jobs(
        layer, "_render", make_fake, job_a, job_b)
    _assert_newest_wins_no_busy_loop(
        layer, "_img", lambda published: published[1], calls, key_a,
        key_b, started_b, release_b)


def test_roads_worker_publishes_superseded_then_latest():
    layer = RoadsLayer()
    job_a = ("A", 1.0, 2.0, 10.0, 400, 400, 200.0)
    job_b = ("B", 3.0, 4.0, 20.0, 400, 400, 200.0)

    def make_fake(*args):
        return _blocking_fake(*args,
                              result_of=lambda job: (f"img-{job[0]}",
                                                     (job[0], "meta")))

    calls, key_a, key_b, started_b, release_b = _stage_two_jobs(
        layer, "_render", make_fake, job_a, job_b)
    _assert_newest_wins_no_busy_loop(
        layer, "_img", lambda published: published[1], calls, key_a,
        key_b, started_b, release_b)


def test_airports_worker_publishes_superseded_then_latest():
    layer = AirportsLayer()
    job_a = ("A", 1.0, 2.0, 10.0)
    job_b = ("B", 3.0, 4.0, 20.0)

    def make_fake(*args):
        return _blocking_fake(*args,
                              result_of=lambda job: [f"airport-{job[0]}"])

    calls, key_a, key_b, started_b, release_b = _stage_two_jobs(
        layer, "_collect", make_fake, job_a, job_b)
    _assert_newest_wins_no_busy_loop(
        layer, "_snap", lambda published: published[0], calls, key_a,
        key_b, started_b, release_b)


def test_navaids_worker_publishes_superseded_then_latest():
    layer = NavaidsLayer()
    layer._path = ":memory:"
    job_a = ("A", 1.0, 2.0, 10.0)
    job_b = ("B", 3.0, 4.0, 20.0)

    started_a = threading.Event()
    release_a = threading.Event()
    started_b = threading.Event()
    release_b = threading.Event()
    calls = []

    def fake_query(con, lat0, lon0, range_nm):
        key = "A" if (lat0, lon0, range_nm) == job_a[1:] else "B"
        calls.append((key, lat0, lon0, range_nm))
        started, release = ((started_a, release_a) if key == "A"
                            else (started_b, release_b))
        started.set()
        assert release.wait(2.0), f"job {key} never released"
        return [f"navaid-{key}"]

    layer._query = fake_query
    layer._owner = _Owner()
    layer._job = job_a
    t = threading.Thread(target=layer._worker_loop, name="test-navaids",
                         daemon=True)
    t.start()

    assert started_a.wait(2.0), "worker never started job A"
    with layer._lock:
        layer._job = job_b
    release_a.set()

    _assert_newest_wins_no_busy_loop(
        layer, "_snap", lambda published: published[0], calls, "A", "B",
        started_b, release_b)
