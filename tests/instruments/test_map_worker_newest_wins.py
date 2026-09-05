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
    """Common drill: job A's worker call blocks on an event so the test
    can post job B (simulating a gesture superseding an in-flight
    render) before releasing A. Returns the call log."""
    key_a, key_b = job_a[0], job_b[0]
    started_a = threading.Event()
    release_a = threading.Event()
    calls = []

    fake = make_fake(calls, key_a, started_a, release_a)
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
    return calls, key_a, key_b


def _assert_newest_wins_no_busy_loop(layer, publish_attr, key_getter,
                                     calls, key_a, key_b):
    # A must still publish, even though self._job moved on to B while
    # A was in flight.
    assert _wait_for(
        lambda: getattr(layer, publish_attr) is not None
        and key_getter(getattr(layer, publish_attr)) == key_a), (
        "superseded job A was never published")
    # The worker then renders/collects the newer job and its result
    # becomes the final published one.
    assert _wait_for(
        lambda: key_getter(getattr(layer, publish_attr)) == key_b), (
        "final published result does not carry the latest key")
    # No busy loop: once job == last (B done, nothing newer requested)
    # the worker must be sleeping, not re-invoking render/collect/query.
    time.sleep(0.15)
    assert [c[0] for c in calls] == [key_a, key_b], (
        "worker kept calling the work function after job == last")


def test_terrain_worker_publishes_superseded_then_latest():
    layer = TerrainLayer()
    job_a = ("A", 1.0, 2.0, 10.0, 400, 400, 200.0)
    job_b = ("B", 3.0, 4.0, 20.0, 400, 400, 200.0)

    def make_fake(calls, key_a, started_a, release_a):
        def fake_render(job):
            calls.append(job)
            if job[0] == key_a:
                started_a.set()
                assert release_a.wait(2.0), "job A never released"
            return (f"img-{job[0]}", (job[0], "meta"))
        return fake_render

    calls, key_a, key_b = _stage_two_jobs(layer, "_render", make_fake,
                                          job_a, job_b)
    _assert_newest_wins_no_busy_loop(
        layer, "_img", lambda published: published[1], calls, key_a, key_b)


def test_roads_worker_publishes_superseded_then_latest():
    layer = RoadsLayer()
    job_a = ("A", 1.0, 2.0, 10.0, 400, 400, 200.0)
    job_b = ("B", 3.0, 4.0, 20.0, 400, 400, 200.0)

    def make_fake(calls, key_a, started_a, release_a):
        def fake_render(job):
            calls.append(job)
            if job[0] == key_a:
                started_a.set()
                assert release_a.wait(2.0), "job A never released"
            return (f"img-{job[0]}", (job[0], "meta"))
        return fake_render

    calls, key_a, key_b = _stage_two_jobs(layer, "_render", make_fake,
                                          job_a, job_b)
    _assert_newest_wins_no_busy_loop(
        layer, "_img", lambda published: published[1], calls, key_a, key_b)


def test_airports_worker_publishes_superseded_then_latest():
    layer = AirportsLayer()
    job_a = ("A", 1.0, 2.0, 10.0)
    job_b = ("B", 3.0, 4.0, 20.0)

    def make_fake(calls, key_a, started_a, release_a):
        def fake_collect(job):
            calls.append(job)
            if job[0] == key_a:
                started_a.set()
                assert release_a.wait(2.0), "job A never released"
            return [f"airport-{job[0]}"]
        return fake_collect

    calls, key_a, key_b = _stage_two_jobs(layer, "_collect", make_fake,
                                          job_a, job_b)
    _assert_newest_wins_no_busy_loop(
        layer, "_snap", lambda published: published[0], calls, key_a, key_b)


def test_navaids_worker_publishes_superseded_then_latest():
    layer = NavaidsLayer()
    layer._path = ":memory:"
    job_a = ("A", 1.0, 2.0, 10.0)
    job_b = ("B", 3.0, 4.0, 20.0)

    def make_fake(calls, key_a, started_a, release_a):
        def fake_query(con, lat0, lon0, range_nm):
            key = "A" if (lat0, lon0, range_nm) == job_a[1:] else "B"
            calls.append((key, lat0, lon0, range_nm))
            if key == key_a:
                started_a.set()
                assert release_a.wait(2.0), "job A never released"
            return [f"navaid-{key}"]
        return fake_query

    calls, key_a, key_b = _stage_two_jobs(layer, "_query", make_fake,
                                          job_a, job_b)
    _assert_newest_wins_no_busy_loop(
        layer, "_snap", lambda published: published[0], calls, key_a, key_b)
