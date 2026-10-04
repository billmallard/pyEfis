"""Tests for tools/capture_service.py (AER-2627, AER-2657).

Covers the behavior the move into the checkout exists to deliver: `/health`
reports the identity of the code this service runs, resolved from git via the
same `pyefis_rev.resolve_pyefis_rev()` svs_capture.py uses for its per-frame
sidecar -- not a deploy-time-written file that can go stale or report
"unknown" because a deploy step forgot to write it.

And the AER-2657 correction to it: this service is long-running, so resolving
that rev per REQUEST reports the checkout rather than the loaded code, and
lies for the whole window between a pull and the restart that picks it up.
`service_ref` is frozen at import, `checkout_ref` is live, and
`service_stale` says when a file this process loaded has changed on disk.
Those three are pinned below, including the stale window itself -- the point
of the change is a value that cannot be confidently wrong, so a test that
only ever sees a quiet checkout would not have caught the defect.

Also covers `build_argv`'s pure translation logic (argv construction, the
AER-676 unknown-field rejection it depends on) since that moved along with
the file and had no test coverage of its own before (it previously lived
outside any checkout this repo's test suite could reach).
"""
import base64
import errno
import fcntl
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]


def _load_capture_service(monkeypatch, tmp_path, source_dir=None, pyefis_root=None):
    token_file = tmp_path / ".capture-token"
    token_file.write_text("test-token\n")
    monkeypatch.setenv("CAPTURE_TOKEN_FILE", str(token_file))
    # Default the bench lock (AER-2658) into the test's own tmp dir: it is
    # read at import, and no test may touch the real /tmp/pyefis-bench.lock,
    # which on a bench is a live mutual exclusion between agents.
    monkeypatch.setenv(
        "CAPTURE_BENCH_LOCK",
        os.environ.get("CAPTURE_BENCH_LOCK", str(tmp_path / "pyefis-bench.lock")),
    )
    if pyefis_root is not None:
        monkeypatch.setenv("PYEFIS_ROOT", str(pyefis_root))
    source = (source_dir or (_ROOT / "tools")) / "capture_service.py"
    spec = importlib.util.spec_from_file_location("capture_service", source)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def capture_service(monkeypatch, tmp_path):
    return _load_capture_service(monkeypatch, tmp_path)


@contextmanager
def _serving(mod):
    """Run mod's handler on a loopback port and yield a /health fetcher."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), mod.Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def health():
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/health",
            headers={"Authorization": "Bearer test-token"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())

    try:
        yield health
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", *args],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


def _git_repo_with_one_commit(repo):
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "test")
    (repo / "tracked.txt").write_text("one\n")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-qm", "one")
    return _git(repo, "rev-parse", "--short", "HEAD")


def test_pyefis_root_self_locates_to_the_checkout(capture_service):
    # No PYEFIS_ROOT override was set -- it must resolve to the checkout
    # this file actually lives in, not a hardcoded bench path (AER-2627).
    assert capture_service.PYEFIS_ROOT == _ROOT
    assert (capture_service.PYEFIS_ROOT / capture_service.CAPTURE_TOOL).is_file()


def test_no_deploy_time_version_file_mechanism(capture_service):
    # The old sidecar-file mechanism this issue retires must actually be
    # gone, not just unused -- otherwise a later edit could silently revive
    # the stale-provenance path this move exists to close.
    assert not hasattr(capture_service, "CAPTURE_SERVICE_VERSION_FILE")
    assert not hasattr(capture_service, "_service_version")


def test_health_reports_a_real_sha_from_the_live_checkout(capture_service):
    from pyefis_rev import resolve_pyefis_rev

    live = resolve_pyefis_rev(capture_service.PYEFIS_ROOT)
    assert live != "unknown"  # this test runs inside a real git checkout

    with _serving(capture_service) as health:
        body = health()

    # The exact field name QA_AGENT_SPEC.md documents and
    # converge_map_gestures.py reads -- still resolved from git, no sidecar.
    assert body["service_ref"] == capture_service.SERVICE_REF
    assert body["checkout_ref"] == live
    # Nothing moved during this test, so the two agree and nothing is stale.
    assert body["service_ref"] == live
    assert body["service_stale"] is False


def test_service_ref_is_frozen_at_import_while_the_checkout_moves(monkeypatch, tmp_path):
    """The AER-2657 defect: a pull must not change what /health claims to run.

    Resolved per request, service_ref reported the new sha the instant
    bench-deploy.sh pulled -- while the process went on executing the old
    code until someone remembered `systemctl restart svs-capture.service`.
    """
    repo = tmp_path / "checkout"
    first = _git_repo_with_one_commit(repo)

    mod = _load_capture_service(monkeypatch, tmp_path, pyefis_root=repo)
    assert mod.SERVICE_REF == first

    # The pull lands: the checkout moves under a process that keeps running.
    (repo / "tracked.txt").write_text("two\n")
    _git(repo, "commit", "-qam", "two")
    second = _git(repo, "rev-parse", "--short", "HEAD")
    assert second != first

    with _serving(mod) as health:
        body = health()

    assert body["service_ref"] == first, "service_ref must describe the running code"
    assert body["checkout_ref"] == second, "checkout_ref must describe the disk"


def test_service_stale_flags_a_loaded_file_changing_on_disk(monkeypatch, tmp_path):
    tools = tmp_path / "tools"
    tools.mkdir()
    for name in ("capture_service.py", "pyefis_rev.py"):
        shutil.copy(_ROOT / "tools" / name, tools / name)

    mod = _load_capture_service(monkeypatch, tmp_path, source_dir=tools)
    with _serving(mod) as health:
        assert health()["service_stale"] is False

    # A pull rewrites the service's own source. The process is unaffected --
    # that is exactly the condition a caller has to be able to see.
    target = tools / "capture_service.py"
    target.write_text(target.read_text() + "\n# changed by the pull\n")

    with _serving(mod) as health:
        assert health()["service_stale"] is True


def test_service_stale_follows_pyefis_rev_too(monkeypatch, tmp_path):
    # pyefis_rev.py is imported at module scope, so a pull that moves only
    # that file also leaves this process running superseded code.
    tools = tmp_path / "tools"
    tools.mkdir()
    for name in ("capture_service.py", "pyefis_rev.py"):
        shutil.copy(_ROOT / "tools" / name, tools / name)

    mod = _load_capture_service(monkeypatch, tmp_path, source_dir=tools)
    target = tools / "pyefis_rev.py"
    target.write_text(target.read_text() + "\n# changed by the pull\n")

    assert mod.service_is_stale() is True


def test_service_files_excludes_the_per_request_tools(capture_service):
    # svs_capture.py and bench_map_gestures.py are spawned per request, so a
    # pull changes what renders with no restart. Listing them would turn
    # every renderer change into a false "restart due" (AER-2657 ruling).
    names = {p.name for p in capture_service.SERVICE_FILES}
    assert names == {"capture_service.py", "pyefis_rev.py"}


def test_unreadable_service_file_counts_as_stale(monkeypatch, tmp_path):
    tools = tmp_path / "tools"
    tools.mkdir()
    for name in ("capture_service.py", "pyefis_rev.py"):
        shutil.copy(_ROOT / "tools" / name, tools / name)

    mod = _load_capture_service(monkeypatch, tmp_path, source_dir=tools)
    (tools / "capture_service.py").unlink()
    # Safe direction: say a restart is due rather than imply the code is
    # current, and do not take /health down over metadata.
    assert mod.service_is_stale() is True


#: Stands in for tools/svs_capture.py: writes a frame and the `<out>.json`
#: sidecar next to it, the way the real one does, and nothing else.
_FAKE_CAPTURE = '''\
import hashlib, json, sys
out = sys.argv[sys.argv.index("--out") + 1]
png = b"\\x89PNG\\r\\n\\x1a\\nFAKE"
with open(out, "wb") as fh:
    fh.write(png)
with open(out + ".json", "w") as fh:
    json.dump({
        "pyefis_rev": "abc1234-dirty",
        "capture_mode": "windowed",
        "requested_size": [640, 400],
        "actual_size": [640, 400],
        "argv": " ".join(sys.argv[1:]),
        "sha256": hashlib.sha256(png).hexdigest(),
    }, fh)
'''


def _service_with_fake_capture(monkeypatch, tmp_path, body=_FAKE_CAPTURE):
    """Load the service pointed at a PYEFIS_ROOT whose svs_capture is a stub."""
    root = tmp_path / "root"
    (root / "tools").mkdir(parents=True)
    (root / "tools" / "svs_capture.py").write_text(body)
    monkeypatch.setenv("CAPTURE_PYTHON", sys.executable)
    return _load_capture_service(monkeypatch, tmp_path, pyefis_root=root), root


@contextmanager
def _capturing(mod):
    """Run mod's handler on loopback and yield a POST /capture fetcher."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), mod.Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def capture(**scenario):
        scenario.setdefault("lat", 34.4275)
        scenario.setdefault("lon", -119.8546)
        scenario.setdefault("alt", 500)
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/capture",
            data=json.dumps(scenario).encode(),
            headers={"Authorization": "Bearer test-token",
                     "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read(), dict(resp.headers)

    try:
        yield capture
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_capture_response_names_the_rev_that_rendered_it(monkeypatch, tmp_path):
    # The AER-1675 defect: the service rendered into a tempfile, returned the
    # PNG bytes and unlinked it, so svs_capture.py's sidecar -- the only thing
    # naming the code that drew the frame -- never reached the caller. A frame
    # fetched over HTTP named nothing, which is the condition the issue opened
    # on, and it survived the sidecar itself shipping.
    mod, _ = _service_with_fake_capture(monkeypatch, tmp_path)
    with _capturing(mod) as capture:
        png, headers = capture()

    assert png.startswith(b"\x89PNG")
    assert headers["X-Capture-Pyefis-Rev"] == "abc1234-dirty"


def test_capture_manifest_header_ties_the_sidecar_to_these_bytes(monkeypatch, tmp_path):
    # The sha256 is why the whole sidecar rides along and not just the rev: it
    # is what lets an archived frame be re-attributed later rather than taken
    # on the word of whoever filed it.
    mod, _ = _service_with_fake_capture(monkeypatch, tmp_path)
    with _capturing(mod) as capture:
        png, headers = capture()

    manifest = json.loads(
        base64.b64decode(headers["X-Capture-Manifest-Base64"]).decode()
    )
    assert manifest["sha256"] == hashlib.sha256(png).hexdigest()
    assert manifest["capture_mode"] == "windowed"
    assert manifest["requested_size"] == [640, 400]


def test_capture_also_names_the_services_own_loaded_rev(monkeypatch, tmp_path):
    # Two revs, because they answer different questions: svs_capture.py is
    # spawned per request off disk, this service runs what it imported. Both
    # on one response so the caller is not comparing a /capture against a
    # later /health and assuming nothing moved in between.
    mod, _ = _service_with_fake_capture(monkeypatch, tmp_path)
    with _capturing(mod) as capture:
        _, headers = capture()

    assert headers["X-Capture-Service-Ref"] == mod.SERVICE_REF


def test_capture_leaves_no_orphan_sidecar_in_tmp(monkeypatch, tmp_path):
    # 355 orphaned tmp*.png.json files had piled up in /tmp on the Beelink by
    # the time this was found -- the service unlinked the PNG and never the
    # sidecar named after it.
    mod, _ = _service_with_fake_capture(monkeypatch, tmp_path)
    tmpdir = tmp_path / "svc-tmp"
    tmpdir.mkdir()
    monkeypatch.setattr(mod.tempfile, "tempdir", str(tmpdir))
    with _capturing(mod) as capture:
        capture()

    assert list(tmpdir.iterdir()) == []


def test_capture_still_succeeds_when_the_sidecar_is_missing(monkeypatch, tmp_path):
    # Provenance is metadata on a capture, never a dependency of one (the same
    # rule resolve_pyefis_rev follows). An svs_capture.py too old to write a
    # sidecar costs the response its rev headers and nothing else -- the Pi's
    # checkout runs 43 commits behind the bench's, so version skew between the
    # two arms is the normal case, not a hypothetical.
    no_sidecar = (
        'import sys\n'
        'out = sys.argv[sys.argv.index("--out") + 1]\n'
        'open(out, "wb").write(b"\\x89PNG\\r\\n\\x1a\\nFAKE")\n'
    )
    mod, _ = _service_with_fake_capture(monkeypatch, tmp_path, body=no_sidecar)
    with _capturing(mod) as capture:
        png, headers = capture()

    assert png.startswith(b"\x89PNG")
    assert "X-Capture-Pyefis-Rev" not in headers
    assert "X-Capture-Manifest-Base64" not in headers
    # The service's own rev does not come from the sidecar, so it survives.
    assert headers["X-Capture-Service-Ref"] == mod.SERVICE_REF


def test_capture_survives_a_malformed_sidecar(monkeypatch, tmp_path):
    # Truncated JSON (a capture killed mid-write) must not 500 the response or
    # leave the half-written file behind for the next caller to inherit.
    bad_sidecar = (
        'import sys\n'
        'out = sys.argv[sys.argv.index("--out") + 1]\n'
        'open(out, "wb").write(b"\\x89PNG\\r\\n\\x1a\\nFAKE")\n'
        'open(out + ".json", "w").write("{\\"pyefis_rev\\": ")\n'
    )
    mod, _ = _service_with_fake_capture(monkeypatch, tmp_path, body=bad_sidecar)
    tmpdir = tmp_path / "svc-tmp"
    tmpdir.mkdir()
    monkeypatch.setattr(mod.tempfile, "tempdir", str(tmpdir))
    with _capturing(mod) as capture:
        png, headers = capture()

    assert png.startswith(b"\x89PNG")
    assert "X-Capture-Pyefis-Rev" not in headers
    assert list(tmpdir.iterdir()) == []


def test_capture_timing_out_takes_the_sidecar_too(monkeypatch, tmp_path):
    # The 504 path has to take the sidecar as well, and it is the path most
    # likely to strand one: svs_capture.py writes the frame and the sidecar
    # beside it and can still hang afterwards on GL teardown, so the handler
    # unlinks the PNG it knows about and the `.json` named after it survives.
    # Written because the line that does this was unpinned -- deleting
    # `take_manifest` from the timeout branch left all 19 other tests green,
    # which makes it exactly the line a later conflict resolution drops in
    # silence (it conflicts with AER-2658's two-lock restructure of this
    # same block).
    mod, _ = _service_with_fake_capture(monkeypatch, tmp_path)
    tmpdir = tmp_path / "svc-tmp"
    tmpdir.mkdir()
    monkeypatch.setattr(mod.tempfile, "tempdir", str(tmpdir))

    def hangs_after_writing_its_sidecar(argv, **kwargs):
        out = argv[argv.index("--out") + 1]
        Path(out).write_bytes(b"\x89PNG\r\n\x1a\nFAKE")
        Path(out + ".json").write_text(json.dumps({"pyefis_rev": "abc1234"}))
        raise subprocess.TimeoutExpired(argv, kwargs.get("timeout", 0))

    monkeypatch.setattr(mod.subprocess, "run", hangs_after_writing_its_sidecar)
    with _capturing(mod) as capture:
        with pytest.raises(urllib.error.HTTPError) as caught:
            capture()

    assert caught.value.code == 504
    assert list(tmpdir.iterdir()) == []


def test_take_manifest_removes_what_it_read(capture_service, tmp_path):
    out = tmp_path / "frame.png"
    sidecar = tmp_path / "frame.png.json"
    sidecar.write_text(json.dumps({"pyefis_rev": "deadbee"}))

    assert capture_service.take_manifest(str(out)) == {"pyefis_rev": "deadbee"}
    assert not sidecar.exists()
    # Second take finds nothing and says so rather than raising.
    assert capture_service.take_manifest(str(out)) is None


def test_build_argv_minimal_scenario(capture_service):
    argv = capture_service.build_argv(
        {"lat": 34.4275, "lon": -119.8546, "alt": 500.0}, "/tmp/out.png",
    )
    assert "--lat" in argv and "34.427500" in argv
    assert "--terrain-only" in argv  # default True per build_argv
    assert "--symbology-only" not in argv
    assert "--dof" in argv  # isolate defaults True


def test_build_argv_rejects_terrain_only_with_symbology_only(capture_service):
    with pytest.raises(ValueError):
        capture_service.build_argv(
            {"lat": 0, "lon": 0, "alt": 0, "terrain_only": True, "symbology_only": True},
            "/tmp/out.png",
        )


def test_highways_path_true_uses_configured_pack(capture_service):
    assert capture_service._highways_path({"highways": True}) == capture_service.HIGHWAYS


def test_highways_path_absent_is_empty(capture_service):
    assert capture_service._highways_path({}) == ""


# -- the bench run lock (AER-2658) --------------------------------------
#
# These endpoints spawn a renderer against a checkout that `bench-deploy.sh`
# rewrites, while holding /tmp/pyefis-bench.lock for its whole run. Before
# AER-2658 nothing in this path took that lock, so a deploy could pull and
# bounce pyefis.service mid-render. Every test below drives the real HTTP
# handler against a real flock on a tmp path -- the subprocess is faked, the
# locking is not, because the locking is the thing under test.


class _FakeRun:
    """Stands in for subprocess.run: writes the --out file, counts calls."""

    def __init__(self, exit_code=0, payload=b"\x89PNG-fake", raise_timeout=False,
                 sleep=0.0):
        self.exit_code = exit_code
        self.payload = payload
        self.raise_timeout = raise_timeout
        self.sleep = sleep
        self.calls = 0

    def __call__(self, argv, **kwargs):
        self.calls += 1
        if self.raise_timeout:
            raise subprocess.TimeoutExpired(argv, kwargs.get("timeout", 0))
        if self.sleep:
            time.sleep(self.sleep)
        out = argv[argv.index("--out") + 1]
        Path(out).write_bytes(self.payload)
        return subprocess.CompletedProcess(argv, self.exit_code, "", "")


def _fake_subprocess(mod, monkeypatch, fake):
    """Swap the loaded module's subprocess for a shim around `fake`."""
    import types
    monkeypatch.setattr(mod, "subprocess", types.SimpleNamespace(
        run=fake,
        TimeoutExpired=subprocess.TimeoutExpired,
        CompletedProcess=subprocess.CompletedProcess,
    ))
    return fake


@contextmanager
def _posting(mod):
    """Serve mod's handler on loopback; yield post(path, body) -> (code, hdrs, body)."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), mod.Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def post(path, body, timeout=60):
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}",
            data=json.dumps(body).encode(),
            headers={"Authorization": "Bearer test-token",
                     "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as err:
            return err.code, dict(err.headers), err.read()

    try:
        yield post
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


@contextmanager
def _holding(lock_path, holder=None):
    """Hold the bench lock the way bench-deploy.sh does: flock(2) on the file."""
    if holder is not None:
        Path(f"{lock_path}.owner").write_text(holder + "\n")
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o666)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        yield
    finally:
        os.close(fd)


def _is_free(lock_path):
    """True if the bench lock can be taken right now."""
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o666)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError as exc:
        assert exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN, errno.EACCES)
        return False
    finally:
        os.close(fd)


_SCENE = {"lat": 35.8, "lon": -78.8, "alt": 1500.0}


@pytest.fixture
def bench_lock_service(monkeypatch, tmp_path):
    """The service, its bench-lock path, and a fake renderer, all wired up."""
    lock = tmp_path / "pyefis-bench.lock"
    monkeypatch.setenv("CAPTURE_BENCH_LOCK", str(lock))
    mod = _load_capture_service(monkeypatch, tmp_path)
    assert mod.BENCH_LOCK == lock
    return mod, lock


def test_capture_waits_for_a_held_bench_lock_then_runs(bench_lock_service, monkeypatch):
    mod, lock = bench_lock_service
    fake = _fake_subprocess(mod, monkeypatch, _FakeRun())
    result = {}

    with _posting(mod) as post:
        with _holding(lock):
            thread = threading.Thread(
                target=lambda: result.update(zip(("code", "hdrs", "body"),
                                                 post("/capture", dict(_SCENE)))),
                daemon=True)
            thread.start()
            time.sleep(0.6)
            # The deploy still has the box: nothing may have been spawned.
            assert fake.calls == 0, "rendered while another tenant held the lock"
            assert not result
        thread.join(timeout=30)

    assert result["code"] == 200
    assert result["body"] == b"\x89PNG-fake"
    assert fake.calls == 1
    assert float(result["hdrs"]["X-Capture-Lock-Wait-Seconds"]) >= 0.5


def test_capture_503s_when_the_bench_stays_busy(monkeypatch, tmp_path):
    lock = tmp_path / "pyefis-bench.lock"
    monkeypatch.setenv("CAPTURE_BENCH_LOCK", str(lock))
    monkeypatch.setenv("CAPTURE_BENCH_LOCK_WAIT", "0.3")
    mod = _load_capture_service(monkeypatch, tmp_path)
    fake = _fake_subprocess(mod, monkeypatch, _FakeRun())

    with _posting(mod) as post, _holding(lock, holder="owner=QA issue=AER-9999 pid=1"):
        code, hdrs, body = post("/capture", dict(_SCENE))

    payload = json.loads(body)
    assert code == 503
    assert payload["error"] == "bench busy"
    assert payload["waited_seconds"] >= 0.3
    # Who has the box, read from the record bench-deploy.sh writes -- the same
    # courtesy its own "BENCH BUSY -- last recorded holder" line extends.
    assert "AER-9999" in payload["holder"]
    assert hdrs["Retry-After"] == "30"
    assert fake.calls == 0


def test_bench_lock_is_released_after_a_capture(bench_lock_service, monkeypatch):
    mod, lock = bench_lock_service
    _fake_subprocess(mod, monkeypatch, _FakeRun())
    with _posting(mod) as post:
        assert post("/capture", dict(_SCENE))[0] == 200
    assert _is_free(lock), "bench lock leaked after a successful capture"


def test_bench_lock_is_released_after_a_capture_times_out(bench_lock_service, monkeypatch):
    mod, lock = bench_lock_service
    _fake_subprocess(mod, monkeypatch, _FakeRun(raise_timeout=True))
    with _posting(mod) as post:
        code, _hdrs, body = post("/capture", dict(_SCENE))
    assert code == 504
    assert "lock_wait_seconds" in json.loads(body)
    # The path that leaks a lock is the one nobody exercises: a render that
    # never came back must not take the bench with it.
    assert _is_free(lock), "bench lock leaked after a capture timeout"


def test_bench_map_takes_the_same_lock(monkeypatch, tmp_path):
    lock = tmp_path / "pyefis-bench.lock"
    monkeypatch.setenv("CAPTURE_BENCH_LOCK", str(lock))
    monkeypatch.setenv("CAPTURE_BENCH_LOCK_WAIT", "0.2")
    mod = _load_capture_service(monkeypatch, tmp_path)
    fake = _fake_subprocess(mod, monkeypatch, _FakeRun(payload=b"{}"))

    with _posting(mod) as post, _holding(lock):
        code, _hdrs, body = post("/bench/map", {"scenario": "pan"})
    assert code == 503 and json.loads(body)["error"] == "bench busy"
    assert fake.calls == 0


def test_capture_seconds_excludes_the_bench_lock_wait(bench_lock_service, monkeypatch):
    """X-Capture-Seconds is the render; queueing is its own number.

    A perf oracle reads X-Capture-Seconds. A capture that queued four minutes
    behind a deploy and then rendered in two seconds is a two-second frame,
    and reporting 242s would quietly poison every budget comparison.
    """
    mod, lock = bench_lock_service
    _fake_subprocess(mod, monkeypatch, _FakeRun())
    result = {}

    with _posting(mod) as post:
        with _holding(lock):
            thread = threading.Thread(
                target=lambda: result.update(zip(("code", "hdrs", "body"),
                                                 post("/capture", dict(_SCENE)))),
                daemon=True)
            thread.start()
            time.sleep(0.8)
        thread.join(timeout=30)

    assert result["code"] == 200
    assert float(result["hdrs"]["X-Capture-Lock-Wait-Seconds"]) >= 0.7
    assert float(result["hdrs"]["X-Capture-Seconds"]) < 0.5


def test_lock_wait_field_can_only_shorten_the_wait(bench_lock_service):
    mod, _lock = bench_lock_service
    assert mod.requested_lock_wait({}) == mod.BENCH_LOCK_WAIT
    assert mod.requested_lock_wait({"lock_wait": 0}) == 0.0
    assert mod.requested_lock_wait({"lock_wait": 5}) == 5.0
    # Clamped UP to the ceiling and DOWN at zero: one HTTP request must not be
    # able to pin the bench for longer than the box's own policy allows.
    assert mod.requested_lock_wait({"lock_wait": 10 ** 6}) == mod.BENCH_LOCK_WAIT
    assert mod.requested_lock_wait({"lock_wait": -1}) == 0.0
    with pytest.raises(ValueError):
        mod.requested_lock_wait({"lock_wait": "soon"})


def test_lock_wait_zero_fails_fast_instead_of_blocking(bench_lock_service, monkeypatch):
    mod, lock = bench_lock_service
    fake = _fake_subprocess(mod, monkeypatch, _FakeRun())
    with _posting(mod) as post, _holding(lock):
        started = time.monotonic()
        code, _hdrs, body = post("/capture", dict(_SCENE, lock_wait=0))
        waited = time.monotonic() - started
    assert code == 503 and json.loads(body)["error"] == "bench busy"
    assert waited < 5, "lock_wait=0 must not block"
    assert fake.calls == 0


def test_an_unusable_bench_lock_is_a_503_not_an_unlocked_render(monkeypatch, tmp_path):
    """The failure path that matters: no silent fallback to running unlocked."""
    monkeypatch.setenv("CAPTURE_BENCH_LOCK", str(tmp_path / "no-such-dir" / "lock"))
    mod = _load_capture_service(monkeypatch, tmp_path)
    fake = _fake_subprocess(mod, monkeypatch, _FakeRun())

    with _posting(mod) as post:
        code, _hdrs, body = post("/capture", dict(_SCENE))
    assert code == 503
    assert json.loads(body)["error"] == "bench lock unavailable"
    assert fake.calls == 0, "rendered with no mutual exclusion at all"


def test_health_reports_whether_the_bench_lock_is_held(bench_lock_service):
    mod, lock = bench_lock_service
    with _serving(mod) as health:
        with _holding(lock, holder="owner=AVIONICS issue=AER-2658 pid=7"):
            held = health()
        free = health()
    assert held["bench_lock_held"] is True
    assert "AER-2658" in held["bench_lock_holder"]
    assert held["bench_lock"] == str(lock)
    assert free["bench_lock_held"] is False
