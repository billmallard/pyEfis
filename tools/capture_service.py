#!/usr/bin/env python3
"""SVS capture service -- the render tier, exposed as one HTTP capability.

Why this exists
---------------
pyEfis renders synthetic vision through real OpenGL. The Paperclip container
that hosts the QA agent has no GPU (the NAS is a Ryzen V1500B -- no integrated
graphics at all, no /dev/dri), so QA cannot run the render tier itself. The
bench can: an Intel Alder Lake-N iGPU, hardware Mesa GL 4.6, an X session, a
pyEfis checkout, and the installed data packs.

Rather than give QA a shell here, this service gives it exactly ONE capability:
"render this pose, hand back a PNG." That is the least-privilege posture used
elsewhere in this org -- the agent gets the capability, not the machine.

Contract
--------
  GET  /health              -> JSON: GL renderer, tool presence, data paths
  POST /capture             -> image/png on success, JSON on failure
  POST /bench/map            -> JSON (the MP7 harness's own output, unmodified)

All three require `Authorization: Bearer <token>`.

A `/capture` 200 carries its provenance in response headers, so the body stays
a plain PNG:

  X-Capture-Pyefis-Rev        the rev of the code that RENDERED these bytes,
                               from the spawned `svs_capture.py`'s own sidecar
  X-Capture-Manifest-Base64   that whole sidecar, base64 JSON -- includes the
                               sha256 tying it to the PNG in this response
  X-Capture-Service-Ref       this service's loaded rev (see SERVICE_REF)
  X-Capture-Seconds / -Argv   timing and the exact argv that was run

Both rev headers are present because they answer different questions and can
legitimately differ: `svs_capture.py` is spawned per request off disk, while
this service runs the module it imported at startup.

Captures are SERIALIZED. One GL capture runs at a time: svs_capture spawns a
fresh process per scenario by design (the visual harness carries module-global
state, so a reused process leaks the previous pose into the next frame), and
concurrent GL work on one iGPU buys nothing. `/bench/map` shares the SAME lock
-- it runs offscreen (QT_QPA_PLATFORM=offscreen, no GL) so it does not need
serializing against itself, but it does need serializing against a `/capture`
that might be mid-render, since both touch the one pyEfis checkout and the
live display shares the box.

Serialized against the DEPLOY as well (AER-2658)
------------------------------------------------
That in-process lock only keeps this service's own callers off each other. The
other tenant of this box is `bench-deploy.sh`, which takes an exclusive flock
on `/tmp/pyefis-bench.lock` for its whole run -- pull, restart, settle,
screenshot as one transaction -- "because the collision that actually hurts is
not git, it is two agents bouncing pyefis.service and grabbing screenshots over
each other, which produces evidence that belongs to neither run"
(`makerplane/processes/bench_deploy.md`). That reasoning covers these endpoints
exactly as written; they were simply never in the lock's scope, so a deploy
would `git pull --ff-only` the checkout and bounce `pyefis.service` while an
`svs_capture` subprocess was mid-render -- a frame rendered from a tree being
rewritten under it, carrying a `pyefis_rev` sidecar that reports the post-pull
sha. Wrong, and confidently labelled.

So every spawn below is wrapped in that same flock, acquired through
`bench_lock()`. A deploy and a capture queue behind one another instead of
overlapping, and no caller is handed a frame rendered through a moving tree.

  CAPTURE_BENCH_LOCK       /tmp/pyefis-bench.lock -- the file bench-deploy.sh
                            locks. Both ends use flock(2) (util-linux `flock`
                            there, `fcntl.flock` here) on the same path, so it
                            is the same lock. The script's `mkdir` fallback is
                            NOT honored: it engages only on a box without
                            util-linux, and both benches have it.
  CAPTURE_BENCH_LOCK_WAIT  900 -- seconds to wait for it, matching the 15
                            minutes `bench-deploy.sh` itself waits. Waiting is
                            the normal outcome; past the budget the caller gets
                            503 + `Retry-After`, never an unserialized render.
                            A caller may ask for LESS per request with the
                            `lock_wait` field (0 = fail fast, for a routine
                            that would rather retry than hold a connection
                            open for minutes) -- it cannot ask for more.

If the lock file cannot be opened at all, the request fails 503 rather than
proceeding unlocked. The silent-skip alternative reintroduces precisely the
defect this closes, and does it invisibly.

Lives in the checkout it serves (AER-2627)
-------------------------------------------
This file used to be hand-placed on the bench outside any git checkout
(``/home/pyefis/capture_service.py``), with no deploy route of its own --
`bench-deploy.sh`'s `git pull --ff-only` never touched it. Living in
`tools/` instead means the regular pull carries it for free, the same
pattern as `gpu-required` (a fork-only file that never rides upstream): the
fourth such file, now this one is no longer a fork-only exception, it is
just a tool shipped in the checkout.

Configuration (env, with the Beelink bench's defaults):
  CAPTURE_PORT        8085
  CAPTURE_TOKEN_FILE  /home/pyefis/.capture-token
  PYEFIS_ROOT         the checkout this file lives in (override only for
                       tests, or to point at a different checkout entirely)
  CAPTURE_PYTHON      /home/pyefis/pyefis-venv/bin/python
  CAPTURE_TILES       /data/makerplane-data/terrain/tiles
  CAPTURE_WATER       /data/makerplane-data/water/current/water.sqlite
  CAPTURE_HIGHWAYS    /data/makerplane-data/highways/current/highways.sqlite
  CAPTURE_NASR        /data/makerplane-data/navdata/current/airports.sqlite (unset by default)
  CAPTURE_NAVAID      /data/makerplane-data/navaids/current/navaids.sqlite (unset by default)
  CAPTURE_DOF         /data/makerplane-data/obstacles/current/obstacles.sqlite (unset by default)
  CAPTURE_DISPLAY     :0

`/bench/map` runs `tools/bench_map_gestures.py` (MP7,
docs/moving_map_spec.md section 9.1) -- the offscreen moving-map gesture
benchmark, distinct from `svs_capture.py`'s SVS/AI render. It needs no
GL and no DISPLAY (QT_QPA_PLATFORM=offscreen); NASR/navaid/DOF paths are
optional (empty string = that layer stays unconfigured, matching the
harness's own defaults) because the moving-map section 5 budgets this
endpoint exists for are all terrain+water.

`/health` reports `service_ref` -- the identity of the checkout this file is
actually running from (AER-2627). Before AER-2627 this was read from a
sidecar file a deploy step had to remember to write, and reported "unknown"
when it forgot -- provenance resting on another agent's timestamped word
rather than anything this service could verify itself. It is resolved from
git the same way `svs_capture.py` resolves its own `pyefis_rev` sidecar key
(`tools/pyefis_rev.py`, shared by both): a rev-parse against `PYEFIS_ROOT`,
dirty-flagged.

Loaded code, not the checkout on disk (AER-2657)
------------------------------------------------
`svs_capture.py` resolves that rev per frame and is spawned per request, so
for it "live" and "loaded" are the same thing. **This service is
long-running, so they are not.** It keeps executing the module Python
imported at startup, while `bench-deploy.sh`'s `git pull --ff-only` moves
the checkout underneath it -- and nothing in the deploy restarts this unit.
Resolving at request time therefore answered the wrong question: between a
pull that moved this file and the restart that picks it up, `/health` would
report the NEW sha while the process ran the OLD code. Before AER-2627 the
sidecar said "unknown" in that window, which is honest ignorance; a live
rev-parse is confident error, and this is the one value QA has for the
provenance of every render verdict in the org.

So `/health` answers both questions separately and says when they differ:

  service_ref   the rev resolved ONCE at import -- the code this process is
                 running. This is the provenance key; it cannot go stale
                 because the process it describes cannot change.
  checkout_ref  the rev resolved live, i.e. what a pull has brought in.
  service_stale true when a file this process loaded (`SERVICE_FILES`) no
                 longer matches the bytes on disk -> `sudo systemctl restart
                 svs-capture.service` to pick it up.

`service_stale` is a content comparison, not a sha comparison, because the
checkout moving is not the same question as this service's code moving:
`tools/svs_capture.py` and `tools/bench_map_gestures.py` are spawned per
request, so a pull that touches only those changes what renders with no
restart at all. Only these two files are loaded in-process, and only their
bytes are checked.
"""
from __future__ import annotations

import base64
import contextlib
import errno
import fcntl
import hashlib
import json
import os
import shlex
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pyefis_rev import resolve_pyefis_rev  # noqa: E402

PORT = int(os.environ.get("CAPTURE_PORT", "8085"))
TOKEN_FILE = Path(os.environ.get("CAPTURE_TOKEN_FILE", "/home/pyefis/.capture-token"))
PYEFIS_ROOT = Path(os.environ.get("PYEFIS_ROOT", str(Path(__file__).resolve().parent.parent)))
PYTHON = os.environ.get("CAPTURE_PYTHON", "/home/pyefis/pyefis-venv/bin/python")
TILES = os.environ.get("CAPTURE_TILES", "/data/makerplane-data/terrain/tiles")
WATER = os.environ.get("CAPTURE_WATER", "/data/makerplane-data/water/current/water.sqlite")
# Roads are OPT-IN: unlike tiles and water this is not applied unless the
# caller asks, so existing scenarios (notably the water oracle's isolate
# runs) keep rendering exactly what they render today.
HIGHWAYS = os.environ.get("CAPTURE_HIGHWAYS", "/data/makerplane-data/highways/current/highways.sqlite")
# NASR/navaid/DOF are unset by default (empty = "that layer stays
# unconfigured", the harness's own default) -- /bench/map exists to measure
# section 5's terrain+water budgets, not the airport/navaid/obstacle layers.
NASR = os.environ.get("CAPTURE_NASR", "")
NAVAID = os.environ.get("CAPTURE_NAVAID", "")
DOF = os.environ.get("CAPTURE_DOF", "")
DISPLAY = os.environ.get("CAPTURE_DISPLAY", ":0")
#: The bench run lock -- the same file, and the same flock(2), that
#: bench-deploy.sh holds for a whole deploy (AER-2658).
BENCH_LOCK = Path(os.environ.get("CAPTURE_BENCH_LOCK", "/tmp/pyefis-bench.lock"))
BENCH_LOCK_WAIT = float(os.environ.get("CAPTURE_BENCH_LOCK_WAIT", "900"))
#: bench-deploy.sh records its holder here; read back into a 503 so a blocked
#: caller is told WHO has the box, the same courtesy the script's own
#: "BENCH BUSY -- last recorded holder" line extends to agents with a shell.
BENCH_LOCK_OWNER_FILE = Path(f"{BENCH_LOCK}.owner")

CAPTURE_TOOL = "tools/svs_capture.py"
BENCH_MAP_TOOL = "tools/bench_map_gestures.py"

#: The files this process LOADS -- resolved from ``__file__``, not from
#: ``PYEFIS_ROOT``, because those can be different trees (``PYEFIS_ROOT`` is
#: overridable) and it is the loaded bytes that decide what this process
#: executes. `pyefis_rev.py` is on the list because it is imported at module
#: scope above; `svs_capture.py` and `bench_map_gestures.py` are NOT, because
#: they are spawned per request and a pull updates them with no restart.
SERVICE_FILES = tuple(
    Path(__file__).resolve().parent / name
    for name in ("capture_service.py", "pyefis_rev.py")
)


def _digest(path: Path):
    """sha256 of a file's bytes, or None if it cannot be read.

    Never raises: this feeds a metadata field, and an unreadable file (mid-pull,
    deleted) must not take /health down with it.
    """
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


#: Captured at import -- the identity of the code this process is running.
#: Frozen on purpose; see the module docstring (AER-2657).
SERVICE_REF = resolve_pyefis_rev(PYEFIS_ROOT)
_LOADED_DIGESTS = {p: _digest(p) for p in SERVICE_FILES}


def service_is_stale():
    """True when a loaded service file on disk no longer matches what is running.

    An unreadable file counts as stale: the safe direction is to tell the
    caller a restart is due rather than imply the running code is current.
    """
    return any(_digest(p) != loaded for p, loaded in _LOADED_DIGESTS.items())


#: How often the bench-lock wait re-tries. Short enough that the reported wait
#: is honest to a fraction of a second, long enough to cost nothing over 900s.
BENCH_LOCK_POLL = 0.25


class BenchBusy(Exception):
    """The bench lock did not come free inside the caller's wait budget."""

    def __init__(self, waited: float, holder: str | None):
        super().__init__(f"bench busy after {waited:.1f}s")
        self.waited = round(waited, 1)
        self.holder = holder


class BenchLockUnavailable(Exception):
    """The lock FILE could not be opened or locked -- so we refuse to run.

    Distinct from BenchBusy on purpose: busy is the normal, expected outcome of
    a shared box, this one means the mutual exclusion is broken. Running
    anyway would be the AER-2658 defect again, with nobody told.
    """


def bench_lock_holder() -> str | None:
    """bench-deploy.sh's recorded holder line, or None if there is none."""
    try:
        return BENCH_LOCK_OWNER_FILE.read_text().splitlines()[0].strip() or None
    except (OSError, IndexError):
        return None


def _open_bench_lock() -> int:
    """Open the lock file for locking, without disturbing its contents.

    Never truncates (bench-deploy.sh appends to this file and writes the holder
    record beside it), and falls back to read-only because flock(2) on Linux
    takes an exclusive lock on a read-only descriptor just fine -- the file may
    belong to another user on a box where a deploy ran under a different
    account.
    """
    try:
        return os.open(BENCH_LOCK, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o666)
    except OSError:
        return os.open(BENCH_LOCK, os.O_RDONLY)


@contextlib.contextmanager
def bench_lock(wait: float):
    """Hold the bench run lock for the body; yield the seconds spent waiting.

    Raises BenchBusy if `wait` elapses first, BenchLockUnavailable if the lock
    cannot be operated at all. Blocking is implemented as a non-blocking retry
    loop rather than `flock -w` so the wait can be measured and reported --
    a capture that took four minutes because a deploy had the box must be
    explicable from its own response, not only from a journal.
    """
    started = time.monotonic()
    try:
        fd = _open_bench_lock()
    except OSError as exc:
        raise BenchLockUnavailable(f"cannot open {BENCH_LOCK}: {exc}") from exc
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in (errno.EWOULDBLOCK, errno.EACCES, errno.EAGAIN):
                    raise BenchLockUnavailable(
                        f"cannot lock {BENCH_LOCK}: {exc}") from exc
                waited = time.monotonic() - started
                if waited >= wait:
                    raise BenchBusy(waited, bench_lock_holder())
                time.sleep(min(BENCH_LOCK_POLL, wait - waited))
        yield round(time.monotonic() - started, 1)
    finally:
        # Closing the descriptor releases the flock -- the lock lives on the
        # open file description, so this covers the success path, the
        # subprocess-timeout path and an unexpected raise alike.
        os.close(fd)


def bench_lock_state() -> bool | None:
    """True if something holds the bench lock right now, None if unknowable.

    A momentary probe, for /health only: acquire non-blocking and let go. Our
    own in-flight capture counts as a holder (flock conflicts across
    descriptors in one process), which is the honest answer -- `busy` says
    whether that holder is us.
    """
    try:
        fd = _open_bench_lock()
    except OSError:
        return None
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return True
    finally:
        os.close(fd)
    return False


def requested_lock_wait(p: dict) -> float:
    """The caller's bench-lock wait budget, clamped to [0, BENCH_LOCK_WAIT].

    A caller may ask to wait less than the configured ceiling (a routine that
    prefers an immediate 503 and a retry of its own), never more -- nothing
    reached through one HTTP request should be able to pin the bench for
    longer than the box's own policy allows.
    """
    try:
        asked = float(p.get("lock_wait", BENCH_LOCK_WAIT))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"bad lock_wait: {exc}") from exc
    return max(0.0, min(asked, BENCH_LOCK_WAIT))


def take_manifest(out_path):
    """Read and remove ``<out_path>.json``, the sidecar `svs_capture.py` wrote.

    Returns the parsed sidecar, or None if there is not a readable one.

    Taking it is not optional bookkeeping. `svs_capture.py` writes the sidecar
    next to the frame it rendered (`pyefis_rev`, capture_mode, requested vs
    actual size, argv, sha256 of the PNG), but this service renders into a
    tempfile and returns the PNG bytes -- so unless the sidecar is read before
    that tempfile goes away, every frame served over HTTP reaches the caller
    naming nothing, which is the exact condition AER-1675 was opened on. It
    also removes it, because 355 orphaned `tmp*.png.json` files had
    accumulated in /tmp on the Beelink by the time this was found.

    Never raises: provenance is metadata on a capture, never a dependency of
    one (same rule as `resolve_pyefis_rev`). A missing or malformed sidecar
    costs the response its manifest header and nothing else.
    """
    path = Path(str(out_path) + ".json")
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    finally:
        try:
            path.unlink()
        except OSError:
            pass
    try:
        return json.loads(raw)
    except ValueError:
        return None


MAX_TIMEOUT = 600
#: /bench/map runs multiple gesture scenarios in one subprocess (--scenario
#: all); each one can hold for several seconds past its settle latency, so
#: the default budget is generous compared to /capture's single-frame 120 s.
BENCH_MAP_DEFAULT_TIMEOUT = 300
_lock = threading.Lock()

#: bench_map_gestures.py's own --scenario choices, mirrored here (subprocess
#: boundary -- this service cannot import the harness's SCENARIOS dict) so a
#: bad scenario name is rejected with a 400 instead of failing inside the
#: subprocess (AER-676 strict-rejection convention, same as ALLOWED_FIELDS
#: below).
BENCH_MAP_SCENARIOS = frozenset({
    "pinch_out", "pinch_in", "rotate", "pan", "ladder", "all",
})

# The full set of /bench/map request fields this service understands --
# mirrors bench_map_gestures.py's own CLI, minus --out/--budget (the service
# owns the output file; a budget check is MP9b's QA routine, not this
# endpoint) and --moving-position/--target/--gs/--heading/--position-hz/
# --duration (AER-679 mode; not this issue's scope -- add when a caller
# needs it, same AER-676 discipline as ALLOWED_FIELDS below).
BENCH_MAP_ALLOWED_FIELDS = frozenset({
    "scenario", "w", "h", "lat", "lon", "track", "alt",
    "range_ladder", "pinch_lo_nm", "pinch_hi_nm",
    "tile_path", "water_db", "water_max_vertices", "water_raster",
    "highway_db", "river_db", "nasr_db", "navaid_db", "dof_db",
    "timeout", "lock_wait",
})

# svs_capture's own exit codes, so a caller can tell "no GPU" from "never settled".
EXIT_MEANING = {
    0: "ok",
    2: "scene never settled (a half-loaded frame was refused)",
    3: "OpenGL renderer unavailable",
    4: "PNG write failed",
    6: "mock FIX db bypassed (would have attached to the live gateway)",
}

# The full set of scenario fields this service understands. A field outside
# this set is REJECTED, not ignored (AER-676): a caller believing it exercised
# a field the service silently dropped is a false pass, and a false pass in
# an oracle's only window onto the render tier is worse than no oracle.
ALLOWED_FIELDS = frozenset({
    "lat", "lon", "alt", "heading", "pitch", "roll", "range_nm",
    "width", "height", "tiles", "water", "water_max_vertices",
    "flat", "terrain_only", "symbology_only", "magvar",
    "isolate", "highways", "perf_log", "timeout", "lock_wait",
})


def _token() -> str:
    return TOKEN_FILE.read_text().strip()


def _highways_path(p: dict) -> str:
    """Resolve the `highways` request field to an svs_capture --highways value.

    Absent or false -> "" -> HighwayDB.ready is False -> no roads can be
    drawn (highway_db.py: `if not path: return`). True -> the configured
    pack. A string -> that path verbatim.
    """
    h = p.get("highways")
    return HIGHWAYS if h is True else ("" if not h else str(h))


def build_argv(p: dict, out: str) -> list[str]:
    """Translate a scenario dict into svs_capture argv."""
    # svs_capture.py rejects --terrain-only and --symbology-only together, and
    # terrain_only defaults to true HERE, so the raw scenario field cannot be
    # what decides argv content -- every symbology_only request would collide
    # with a default the caller never asked for. Resolve terrain_only first:
    # symbology_only suppresses that default, and only an EXPLICIT
    # terrain_only: true alongside symbology_only: true is a real conflict.
    symbology_only = bool(p.get("symbology_only", False))
    if symbology_only:
        terrain_only = bool(p.get("terrain_only", False))
        if terrain_only:
            raise ValueError(
                "terrain_only and symbology_only are mutually exclusive"
            )
    else:
        terrain_only = bool(p.get("terrain_only", True))

    # AER-1002: magvar is only emitted when non-default so a magvar: 0 (or
    # omitted) caller's argv stays byte-identical to a pre-AER-1002 caller's
    # -- the same invariant AER-708 held for svs_capture's own --magvar.
    magvar = float(p.get("magvar", 0.0))

    argv = [
        PYTHON, CAPTURE_TOOL,
        "--lat", f"{float(p['lat']):.6f}",
        "--lon", f"{float(p['lon']):.6f}",
        "--alt", f"{float(p['alt']):.1f}",
        "--heading", f"{float(p.get('heading', 0.0)):.2f}",
        "--pitch", f"{float(p.get('pitch', 0.0)):.2f}",
        "--roll", f"{float(p.get('roll', 0.0)):.2f}",
        "--range", f"{float(p.get('range_nm', 30.0)):.2f}",
        "--width", str(int(p.get("width", 800))),
        "--height", str(int(p.get("height", 600))),
        "--tiles", str(p.get("tiles", TILES)),
        "--water", str(p.get("water", WATER)),
        # Emitted exactly once, and here rather than under `isolate`: argparse
        # takes the LAST occurrence, so a second copy in the isolate branch
        # would silently override an explicit request.
        "--highways", _highways_path(p),
        "--out", out,
        # ALWAYS explicit, never omitted. svs_capture's own help warns that at
        # the 32 default _decode_vertices stride-decimates the ring while
        # _decode_triangles keeps the ORIGINAL indices, which are then clamped
        # -- collapsing most triangles to degenerate slivers and "silently
        # rendering corrupt water". A render oracle must never inherit that by
        # accident, so the cap is a first-class parameter with a stated default
        # (1024 = what the appliance actually runs).
        "--water-max-vertices", str(int(p.get("water_max_vertices", 1024))),
    ]
    if magvar != 0.0:
        argv += ["--magvar", f"{magvar:.2f}"]
    if p.get("flat", True):
        argv.append("--flat")
    if terrain_only:
        argv.append("--terrain-only")
    if symbology_only:
        argv.append("--symbology-only")
    if p.get("isolate", True):
        # Nothing may paint over the answer: an oracle that judges one property
        # must control every other thing that can draw.
        # `highways` is exempt: it defaults to "" above, so isolate still
        # suppresses roads for every caller that does not ask. A caller that
        # DOES ask has made roads the answer.
        argv += ["--dof", "", "--nasr", "", "--cifp", ""]
    if p.get("perf_log", False):
        # AER-1976: opt-in, like `highways` above -- existing callers (the
        # water oracle's isolate runs) keep the argv they already get.
        argv.append("--perf-log")
    argv += ["--timeout", str(int(p.get("timeout", 120)))]
    return argv


def build_bench_map_argv(p: dict, out: str) -> list[str]:
    """Translate a /bench/map request dict into bench_map_gestures.py argv.

    Defaults mirror the harness's own bench-run recipe (docstring at the top
    of tools/bench_map_gestures.py): the bench's real packs at the bench
    widget size, Raleigh scene, --scenario all. NASR/navaid/DOF default to
    unconfigured (empty), same rationale as HIGHWAYS in build_argv() above --
    this endpoint measures terrain+water, and a caller that wants roads or
    navaids configured can ask for them explicitly.
    """
    scenario = str(p.get("scenario", "all"))
    if scenario not in BENCH_MAP_SCENARIOS:
        raise ValueError(f"unknown scenario: {scenario!r}")
    argv = [
        PYTHON, BENCH_MAP_TOOL,
        "--scenario", scenario,
        "--w", str(int(p.get("w", 650))),
        "--h", str(int(p.get("h", 1040))),
        "--lat", f"{float(p.get('lat', 35.8)):.6f}",
        "--lon", f"{float(p.get('lon', -78.8)):.6f}",
        "--track", f"{float(p.get('track', 0.0)):.2f}",
        "--alt", f"{float(p.get('alt', 1500.0)):.1f}",
        "--range-ladder", str(p.get("range_ladder", "2,5,10,20,40,80,160")),
        "--tile-path", str(p.get("tile_path", TILES)),
        "--water-db", str(p.get("water_db", WATER)),
        # ALWAYS explicit, same rationale as build_argv()'s --water-max-vertices:
        # omitting it silently renders corrupt water through the
        # decimation/clamp mismatch (AX-9). 1024 = what the appliance runs.
        "--water-max-vertices", str(int(p.get("water_max_vertices", 1024))),
        "--water-raster", str(p.get("water_raster", "numpy")),
        "--highway-db", str(p.get("highway_db", "")),
        "--river-db", str(p.get("river_db", "")),
        "--nasr-db", str(p.get("nasr_db", NASR)),
        "--navaid-db", str(p.get("navaid_db", NAVAID)),
        "--dof-db", str(p.get("dof_db", DOF)),
        "--out", out,
    ]
    if "pinch_lo_nm" in p:
        argv += ["--pinch-lo-nm", f"{float(p['pinch_lo_nm']):.2f}"]
    if "pinch_hi_nm" in p:
        argv += ["--pinch-hi-nm", f"{float(p['pinch_hi_nm']):.2f}"]
    return argv


class Handler(BaseHTTPRequestHandler):
    server_version = "svs-capture/1.0"

    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {fmt % args}", flush=True)

    # -- helpers --
    def _json(self, code: int, obj: dict):
        body = json.dumps(obj, indent=1).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _bench_busy(self, busy: BenchBusy, what: str):
        """503 for a request that waited out its bench-lock budget."""
        body = {
            "error": "bench busy",
            "detail": f"{what} did not start: another tenant holds {BENCH_LOCK}",
            "waited_seconds": busy.waited,
            "lock": str(BENCH_LOCK),
            "holder": busy.holder,
            # Transient by design, exactly as bench-deploy.sh's exit 7 is:
            # retry, do not escalate (processes/bench_deploy.md).
            "hint": "a deploy or another agent has the bench; retry",
        }
        self.send_response(503)
        self.send_header("Content-Type", "application/json")
        payload = json.dumps(body, indent=1).encode()
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Retry-After", "30")
        self.end_headers()
        self.wfile.write(payload)

    def _bench_lock_broken(self, exc: BenchLockUnavailable):
        """503 for a bench lock that cannot be operated at all.

        Deliberately NOT a fallback to running unlocked: that is the AER-2658
        defect, and it would be invisible.
        """
        return self._json(503, {
            "error": "bench lock unavailable",
            "detail": str(exc),
            "lock": str(BENCH_LOCK),
            "hint": "refusing to render unserialized; fix the lock file's "
                    "permissions or set CAPTURE_BENCH_LOCK",
        })

    def _authed(self) -> bool:
        got = self.headers.get("Authorization", "")
        want = f"Bearer {_token()}"
        if len(got) != len(want) or got != want:
            self._json(401, {"error": "unauthorized"})
            return False
        return True

    def do_GET(self):
        if self.path != "/health":
            return self._json(404, {"error": "not found"})
        if not self._authed():
            return
        gl = "unknown"
        try:
            r = subprocess.run(["glxinfo", "-B"], env={**os.environ, "DISPLAY": DISPLAY},
                               capture_output=True, text=True, timeout=20)
            for line in r.stdout.splitlines():
                if "OpenGL renderer string" in line:
                    gl = line.split(":", 1)[1].strip()
        except Exception as exc:
            gl = f"glxinfo failed: {exc}"
        self._json(200, {
            "ok": True,
            # service_ref is the code this process runs (frozen at import);
            # checkout_ref is what is on disk now. They differ for as long as
            # a pull has landed and nobody has restarted this unit (AER-2657).
            "service_ref": SERVICE_REF,
            "checkout_ref": resolve_pyefis_rev(PYEFIS_ROOT),
            "service_stale": service_is_stale(),
            "gl_renderer": gl,
            "display": DISPLAY,
            "capture_tool": str(PYEFIS_ROOT / CAPTURE_TOOL),
            "capture_tool_present": (PYEFIS_ROOT / CAPTURE_TOOL).is_file(),
            "bench_map_tool": str(PYEFIS_ROOT / BENCH_MAP_TOOL),
            "bench_map_tool_present": (PYEFIS_ROOT / BENCH_MAP_TOOL).is_file(),
            "tiles": TILES,
            "tiles_present": Path(TILES).is_dir(),
            "water": WATER,
            "water_present": Path(WATER).is_file(),
            "highways": HIGHWAYS,
            "highways_present": Path(HIGHWAYS).is_file(),
            "busy": _lock.locked(),
            # The bench run lock (AER-2658). `busy` is this service's own
            # queue; `bench_lock_held` includes the other tenant -- a deploy
            # holding the box -- so a caller can tell "someone else is
            # mid-deploy" from "I am behind my own earlier request".
            "bench_lock": str(BENCH_LOCK),
            "bench_lock_held": bench_lock_state(),
            "bench_lock_holder": bench_lock_holder(),
            "bench_lock_wait": BENCH_LOCK_WAIT,
        })

    def do_POST(self):
        if self.path not in ("/capture", "/bench/map"):
            return self._json(404, {"error": "not found"})
        if not self._authed():
            return
        try:
            n = int(self.headers.get("Content-Length", "0"))
            params = json.loads(self.rfile.read(n) or b"{}")
        except Exception as exc:
            return self._json(400, {"error": f"bad JSON body: {exc}"})
        if self.path == "/bench/map":
            return self._handle_bench_map(params)
        return self._handle_capture(params)

    def _handle_capture(self, params: dict):
        unknown = sorted(set(params) - ALLOWED_FIELDS)
        if unknown:
            # Reject, don't ignore (AER-676): a silently-dropped field lets a
            # caller believe it exercised something it never tested.
            return self._json(400, {"error": f"unknown scenario field(s): {', '.join(unknown)}"})
        for req in ("lat", "lon", "alt"):
            if req not in params:
                return self._json(400, {"error": f"missing required field: {req}"})

        timeout = min(int(params.get("timeout", 120)), MAX_TIMEOUT)
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp.close()
        try:
            argv = build_argv(params, tmp.name)
            lock_wait_budget = requested_lock_wait(params)
        except (KeyError, TypeError, ValueError) as exc:
            os.unlink(tmp.name)
            return self._json(400, {"error": f"bad scenario: {exc}"})

        # Serialize twice over: `_lock` keeps this service's own callers off
        # one iGPU, `bench_lock` keeps the whole render off a deploy that is
        # rewriting the checkout under it (AER-2658). Always in that order --
        # one fixed order is what makes two locks deadlock-free.
        try:
            with _lock, bench_lock(lock_wait_budget) as lock_wait:
                # Timed from HERE, not from the top of the handler: `seconds`
                # is the render, and a four-minute queue behind a deploy must
                # not be reported as a four-minute frame. The wait is its own
                # number below.
                started = time.time()
                try:
                    proc = subprocess.run(
                        argv, cwd=str(PYEFIS_ROOT),
                        env={**os.environ, "DISPLAY": DISPLAY},
                        capture_output=True, text=True, timeout=timeout + 30,
                    )
                except subprocess.TimeoutExpired:
                    take_manifest(tmp.name)
                    os.unlink(tmp.name)
                    return self._json(504, {"error": "capture timed out",
                                            "seconds": round(time.time() - started, 1),
                                            "lock_wait_seconds": lock_wait,
                                            "argv": " ".join(shlex.quote(a) for a in argv)})
                elapsed = round(time.time() - started, 1)
        except BenchBusy as busy:
            os.unlink(tmp.name)
            return self._bench_busy(busy, "capture")
        except BenchLockUnavailable as exc:
            os.unlink(tmp.name)
            return self._bench_lock_broken(exc)

        if proc.returncode != 0 or not os.path.getsize(tmp.name):
            body = {
                "error": "capture failed",
                "exit_code": proc.returncode,
                "meaning": EXIT_MEANING.get(proc.returncode, "unknown"),
                "seconds": elapsed,
                "lock_wait_seconds": lock_wait,
                "stderr": proc.stderr[-2000:],
                "argv": " ".join(shlex.quote(a) for a in argv),
            }
            take_manifest(tmp.name)
            os.unlink(tmp.name)
            return self._json(502, body)

        png = Path(tmp.name).read_bytes()
        # Before the tempfile goes away -- the sidecar is named after it.
        manifest = take_manifest(tmp.name)
        os.unlink(tmp.name)
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(png)))
        # Metadata rides in headers so the body stays a plain PNG.
        self.send_header("X-Capture-Seconds", str(elapsed))
        # Queue time, reported separately so X-Capture-Seconds stays a render
        # number a perf oracle can trust (AER-2658).
        self.send_header("X-Capture-Lock-Wait-Seconds", str(lock_wait))
        self.send_header("X-Capture-Argv", " ".join(shlex.quote(a) for a in argv))
        # The code that rendered these bytes (AER-1675). `svs_capture.py` is
        # spawned per request from PYEFIS_ROOT, so the sidecar's `pyefis_rev`
        # -- not this service's frozen SERVICE_REF -- is the renderer's
        # identity, and it is the one a cross-renderer differential needs to
        # tell "different GPU" apart from "different code".
        if manifest:
            rev = manifest.get("pyefis_rev")
            if rev:
                self.send_header("X-Capture-Pyefis-Rev", str(rev))
            # The whole sidecar too, so the caller keeps the sha256 that ties
            # it to the PNG it just received, the requested-vs-actual size and
            # the capture mode. Base64 for the same reason the perf log is:
            # the argv it carries cannot ride raw in a header value.
            self.send_header(
                "X-Capture-Manifest-Base64",
                base64.b64encode(json.dumps(manifest).encode()).decode(),
            )
        # This service's own loaded rev, so provenance for a frame is one
        # response rather than a /capture plus a /health the caller has to
        # assume nothing moved between.
        self.send_header("X-Capture-Service-Ref", SERVICE_REF)
        if params.get("perf_log", False):
            # svs_capture.py's perf report goes to stderr (log.info, forced
            # past the profiler's own 2s interval) and is otherwise thrown
            # away on a successful capture -- asking for perf_log and never
            # being able to read it back would make the field pointless.
            # Base64 because the report is multi-line and a raw header value
            # cannot carry embedded newlines.
            perf_log_b64 = base64.b64encode(
                proc.stderr[-4000:].encode()).decode()
            self.send_header("X-Capture-Perf-Log-Base64", perf_log_b64)
        self.end_headers()
        self.wfile.write(png)

    def _handle_bench_map(self, params: dict):
        unknown = sorted(set(params) - BENCH_MAP_ALLOWED_FIELDS)
        if unknown:
            # Same AER-676 discipline as _handle_capture: reject, don't ignore.
            return self._json(400, {"error": f"unknown scenario field(s): {', '.join(unknown)}"})

        timeout = min(int(params.get("timeout", BENCH_MAP_DEFAULT_TIMEOUT)), MAX_TIMEOUT)
        tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        tmp.close()
        try:
            argv = build_bench_map_argv(params, tmp.name)
            lock_wait_budget = requested_lock_wait(params)
        except (KeyError, TypeError, ValueError) as exc:
            os.unlink(tmp.name)
            return self._json(400, {"error": f"bad scenario: {exc}"})

        # Same two locks as /capture, same order: bench_map_gestures.py needs
        # no GL of its own (offscreen QPA), but it reads the one pyEfis
        # checkout -- which a deploy rewrites -- and shares the box with a
        # /capture that might be mid-render.
        try:
            with _lock, bench_lock(lock_wait_budget) as lock_wait:
                started = time.time()
                try:
                    proc = subprocess.run(
                        argv, cwd=str(PYEFIS_ROOT),
                        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
                        capture_output=True, text=True, timeout=timeout + 30,
                    )
                except subprocess.TimeoutExpired:
                    os.unlink(tmp.name)
                    return self._json(504, {"error": "bench/map timed out",
                                            "seconds": round(time.time() - started, 1),
                                            "lock_wait_seconds": lock_wait,
                                            "argv": " ".join(shlex.quote(a) for a in argv)})
                elapsed = round(time.time() - started, 1)
        except BenchBusy as busy:
            os.unlink(tmp.name)
            return self._bench_busy(busy, "bench/map")
        except BenchLockUnavailable as exc:
            os.unlink(tmp.name)
            return self._bench_lock_broken(exc)

        if proc.returncode != 0 or not os.path.getsize(tmp.name):
            body = {
                "error": "bench/map failed",
                "exit_code": proc.returncode,
                "seconds": elapsed,
                "lock_wait_seconds": lock_wait,
                "stderr": proc.stderr[-4000:],
                "argv": " ".join(shlex.quote(a) for a in argv),
            }
            os.unlink(tmp.name)
            return self._json(502, body)

        # The harness's own JSON, byte-for-byte -- this endpoint's whole
        # contract is "runs the MP7 harness, returns the JSON unmodified"
        # (AER-1217), so the response body is the harness's --out file read
        # straight off disk, never re-serialized through this service.
        payload = Path(tmp.name).read_bytes()
        os.unlink(tmp.name)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("X-Bench-Map-Seconds", str(elapsed))
        self.send_header("X-Bench-Map-Lock-Wait-Seconds", str(lock_wait))
        self.send_header("X-Bench-Map-Argv", " ".join(shlex.quote(a) for a in argv))
        self.end_headers()
        self.wfile.write(payload)


def main():
    if not TOKEN_FILE.is_file():
        raise SystemExit(f"no token file at {TOKEN_FILE}")
    if not (PYEFIS_ROOT / CAPTURE_TOOL).is_file():
        raise SystemExit(f"capture tool not found at {PYEFIS_ROOT / CAPTURE_TOOL}")
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"svs-capture listening on :{PORT} (DISPLAY={DISPLAY}, root={PYEFIS_ROOT})", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
