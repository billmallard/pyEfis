#  SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for tools/fetch_geofabrik_water.py.

Issue #106 double-append: the post-loop cache sweep (meant to serve
--build-only, whose skipped download loop leaves ``shp_paths`` empty)
also ran on the normal path, where the loop had already appended every
requested area. Every shapefile then reached build_water_db.py twice,
and its plain INSERTs doubled each inland polygon in the output (the
2026q2r6 candidate: 128 args for 64 areas, 18.9 GB vs the canonical
4 GB). Those tests pin the input-assembly contract: each --osm-water
arg exactly once, on every assembly path.

Issue #104 pbf fallback: regions past Geofabrik's free-shapefile size
cap (BC + Nunavut) 404 on shp.zip; the tool falls back to the .osm.pbf
extract and writes a shapefile twin of the water layer. Those tests
pin the routing (404 and only 404 triggers the fallback), the
fail-loud contract (zero extracted polygons is a hard error), the
tag->fclass mapping (empirically derived, see water_fclass), and that
the written twin is consumable by the same pyshp reader
build_water_db.py uses. Network-touching parity lives separately in
test_pbf_water_parity.py (opt-in).

Plain pytest + tmp_path + monkeypatch; the builder subprocess is
captured, never run, so there are no build-time deps to skip on.
"""

import importlib.util
import sys
import urllib.error
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, _ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fw = _load("fetch_geofabrik_water")

LAYER = fw.WATER_LAYER_FILES[0]


def _seed_cache(cache_dir, areas):
    """Pre-extract the given areas so the download loop resume path
    (and the --build-only sweep) sees them as done."""
    for area in areas:
        d = cache_dir / "extracted" / area.replace("/", "-")
        d.mkdir(parents=True)
        (d / LAYER).write_bytes(b"stub")


def _run_main(monkeypatch, tmp_path, states, extra_args=(), capture=None):
    """Run main() against a tmp cache with the builder call captured.
    Returns the list of --osm-water argument values it would pass;
    ``capture`` (a list) additionally receives the full builder cmd."""
    cache = tmp_path / "cache"
    out = tmp_path / "out.sqlite"
    calls = []

    def _fake_builder(cmd):
        # main() stats the output after the builder returns.
        calls.append(cmd)
        out.write_bytes(b"stub")

    monkeypatch.setattr(fw.subprocess, "check_call", _fake_builder)
    monkeypatch.setattr(sys, "argv", [
        "fetch_geofabrik_water.py",
        "--states", states,
        "--cache-dir", str(cache),
        "--output", str(out),
        "--ocean-shp", "", "--ne-lakes", "",
        *extra_args,
    ])
    fw.main()
    assert len(calls) == 1
    cmd = calls[0]
    if capture is not None:
        capture.append(cmd)
    return [cmd[i + 1] for i, a in enumerate(cmd) if a == "--osm-water"]


def test_resume_path_passes_each_shapefile_once(monkeypatch, tmp_path):
    # Fully-cached normal run (the 2026q2r6 scenario): the sweep must
    # not re-append what the resume loop already added.
    (tmp_path / "cache").mkdir()
    _seed_cache(tmp_path / "cache", ["texas", "oklahoma"])
    paths = _run_main(monkeypatch, tmp_path, "texas,oklahoma")
    assert len(paths) == 2
    assert len(set(paths)) == 2


def test_build_only_passes_each_shapefile_once(monkeypatch, tmp_path):
    (tmp_path / "cache").mkdir()
    _seed_cache(tmp_path / "cache", ["texas", "oklahoma"])
    paths = _run_main(monkeypatch, tmp_path, "texas,oklahoma",
                      extra_args=("--build-only",))
    assert len(paths) == 2
    assert len(set(paths)) == 2


def test_normal_path_excludes_unrequested_cached_areas(monkeypatch,
                                                       tmp_path):
    # A single-state run over a well-stocked cache must build that
    # state only -- the old sweep silently included every cached area.
    (tmp_path / "cache").mkdir()
    _seed_cache(tmp_path / "cache", ["texas", "oklahoma", "kansas"])
    paths = _run_main(monkeypatch, tmp_path, "texas")
    assert len(paths) == 1
    assert paths[0].endswith(str(Path("texas") / LAYER)) or \
        "texas" in paths[0]


def test_duplicate_states_arg_collapses(monkeypatch, tmp_path):
    (tmp_path / "cache").mkdir()
    _seed_cache(tmp_path / "cache", ["texas"])
    paths = _run_main(monkeypatch, tmp_path, "texas,texas")
    assert len(paths) == 1


def test_declutter_filters_pass_through(monkeypatch, tmp_path):
    # --min-area-km2 / --keep-fclass reach the builder cmd verbatim
    # (and stay absent at their defaults, matching prior behavior).
    (tmp_path / "cache").mkdir()
    _seed_cache(tmp_path / "cache", ["texas"])
    cmds = []
    _run_main(monkeypatch, tmp_path, "texas",
              extra_args=("--min-area-km2", "0.5",
                          "--keep-fclass", "water", "reservoir"),
              capture=cmds)
    cmd = cmds[0]
    i = cmd.index("--min-area-km2")
    assert cmd[i + 1] == "0.5"
    j = cmd.index("--keep-fclass")
    assert cmd[j + 1:j + 3] == ["water", "reservoir"]

    cmds2 = []
    _run_main(monkeypatch, tmp_path, "texas", capture=cmds2)
    assert "--min-area-km2" not in cmds2[0]
    assert "--keep-fclass" not in cmds2[0]


# ---------------------------------------------------------------------------
# Issue #104: pbf-extraction fallback for shp-less regions


def _http404(*_a, **_k):
    raise urllib.error.HTTPError("http://x/shp.zip", 404, "Not Found",
                                 None, None)


def test_water_fclass_mapping():
    # Pinned to the empirical PEI shapefile<->pbf osm_id join
    # (3,064/3,064 matched, 2026-07-23) -- see water_fclass docstring.
    wf = fw.water_fclass
    assert wf({"natural": "water"}) == ("water", 8200)
    assert wf({"natural": "water", "water": "pond"}) == ("water", 8200)
    assert wf({"natural": "water", "water": "river"}) == \
        ("riverbank", 8202)
    assert wf({"natural": "water", "water": "reservoir"}) == \
        ("reservoir", 8201)
    # natural=water wins over a wetland subtag (observed on PEI).
    assert wf({"natural": "water", "wetland": "tidalflat"}) == \
        ("water", 8200)
    assert wf({"natural": "wetland"}) == ("wetland", 8220)
    assert wf({"natural": "wetland", "wetland": "saltmarsh"}) == \
        ("wetland_saltmarsh", 8223)
    # Unknown subtype folds into plain wetland, never invents a class.
    assert wf({"natural": "wetland", "wetland": "no-such"}) == \
        ("wetland", 8220)
    assert wf({"landuse": "reservoir"}) == ("reservoir", 8201)
    assert wf({"waterway": "riverbank"}) == ("riverbank", 8202)
    assert wf({"waterway": "dock"}) == ("dock", 8203)
    assert wf({"natural": "glacier"}) == ("glacier", 8211)
    # NOT in the layer: bare landuse=basin and bare water=* were both
    # present in the PEI pbf and absent from the shp layer.
    assert wf({"landuse": "basin"}) is None
    assert wf({"water": "pond"}) is None
    assert wf({"natural": "beach"}) is None
    assert wf({}) is None


def _synthetic_areas(_pbf_path):
    # An island lake (outer + hole, GeoJSON winding: outer CCW, hole
    # CW) and a plain pond, GeoJSON MultiPolygon coordinates.
    lake = [[[(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0),
              (0.0, 0.0)],
             [(1.0, 1.0), (1.0, 2.0), (2.0, 2.0), (2.0, 1.0),
              (1.0, 1.0)]]]
    pond = [[[(10.0, 10.0), (11.0, 10.0), (11.0, 11.0), (10.0, 10.0)]]]
    yield ("123", "Big Lake", "water", 8200, lake)
    yield ("456", "", "reservoir", 8201, pond)


def test_extract_writes_consumable_layer(monkeypatch, tmp_path):
    shapefile = pytest.importorskip("shapefile")
    monkeypatch.setattr(fw, "iter_pbf_water_areas", _synthetic_areas)
    out = fw.extract_water_from_pbf(tmp_path / "x-latest.osm.pbf",
                                    tmp_path / "extracted")
    assert out.name == LAYER
    # All five layer files land under the canonical names; no partial
    # temp files survive.
    for name in fw.WATER_LAYER_FILES:
        assert (tmp_path / "extracted" / name).exists()
    assert not list((tmp_path / "extracted").glob("*_partial*"))
    # Read back with the same pyshp build_water_db.py uses.
    sf = shapefile.Reader(str(out))
    fields = [f[0] for f in sf.fields[1:]]
    assert fields == ["osm_id", "code", "fclass", "name"]
    shapes = sf.shapes()
    assert len(shapes) == 2
    parts = list(shapes[0].parts) + [len(shapes[0].points)]
    assert len(parts) - 1 == 2  # outer + island hole in one record
    rings = [shapes[0].points[parts[k]:parts[k + 1]]
             for k in range(len(parts) - 1)]
    # Shapefile winding: outer CW (negative signed area), hole CCW.
    assert fw._ring_signed_area_xy(rings[0]) < 0
    assert fw._ring_signed_area_xy(rings[1]) > 0
    assert list(sf.record(0)) == ["123", 8200, "water", "Big Lake"]
    assert list(sf.record(1)) == ["456", 8201, "reservoir", ""]


def test_extract_zero_features_fails_loud(monkeypatch, tmp_path):
    pytest.importorskip("shapefile")
    monkeypatch.setattr(fw, "iter_pbf_water_areas", lambda _p: iter(()))
    with pytest.raises(RuntimeError, match="0 water"):
        fw.extract_water_from_pbf(tmp_path / "x-latest.osm.pbf",
                                  tmp_path / "extracted")
    # Nothing half-written left behind for the resume path to trust.
    assert not list((tmp_path / "extracted").glob("*"))


def test_fallback_on_404(monkeypatch, tmp_path):
    # shp.zip 404 -> pbf fallback; the extracted twin reaches the
    # builder exactly once and the pbf is cleaned up like a zip.
    cache = tmp_path / "cache"
    state_flat = "canada-british-columbia"
    pbf = cache / (state_flat + "-latest.osm.pbf")

    def _fake_pbf_download(state, cache_dir):
        assert state == "canada/british-columbia"
        out = cache_dir / (state.replace("/", "-") + "-latest.osm.pbf")
        out.write_bytes(b"\x00\x00stub")
        return out

    def _fake_extract(pbf_path, out_dir):
        assert pbf_path == pbf
        out_dir.mkdir(parents=True)
        shp = out_dir / LAYER
        shp.write_bytes(b"stub")
        return shp

    monkeypatch.setattr(fw, "download_state", _http404)
    monkeypatch.setattr(fw, "download_state_pbf", _fake_pbf_download)
    monkeypatch.setattr(fw, "extract_water_from_pbf", _fake_extract)
    paths = _run_main(monkeypatch, tmp_path, "canada/british-columbia")
    assert len(paths) == 1
    assert paths[0].endswith(LAYER) and state_flat in paths[0]
    assert not pbf.exists()  # deleted after extraction (no --keep-zips)


def test_fallback_resume_skips_download(monkeypatch, tmp_path):
    # A previously fallback-extracted region resumes exactly like a
    # shp-extracted one: no download of any kind on the second run.
    (tmp_path / "cache").mkdir()
    _seed_cache(tmp_path / "cache", ["canada/nunavut"])

    def _boom(*_a, **_k):
        raise AssertionError("no download expected on resume")

    monkeypatch.setattr(fw, "download_state", _boom)
    monkeypatch.setattr(fw, "download_state_pbf", _boom)
    paths = _run_main(monkeypatch, tmp_path, "canada/nunavut")
    assert len(paths) == 1


def test_no_fallback_on_other_http_errors(monkeypatch, tmp_path):
    # A 500 (or any non-404) is not "Geofabrik stopped shipping shp" --
    # it must fail the region, never silently switch data sources.
    def _http500(*_a, **_k):
        raise urllib.error.HTTPError("http://x/shp.zip", 500, "Boom",
                                     None, None)

    def _no_fallback(*_a, **_k):
        raise AssertionError("pbf fallback must not run on a 500")

    monkeypatch.setattr(fw, "download_state", _http500)
    monkeypatch.setattr(fw, "download_state_pbf", _no_fallback)
    monkeypatch.setattr(fw.subprocess, "check_call",
                        lambda cmd: pytest.fail("builder must not run"))
    monkeypatch.setattr(sys, "argv", [
        "fetch_geofabrik_water.py", "--states", "texas",
        "--cache-dir", str(tmp_path / "cache"),
        "--output", str(tmp_path / "out.sqlite"),
        "--ocean-shp", "", "--ne-lakes", "",
    ])
    with pytest.raises(SystemExit) as exc:
        fw.main()
    assert exc.value.code == 1


def test_fallback_failure_fails_loud(monkeypatch, tmp_path):
    # 404 routes to the fallback, but a failed extraction still fails
    # the whole run: no pack with a silent hole where BC should be.
    def _bad_extract(*_a, **_k):
        raise RuntimeError("x-latest.osm.pbf: pbf extraction produced "
                           "0 water polygons")

    def _fake_pbf_download(state, cache_dir):
        out = cache_dir / (state.replace("/", "-") + "-latest.osm.pbf")
        out.write_bytes(b"\x00\x00stub")
        return out

    monkeypatch.setattr(fw, "download_state", _http404)
    monkeypatch.setattr(fw, "download_state_pbf", _fake_pbf_download)
    monkeypatch.setattr(fw, "extract_water_from_pbf", _bad_extract)
    monkeypatch.setattr(fw.subprocess, "check_call",
                        lambda cmd: pytest.fail("builder must not run"))
    monkeypatch.setattr(sys, "argv", [
        "fetch_geofabrik_water.py", "--states", "canada/nunavut",
        "--cache-dir", str(tmp_path / "cache"),
        "--output", str(tmp_path / "out.sqlite"),
        "--ocean-shp", "", "--ne-lakes", "",
    ])
    with pytest.raises(SystemExit) as exc:
        fw.main()
    assert exc.value.code == 1
