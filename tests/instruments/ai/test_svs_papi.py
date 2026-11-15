"""SVS PAPI (CIFP1 / CAP-123, docs/svs_papi_plan.md).

The GL SVS draws a PAPI only where NASR records one (vgsi_code P2*/P4*), on
the published visual glide path angle and the published side -- replacing the
legacy VirtualVfr PAPI, which painted every runway on an assumed 3 degrees.
These tests drive the pre-GL collector; the draw call itself needs a GL
context and is covered by the bench capture.
"""
import math

import numpy as np
import pytest

from pyefis.instruments.ai.airport_db import AirportRecord, RunwayRecord
from pyefis.instruments.ai.svs import SVSRenderer

FT_PER_DEG = 364491.0
NM_FT = 6076.12
LAT0, LON0, ELEV = 34.0, -118.0, 100.0
RWY_LEN_FT = 5000.0
PPD = 16.0   # ~800 px wide panel at a 50 degree terrain HFOV


def _runway(vgsi="P4L", gpa=3.0, vgsi2=None, gpa2=None):
    """A north-south runway: thr1 at the south end (landing north), thr2 at
    the north end (landing south)."""
    return RunwayRecord(
        airport_id="TST", name="18/36",
        thr1_lat=LAT0, thr1_lon=LON0, thr1_elev_ft=ELEV,
        thr2_lat=LAT0 + RWY_LEN_FT / FT_PER_DEG, thr2_lon=LON0,
        thr2_elev_ft=ELEV,
        length_ft=RWY_LEN_FT, bearing_deg=0.0, width_ft=100.0,
        thr1_vgsi_type=vgsi, thr1_visual_gpa=gpa,
        thr2_vgsi_type=vgsi2, thr2_visual_gpa=gpa2)


class _StubAirportDB:
    ready = True

    def __init__(self, runways):
        self._ap = AirportRecord(icao="KTST", name="Test", ref_lat=LAT0,
                                 ref_lon=LON0, elev_ft=ELEV, runways=runways)

    def airports_in_range(self, lat, lon, range_nm):
        return [self._ap]


def _renderer(runways, **cfg):
    r = SVSRenderer(dict(cfg))
    r.airport_db = _StubAirportDB(runways)
    # Bypass the async worker: hand the collector the airport list directly.
    airports = list(r._airports_in_range(LAT0, LON0))
    r._get_airports_cached = lambda lat, lon: airports
    return r


def _box_lat():
    # Box abeam the 1000 ft aiming point of the thr1 (south) end.
    return LAT0 + 1000.0 / FT_PER_DEG


def _approach(dist_nm, angle_deg, lateral_deg=0.0):
    """Aircraft ``dist_nm`` south of the thr1 box (on the approach side),
    ``lateral_deg`` off the extended centreline, ``angle_deg`` above it."""
    d_ft = dist_nm * NM_FT
    n = -d_ft * math.cos(math.radians(lateral_deg))
    e = d_ft * math.sin(math.radians(lateral_deg))
    lat = _box_lat() + n / FT_PER_DEG
    lon = LON0 + e / (FT_PER_DEG * math.cos(math.radians(_box_lat())))
    alt = ELEV + math.tan(math.radians(angle_deg)) * d_ft
    return lat, lon, alt


def _counts(papi):
    """(red lights, white lights) -- six vertices per light quad."""
    if papi is None:
        return (0, 0)
    red = 0 if papi["red"] is None else len(papi["red"]) // 6
    white = 0 if papi["white"] is None else len(papi["white"]) // 6
    return (red, white)


class TestPapiUnitSettings:
    @pytest.mark.parametrize("angle,expect", [
        (2.3, 4), (2.6, 3), (3.0, 2), (3.3, 1), (3.7, 0)])
    def test_four_box_reads_against_the_published_angle(self, angle, expect):
        assert SVSRenderer._papi_red_count(angle, 3.0, 4) == expect

    def test_published_four_degrees_is_not_the_legacy_three(self):
        # A 3-degree approach to a 4-degree PAPI is low: all red. The
        # legacy renderer, assuming 3 degrees, would have shown 2/2.
        assert SVSRenderer._papi_red_count(3.0, 4.0, 4) == 4
        assert SVSRenderer._papi_red_count(4.0, 4.0, 4) == 2

    @pytest.mark.parametrize("angle,expect", [(2.6, 2), (3.0, 1), (3.4, 0)])
    def test_two_box_reads_one_and_one_on_path(self, angle, expect):
        assert SVSRenderer._papi_red_count(angle, 3.0, 2) == expect

    def test_inboard_unit_has_the_highest_setting(self):
        s = SVSRenderer._papi_settings(3.0, 4)
        assert s == sorted(s, reverse=True)
        assert s[0] == pytest.approx(3.5) and s[-1] == pytest.approx(2.5)


class TestPapiCandidates:
    def test_vgsi_fields_reach_the_runway_dicts(self):
        r = _renderer([_runway("P2R", 3.5)])
        (_l, _a, _b, _e, runways), = r._airports_in_range(LAT0, LON0)
        assert runways[0]["thr1_vgsi_type"] == "P2R"
        assert runways[0]["thr1_visual_gpa"] == 3.5
        assert runways[0]["thr2_vgsi_type"] is None

    @pytest.mark.parametrize("vgsi,gpa", [
        (None, 3.0),        # no VGSI installed
        ("P4L", None),      # PAPI without a published angle -- no guess
        ("V4L", 3.0),       # VASI: not drawn as a PAPI
        ("PSIL", 3.0),      # pulsating VASI
        ("TRIL", 3.0),      # tri-colour VASI
    ])
    def test_only_papi_with_a_published_angle_is_a_candidate(self, vgsi, gpa):
        r = _renderer([_runway(vgsi, gpa)])
        assert r._papi_candidates(LAT0, LON0) == []

    def test_each_runway_end_is_its_own_candidate(self):
        r = _renderer([_runway("P4L", 3.0, "P2R", 3.25)])
        c = r._papi_candidates(LAT0, LON0)
        assert sorted((x["n"], x["gpa"]) for x in c) == [(2, 3.25), (4, 3.0)]


class TestCollectPapi:
    def test_on_path_four_box_shows_two_red_two_white(self):
        r = _renderer([_runway("P4L", 3.0)])
        lat, lon, alt = _approach(3.0, 3.0)
        assert _counts(r._collect_papi(lat, lon, alt, 0.0, PPD)) == (2, 2)

    @pytest.mark.parametrize("angle,expect", [
        (2.0, (4, 0)), (2.7, (3, 1)), (3.35, (1, 3)), (4.2, (0, 4))])
    def test_low_adds_red_high_adds_white(self, angle, expect):
        r = _renderer([_runway("P4L", 3.0)])
        lat, lon, alt = _approach(3.0, angle)
        assert _counts(r._collect_papi(lat, lon, alt, 0.0, PPD)) == expect

    def test_steep_published_angle_reads_low_on_a_three_degree_path(self):
        r = _renderer([_runway("P4L", 4.0)])
        lat, lon, alt = _approach(3.0, 3.0)
        assert _counts(r._collect_papi(lat, lon, alt, 0.0, PPD)) == (4, 0)

    def test_two_box_row(self):
        r = _renderer([_runway("P2L", 3.0)])
        lat, lon, alt = _approach(2.0, 3.0)
        assert _counts(r._collect_papi(lat, lon, alt, 0.0, PPD)) == (1, 1)

    def test_no_vgsi_draws_nothing(self):
        r = _renderer([_runway(None, None)])
        lat, lon, alt = _approach(3.0, 3.0)
        assert r._collect_papi(lat, lon, alt, 0.0, PPD) is None

    @pytest.mark.parametrize("side,west", [("P4L", True), ("P4R", False)])
    def test_row_sits_on_the_published_side(self, side, west):
        r = _renderer([_runway(side, 3.0)])
        lat, lon, alt = _approach(3.0, 3.0)
        papi = r._collect_papi(lat, lon, alt, 0.0, PPD)
        lons = np.concatenate([papi["red"], papi["white"]])[:, 1]
        # Landing north: left is west of the centreline (lon < LON0).
        assert (lons < LON0).all() if west else (lons > LON0).all()

    def test_red_units_are_inboard_on_path(self):
        r = _renderer([_runway("P4R", 3.0)])
        lat, lon, alt = _approach(3.0, 3.0)
        papi = r._collect_papi(lat, lon, alt, 0.0, PPD)
        assert papi["red"][:, 1].max() < papi["white"][:, 1].min()

    def test_outside_the_azimuth_coverage_draws_nothing(self):
        r = _renderer([_runway("P4L", 3.0)])
        lat, lon, alt = _approach(3.0, 3.0, lateral_deg=8.0)
        assert r._collect_papi(lat, lon, alt, 0.0, PPD) is not None
        lat, lon, alt = _approach(3.0, 3.0, lateral_deg=14.0)
        assert r._collect_papi(lat, lon, alt, 0.0, PPD) is None

    def test_beyond_papi_range_draws_nothing(self):
        r = _renderer([_runway("P4L", 3.0)])
        lat, lon, alt = _approach(4.5, 3.0)
        assert r._collect_papi(lat, lon, alt, 0.0, PPD) is not None
        lat, lon, alt = _approach(6.0, 3.0)
        assert r._collect_papi(lat, lon, alt, 0.0, PPD) is None

    def test_past_the_box_draws_nothing(self):
        r = _renderer([_runway("P4L", 3.0)])
        # North of the box, on the runway: the departure side for thr1.
        lat = _box_lat() + 500.0 / FT_PER_DEG
        assert r._collect_papi(lat, LON0, ELEV + 50.0, 0.0, PPD) is None

    def test_box_behind_the_nose_draws_nothing(self):
        r = _renderer([_runway("P4L", 3.0)])
        lat, lon, alt = _approach(3.0, 3.0)
        assert r._collect_papi(lat, lon, alt, 180.0, PPD) is None

    def test_disabled_by_config(self):
        r = _renderer([_runway("P4L", 3.0)], papi=False)
        lat, lon, alt = _approach(3.0, 3.0)
        assert r._collect_papi(lat, lon, alt, 0.0, PPD) is None

    def test_far_lights_floor_at_a_visible_pixel_size(self):
        r = _renderer([_runway("P4L", 3.0)])
        lat, lon, alt = _approach(4.0, 3.0)
        papi = r._collect_papi(lat, lon, alt, 0.0, PPD)
        quad = papi["red"][:6]
        height_ft = float(quad[:, 2].max() - quad[:, 2].min())
        dist_ft = 4.0 * NM_FT
        px = height_ft / (dist_ft / (57.29577951308232 * PPD))
        assert px == pytest.approx(SVSRenderer._PAPI_LIGHT_PX, rel=0.01)


class TestPapiTerrainMask:
    def test_terrain_between_aircraft_and_box_hides_it(self, tmp_path):
        # A 2000 m plateau everywhere, aircraft at a few hundred feet MSL:
        # every sight line is through terrain.
        root = tmp_path / "tiles"
        data = np.full((1201, 1201), 2000, dtype=">i2")
        for lat in (33, 34):              # the runway sits on a tile corner
            (root / f"N{lat}").mkdir(parents=True, exist_ok=True)
            for lon in (118, 119):
                data.tofile(root / f"N{lat}" / f"N{lat}W{lon}.hgt")
        r = _renderer([_runway("P4L", 3.0)], tile_path=str(root))
        lat, lon, alt = _approach(3.0, 3.0)
        assert r._collect_papi(lat, lon, alt, 0.0, PPD) is None
