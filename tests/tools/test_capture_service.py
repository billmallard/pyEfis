"""Tests for tools/capture_service.py (AER-2627).

Covers the one behavior this move exists to deliver: `/health`'s
`service_ref` is resolved LIVE from the checkout `capture_service.py` itself
lives in, via the same `pyefis_rev.resolve_pyefis_rev()` svs_capture.py uses
for its per-frame sidecar -- not a deploy-time-written file that can go
stale or report "unknown" because a deploy step forgot to write it.

Also covers `build_argv`'s pure translation logic (argv construction, the
AER-676 unknown-field rejection it depends on) since that moved along with
the file and had no test coverage of its own before (it previously lived
outside any checkout this repo's test suite could reach).
"""
import importlib.util
import json
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]


def _load_capture_service(monkeypatch, tmp_path):
    token_file = tmp_path / ".capture-token"
    token_file.write_text("test-token\n")
    monkeypatch.setenv("CAPTURE_TOKEN_FILE", str(token_file))
    spec = importlib.util.spec_from_file_location(
        "capture_service", _ROOT / "tools" / "capture_service.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def capture_service(monkeypatch, tmp_path):
    return _load_capture_service(monkeypatch, tmp_path)


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


def test_health_service_ref_matches_live_resolve_pyefis_rev(capture_service):
    from pyefis_rev import resolve_pyefis_rev

    expected = resolve_pyefis_rev(capture_service.PYEFIS_ROOT)
    assert expected != "unknown"  # this test runs inside a real git checkout

    server = ThreadingHTTPServer(("127.0.0.1", 0), capture_service.Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/health",
            headers={"Authorization": "Bearer test-token"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read())
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    # The exact field name QA_AGENT_SPEC.md documents and
    # converge_map_gestures.py reads -- unchanged, just live now.
    assert body["service_ref"] == expected


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
