#  SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for tools/evidence_sidecar.py and tools/evidence_index.py (TV12).

The sidecar states are what the index reports about each image, so each one is built
here from a real file and checked; the stale case is the reason the sidecar carries a
hash at all. The index reaches a public page, so the sanitizer and the wording rule are
pinned the same way tests/tools/test_verification_report.py pins them. The last test
runs over the committed evidence: a sidecar that is present but broken fails CI."""

import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "tools"))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


es = _load("evidence_sidecar")
ei = _load("evidence_index")


def _png(path, data=b"\x89PNG not really"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


# --------------------------------------------------------------------------- sidecar

def test_write_sidecar_round_trips_as_ok(tmp_path):
    img = _png(tmp_path / "shot.png")
    rec = es.write_sidecar(img, commit="abc1234", run="local: test", device="Test board (offscreen)")
    assert rec["schema"] == "evidence-sidecar/1"
    assert rec["sha256"] == hashlib.sha256(img.read_bytes()).hexdigest()
    state, read = es.check_sidecar(img)
    assert state == "ok"
    assert (read["commit"], read["run"], read["device"]) == ("abc1234", "local: test", "Test board (offscreen)")


def test_sidecar_goes_stale_when_the_image_changes(tmp_path):
    img = _png(tmp_path / "shot.png")
    es.write_sidecar(img, commit="abc1234", run="r", device="d")
    img.write_bytes(b"a different frame")
    assert es.check_sidecar(img)[0] == "stale"


def test_sidecar_states_none_incomplete_legacy_unreadable(tmp_path):
    img = _png(tmp_path / "a.png")
    assert es.check_sidecar(img)[0] == "none"
    es.write_sidecar(img, commit="abc1234", run="r", device="d")
    rec = json.loads(es.sidecar_path(img).read_text())
    rec["device"] = ""
    es.sidecar_path(img).write_text(json.dumps(rec))
    assert es.check_sidecar(img)[0] == "incomplete"
    es.sidecar_path(img).write_text(json.dumps({"pyefis_rev": "1e7db42"}))
    assert es.check_sidecar(img)[0] == "legacy"
    es.sidecar_path(img).write_text("{not json")
    assert es.check_sidecar(img)[0] == "unreadable"


def test_describe_run_prefers_the_ci_run_url():
    env = {"GITHUB_RUN_ID": "42", "GITHUB_REPOSITORY": "billmallard/pyEfis",
           "GITHUB_SERVER_URL": "https://github.com", "EVIDENCE_RUN": "bench"}
    assert es.describe_run(environ=env) == "https://github.com/billmallard/pyEfis/actions/runs/42"
    assert es.describe_run(environ={"EVIDENCE_RUN": "AER-1 bench session"}) == "AER-1 bench session"
    assert es.describe_run(argv=["tools/x.py", "--out", "y.png"], environ={}) == "local: tools/x.py --out y.png"


def test_describe_device_names_the_runner_and_qt_platform():
    env = {"GITHUB_ACTIONS": "true", "RUNNER_OS": "Linux", "QT_QPA_PLATFORM": "offscreen"}
    assert es.describe_device(environ=env) == "GitHub Actions Linux runner (offscreen)"
    assert es.describe_device(environ={"QT_QPA_PLATFORM": "eglfs"}).endswith("(eglfs)")


def test_cli_requires_all_three_keys(tmp_path, capsys):
    img = _png(tmp_path / "a.png")
    try:
        es.main([str(img), "--run", "r", "--device", "d"])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("--commit should be required")
    assert es.main([str(img), "--commit", "abc1234", "--run", "r", "--device", "d"]) == 0
    assert es.check_sidecar(img)[0] == "ok"


# --------------------------------------------------------------------------- index

def _tree(tmp_path):
    d = tmp_path / "docs" / "images" / "aer1234_baro_box"
    (d / "README.md").parent.mkdir(parents=True)
    (d / "README.md").write_text("# Baro box (AER-1234)\n\nSee 203.0.113.9 for nothing.\n")
    good = _png(d / "good.png")
    es.write_sidecar(good, commit="abc1234", run="https://github.com/billmallard/pyEfis/actions/runs/7",
                     device="Pilot board at 192.0.2.4 (eglfs)")
    _png(d / "bare.png")
    old = tmp_path / "docs" / "aer-77-evidence"
    _png(old / "frame.png")
    (old / "frame.png.json").write_text(json.dumps({"pyefis_rev": "1e7db42", "argv": "svs_capture.py"}))
    (tmp_path / "docs" / "images" / "unrelated").mkdir()
    return tmp_path


def test_scan_finds_both_roots_in_issue_order(tmp_path):
    entries = ei.scan(_tree(tmp_path))
    assert [e["issue"] for e in entries] == ["AER-77", "AER-1234"]
    old, new = entries
    assert new["title"] == "Baro box (AER-1234)"
    states = {Path(i["path"]).name: i["state"] for i in new["images"]}
    assert states == {"bare.png": "none", "good.png": "ok"}
    assert old["images"][0]["state"] == "legacy"
    assert (old["images"][0]["commit"], old["images"][0]["run"]) == ("1e7db42", "svs_capture.py")


def test_check_fails_only_on_a_broken_sidecar(tmp_path, capsys):
    root = _tree(tmp_path)
    assert ei.main(["--repo-root", str(root), "--check"]) == 0
    (root / "docs/images/aer1234_baro_box/good.png").write_bytes(b"replaced")
    assert ei.main(["--repo-root", str(root), "--check"]) == 1
    assert "good.png: sidecar does not match the image" in capsys.readouterr().out


def test_html_is_sanitized_pinned_and_plainly_worded(tmp_path):
    root = _tree(tmp_path)
    out = tmp_path / "site" / "evidence.html"
    assert ei.main(["--repo-root", str(root), "--html", str(out),
                    "--repo", "billmallard/pyEfis", "--sha", "f" * 40]) == 0
    text = out.read_text()
    assert "192.0.2.4" not in text and "203.0.113.9" not in text
    assert ei.find_leaks(text) == []
    assert ("https://raw.githubusercontent.com/billmallard/pyEfis/" + "f" * 40
            + "/docs/images/aer1234_baro_box/good.png") in text
    own = text.replace(ei.html.escape(ei.STANDING_TEXT, quote=True), "").lower()
    for word in ("verified", "certified", "approved", "safe", "compliant", "airworthy"):
        assert not re.search(rf"\b{word}\b", own), word


def test_committed_evidence_has_no_broken_sidecar():
    """Every sidecar committed under docs/ that claims the convention matches its image."""
    broken = [i["path"] for e in ei.scan(_ROOT) for i in e["images"] if i["state"] in ei.BROKEN]
    assert broken == []
