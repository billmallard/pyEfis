#  SPDX-License-Identifier: GPL-2.0-or-later
"""``PlateIndex`` and the approach-to-plate match (PA12, AER-1611).

Every name pair below is real: the CIFP approach ident from FAACIFP18 cycle
2611 (``SUSAP`` records) and the chart names the d-TPP metafile of the same
cycle lists for that airport. Run over the whole cycle, the match finds
exactly one chart for 8,293 of the 8,297 CIFP approaches at an airport with
charts; the four it does not are pinned here too, because the viewer must
fall back to the chart list for them rather than guess.
"""

import sqlite3

import pytest

from pyefis.flightplan import plates
from tests.flightplan import ksba_plates


def _pack(tmp_path, airport, names, name="plates.sqlite"):
    records = [("IAP", chart, f"{airport}{n}.PDF", "", "") for n, chart in enumerate(names)]
    return ksba_plates.build(tmp_path / name, records=records, airport=airport)


KDEN = ["ILS OR LOC RWY 34L", "ILS RWY 34L (SA CAT I)", "ILS RWY 34L (CAT II - III)",
        "RNAV (RNP) Z RWY 07", "RNAV (GPS) Y RWY 07", "ILS OR LOC RWY 07"]
KTEX = ["RNAV (GPS) X RWY 09", "RNAV (GPS) Y RWY 09", "RNAV (GPS) Z RWY 09", "LOC RWY 09",
        "VOR/DME-A"]
KASE = ["RNAV (GPS)-F", "LOC/DME-E", "ROARING FORK VISUAL RWY 15"]
KBJC = ["ILS OR LOC RWY 30R", "RNAV (GPS) RWY 30L", "RNAV (GPS) RWY 30R",
        "VOR/DME RWY 30L/R", "RED ROCKS VISUAL RWY 12L/R"]
KCEC = ["VOR/DME RWY 12", "VOR RWY 12"]
KABQ = ["HI-ILS OR LOC RWY 08", "ILS OR LOC RWY 08"]
KEWR = ["ILS Z OR LOC Z RWY 04L", "RNAV (GPS) Y RWY 04R", "COPTER ILS Y OR LOC Y RWY 04L"]
KDFW = ["ILS Z OR LOC Z RWY 13R", "ILS Z RWY 13R (SA CAT I - II)", "ILS V RWY 13R (CONVERGING)"]
KGUC = ["ILS OR LOC RWY 07", "RNAV (RNP) RWY 07", "RNAV (RNP) RWY 25", "RNAV (GPS)-B", "VOR-A"]
KAPC = ["ILS Z OR LOC Z RWY 01L", "RNAV (GPS) Y RWY 01L", "RNAV (GPS) Z RWY 01L"]
KCNM = ["ILS RWY 03", "RNAV (GPS) RWY 03"]
KJFK = ["COPTER RNAV (GPS) 027", "RNAV (GPS) Z RWY 13L"]


@pytest.mark.parametrize("airport, names, ident, expected", [
    ("KDEN", KDEN, "I34L", "ILS OR LOC RWY 34L"),       # plain beats the CAT notes
    ("KDEN", KDEN, "L34L", "ILS OR LOC RWY 34L"),       # LOC is the chart's other half
    ("KDEN", KDEN, "H07-Z", "RNAV (RNP) Z RWY 07"),
    ("KDEN", KDEN, "R07-Y", "RNAV (GPS) Y RWY 07"),
    ("KDEN", KDEN, "I07", "ILS OR LOC RWY 07"),         # runway 07 is chart RWY 07, not 7L
    ("KTEX", KTEX, "R09-X", "RNAV (GPS) X RWY 09"),
    ("KTEX", KTEX, "R09-Z", "RNAV (GPS) Z RWY 09"),
    ("KTEX", KTEX, "L09", "LOC RWY 09"),
    ("KTEX", KTEX, "VDM-A", "VOR/DME-A"),               # circling
    ("KASE", KASE, "RNV-F", "RNAV (GPS)-F"),
    ("KBJC", KBJC, "D30R", "VOR/DME RWY 30L/R"),        # one chart, two runways
    ("KBJC", KBJC, "D30L", "VOR/DME RWY 30L/R"),
    ("KCEC", KCEC, "D12", "VOR/DME RWY 12"),            # D is VOR/DME before VOR
    ("KABQ", KABQ, "L08", "ILS OR LOC RWY 08"),         # HI- is the noted one
    ("KEWR", KEWR, "I04LY", "COPTER ILS Y OR LOC Y RWY 04L"),  # Y is the copter chart
    ("KDFW", KDFW, "I13RV", "ILS V RWY 13R (CONVERGING)"),
    ("KGUC", KGUC, "R25", "RNAV (RNP) RWY 25"),         # an R charted RNAV (RNP)
    ("KAPC", KAPC, "I01L", None),                       # CIFP says Y, the chart says Z
    ("KCNM", KCNM, "L03", None),                        # no LOC half on the chart
    ("KJFK", KJFK, "R027", None),                       # a copter heading, not a runway
])
def test_the_approach_finds_its_one_chart(tmp_path, airport, names, ident, expected):
    index = plates.PlateIndex(_pack(tmp_path, airport, names))
    plate = index.plate_for_approach(airport, ident)
    assert (plate.chart_name if plate else None) == expected


def test_two_equally_good_charts_are_no_answer(tmp_path):
    index = plates.PlateIndex(_pack(tmp_path, "KXYZ", ["VOR RWY 12", "VOR RWY 12"]))
    assert index.plate_for_approach("KXYZ", "V12") is None


def test_the_pack_letter_overrides_the_ident(tmp_path):
    index = plates.PlateIndex(_pack(tmp_path, "KCEC", KCEC))
    # A V-coded approach whose ident starts with D is read as the pack codes it.
    assert index.plate_for_approach("KCEC", "D12", "V").chart_name == "VOR RWY 12"


def test_chart_alternatives_share_the_runway():
    assert plates.chart_alternatives("ILS Y OR LOC Y RWY 23") == [
        ("ILS", "Y", frozenset({"23"}), ""), ("LOC", "Y", frozenset({"23"}), "")]
    assert plates.chart_alternatives("LOC/DME BC-A") == [("LOC/DME BC", "", frozenset({""}), "A")]


def test_ksba_charts_list_with_the_diagram_first(tmp_path):
    index = plates.PlateIndex(ksba_plates.build(tmp_path / "p.sqlite"))
    assert index.ready
    listed = index.plates_at("ksba")
    assert [pl.chart_code for pl in listed[:4]] == ["APD", "IAP", "IAP", "IAP"]
    assert len(listed) == len(ksba_plates.KSBA_RECORDS)
    assert index.airport_diagram("KSBA").pdf_name == "00378AD.PDF"
    ils = index.plate_for_approach("KSBA", "I07", "I")
    assert (ils.chart_name, ils.amdt_num, ils.cycle) == ("ILS OR LOC RWY 07", "7", "2611")


def test_pdf_bytes_come_back_as_stored(tmp_path):
    index = plates.PlateIndex(ksba_plates.build(tmp_path / "p.sqlite",
                                                pdfs={"00378IL7.PDF": b"%PDF-1.4 x"}))
    assert index.pdf_bytes("00378IL7.PDF") == b"%PDF-1.4 x"
    assert index.pdf_bytes("NOPE.PDF") is None


def test_a_directory_of_region_packs_answers_from_each(tmp_path):
    region = tmp_path / "plates" / "plates-us-west" / "current"
    region.mkdir(parents=True)
    ksba_plates.build(region / "plates.sqlite")
    other = tmp_path / "plates" / "plates-us-central" / "current"
    other.mkdir(parents=True)
    _pack(other, "KDEN", KDEN)
    index = plates.PlateIndex(tmp_path / "plates")
    assert index.plates_at("KSBA") and index.plates_at("KDEN")


@pytest.mark.parametrize("path", [None, "", "/no/such/plates.sqlite"])
def test_no_pack_means_no_charts(path):
    index = plates.PlateIndex(path)
    assert not index.ready
    assert index.plates_at("KSBA") == [] and index.plate_for_approach("KSBA", "I07") is None


def test_a_file_that_is_not_a_plates_pack_is_skipped(tmp_path):
    junk = tmp_path / "junk.sqlite"
    junk.write_bytes(b"this is not sqlite")
    other = tmp_path / "other.sqlite"
    sqlite3.connect(str(other)).execute("CREATE TABLE t (x)").connection.close()
    assert not plates.PlateIndex(junk).ready
    assert not plates.PlateIndex(other).ready
