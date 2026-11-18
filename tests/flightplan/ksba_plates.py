#  SPDX-License-Identifier: GPL-2.0-or-later
"""A ``plates`` pack holding KSBA's d-TPP catalog records, for the PA12
tests (AER-1611).

The records are the real d-TPP metafile's for KSBA, cycle 2611
(``https://aeronav.faa.gov/d-tpp/2611/xml_data/d-TPP_Metafile.xml``,
parsed by makerplane-data ``packtools.dtpp.parse_metafile``), copied here
as literals. The PDFs are not the FAA's: each test passes the bytes it
needs (a page drawn with ``QPdfWriter``, or junk), so no 400 KB chart is
committed. :data:`SCHEMA` is makerplane-data's, from
``packtools/build/plates.py`` (PA11).
"""

import hashlib
import sqlite3

SCHEMA = """
CREATE TABLE plate_files (pdf_name TEXT PRIMARY KEY, sha256 TEXT NOT NULL,
    bytes INTEGER NOT NULL, data BLOB NOT NULL);
CREATE TABLE plates (id INTEGER PRIMARY KEY, state TEXT NOT NULL, city TEXT NOT NULL,
    apt_ident TEXT NOT NULL, icao_ident TEXT NOT NULL, military INTEGER NOT NULL,
    chart_code TEXT NOT NULL, chart_name TEXT NOT NULL, procuid TEXT,
    pdf_name TEXT NOT NULL REFERENCES plate_files(pdf_name), amdt_num TEXT, amdt_date TEXT,
    cycle TEXT NOT NULL);
CREATE INDEX idx_plates_airport ON plates(icao_ident, chart_code);
CREATE INDEX idx_plates_pdf ON plates(pdf_name);
CREATE TABLE plate_georef (pdf_name TEXT PRIMARY KEY REFERENCES plate_files(pdf_name),
    status TEXT NOT NULL, residual_nm REAL, control_points INTEGER NOT NULL,
    transform_a REAL, transform_b REAL, transform_tx REAL, transform_ty REAL,
    origin_lat REAL, origin_lon REAL, detail TEXT NOT NULL);
"""

# (chart_code, chart_name, pdf_name, amdt_num, amdt_date), in metafile order.
KSBA_RECORDS = [
    ("MIN", "TAKEOFF MINIMUMS", "SW3TO.PDF", "", ""),
    ("MIN", "DIVERSE VECTOR AREA", "SW3TO.PDF", "", ""),
    ("MIN", "ALTERNATE MINIMUMS", "SW3ALT.PDF", "", ""),
    ("HOT", "HOT SPOT", "SW3HOTSPOT.PDF", "", ""),
    ("STR", "PITBL TWO (RNAV)", "00378PITBL.PDF", "", ""),
    ("IAP", "ILS OR LOC RWY 07", "00378IL7.PDF", "7", ""),
    ("IAP", "RNAV (GPS) RWY 07", "00378R7.PDF", "2", "03/19/2026"),
    ("IAP", "VOR RWY 25", "00378V25.PDF", "8", ""),
    ("APD", "AIRPORT DIAGRAM", "00378AD.PDF", "", ""),
    ("DP", "FLOUT FIVE", "00378FLOUT.PDF", "", ""),
    ("DP", "GAUCH THREE (RNAV)", "00378GAUCH.PDF", "", ""),
    ("DP", "HABUT FOUR", "00378HABUT.PDF", "", ""),
    ("DP", "KWANG SIX", "00378KWANG.PDF", "", ""),
    ("DP", "MISHN FIVE (RNAV)", "00378MISHN.PDF", "", ""),
    ("DP", "SANTA BARBARA FIVE", "00378SANTABARBARA.PDF", "", ""),
    ("DP", "SANTA BARBARA FIVE, CONT.1", "00378SANTABARBARA_C.PDF", "", ""),
]


def build(path, pdfs=None, cycle="2611", records=KSBA_RECORDS, airport="KSBA", icao=True):
    """Write a plates pack to *path*. *pdfs* maps a pdf_name to its bytes; a
    record whose PDF is not given gets a few junk bytes. With ``icao=False``
    the airport is filed the way the metafile files one with no ICAO ident:
    ``apt_ident`` is *airport* and ``icao_ident`` is empty."""
    apt_ident, icao_ident = (airport[1:], airport) if icao else (airport, "")
    pdfs = pdfs or {}
    con = sqlite3.connect(str(path))
    try:
        con.executescript(SCHEMA)
        for name in dict.fromkeys(r[2] for r in records):
            data = pdfs.get(name, b"not a pdf")
            con.execute("INSERT INTO plate_files VALUES (?, ?, ?, ?)",
                        (name, hashlib.sha256(data).hexdigest(), len(data), data))
        for code, chart, name, amdt, date in records:
            con.execute(
                "INSERT INTO plates (state, city, apt_ident, icao_ident, military, chart_code, "
                "chart_name, procuid, pdf_name, amdt_num, amdt_date, cycle) "
                "VALUES ('CA', 'SANTA BARBARA', ?, ?, 0, ?, ?, NULL, ?, ?, ?, ?)",
                (apt_ident, icao_ident, code, chart, name, amdt or None, date or None, cycle))
        con.commit()
    finally:
        con.close()
    return path
