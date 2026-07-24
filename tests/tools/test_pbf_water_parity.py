#  SPDX-License-Identifier: GPL-2.0-or-later
"""Opt-in parity test for the pbf water fallback (issue #104).

Downloads Geofabrik's prince-edward-island daily shapefile AND pbf
extract, runs the real fallback extraction, and compares the two
layers: per-fclass feature counts and aggregate |ring area|. On
2026-07-23 the match was exact (3,064/3,064 records, area ratio
1.00000); the assertions allow 1% because the shp and pbf daily builds
can be cut hours apart.

Network + pyosmium required, so the test is gated behind
PYEFIS_NET_TESTS=1 and never runs in CI. Set PYEFIS_PARITY_DIR to a
persistent directory to reuse the ~30 MB of downloads across runs
(both download helpers are cache-idempotent).

    PYEFIS_NET_TESTS=1 PYTHONPATH="C:/pylib;src" \
        python -m pytest tests/tools/test_pbf_water_parity.py --no-cov
"""

import collections
import importlib.util
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("PYEFIS_NET_TESTS"),
    reason="network parity test; set PYEFIS_NET_TESTS=1 to run")

shapefile = pytest.importorskip("shapefile")
pytest.importorskip("osmium")

_ROOT = Path(__file__).resolve().parents[2]


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, _ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fw = _load("fetch_geofabrik_water")

STATE = "canada/prince-edward-island"


def _layer_stats(shp_path):
    """Per-fclass record counts + aggregate |ring area| in deg^2."""
    sf = shapefile.Reader(str(shp_path))
    fields = [f[0] for f in sf.fields[1:]]
    fclass_idx = fields.index("fclass")
    counts = collections.Counter()
    area = 0.0
    for item in sf.iterShapeRecords():
        counts[item.record[fclass_idx]] += 1
        pts = item.shape.points
        parts = list(item.shape.parts) + [len(pts)]
        for k in range(len(parts) - 1):
            area += abs(fw._ring_signed_area_xy(pts[parts[k]:parts[k + 1]]))
    return counts, area


def test_pei_pbf_extraction_matches_shp_layer(tmp_path):
    work = Path(os.environ.get("PYEFIS_PARITY_DIR") or tmp_path)
    work.mkdir(parents=True, exist_ok=True)

    zip_path = fw.download_state(STATE, work)
    ref_shp = fw.extract_water_layer(zip_path, work / "ref")
    assert ref_shp is not None

    pbf_path = fw.download_state_pbf(STATE, work)
    twin_shp = fw.extract_water_from_pbf(
        pbf_path, work / "twin" / STATE.replace("/", "-"))

    ref_counts, ref_area = _layer_stats(ref_shp)
    twin_counts, twin_area = _layer_stats(twin_shp)

    assert sum(ref_counts.values()) > 1000  # a real layer, not a stub
    for fclass in sorted(set(ref_counts) | set(twin_counts)):
        a, b = ref_counts[fclass], twin_counts[fclass]
        assert abs(a - b) <= max(2, 0.01 * max(a, b)), \
            f"{fclass}: shp {a} vs pbf {b}"
    assert twin_area == pytest.approx(ref_area, rel=0.01)
