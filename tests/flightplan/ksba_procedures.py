#  SPDX-License-Identifier: GPL-2.0-or-later
"""A ``procedures`` pack holding KSBA's real procedures, for the PA7 tests
(AER-1606).

The rows are decoder output, not typed by hand: makerplane-data
``packtools.build.procedures.build_procedures`` (commit e84a681) run over
that repo's golden CIFP fixture ``tests/fixtures/cifp/FAACIFP18`` (AIRAC
2609), then copied here as literals. They are the ILS RWY 7 (``I07``: the
GOLET and GVO transitions, each with an ``FC`` leg, and a final whose
missed approach climbs on a ``CA`` and holds at GOLET for one minute), the
FLOUT5 departure (vector legs off each runway) and the PITBL2 arrival.

:func:`build` writes them, with makerplane-data's schema, to a sqlite file.
"""

import sqlite3

SCHEMA = """
CREATE TABLE procedures (id INTEGER PRIMARY KEY, airport TEXT NOT NULL, kind TEXT NOT NULL,
    ident TEXT NOT NULL, runway TEXT, approach_type TEXT, rnp REAL, cycle TEXT NOT NULL);
CREATE TABLE transitions (id INTEGER PRIMARY KEY, proc_id INTEGER NOT NULL, role TEXT NOT NULL,
    ident TEXT);
CREATE TABLE legs (transition_id INTEGER NOT NULL, seq INTEGER NOT NULL, path_term TEXT NOT NULL,
    fix_id TEXT, fix_lat REAL, fix_lon REAL, fix_type TEXT, recd_navaid TEXT, theta REAL,
    rho REAL, course REAL, dist_nm REAL, time_min REAL, alt_desc TEXT, alt1_ft INTEGER,
    alt2_ft INTEGER, speed_kt INTEGER, turn_dir TEXT, rnp REAL, flags INTEGER NOT NULL,
    centre_fix TEXT, centre_lat REAL, centre_lon REAL, arc_radius_nm REAL);
CREATE INDEX idx_proc_airport ON procedures(airport, kind);
CREATE INDEX idx_trans_proc ON transitions(proc_id);
CREATE INDEX idx_legs_trans ON legs(transition_id, seq);
"""

# The KSBA airport reference point (NASR, as in test_waypoints.py).
KSBA = (34.42621, -119.84037)

PROCEDURES = [
    (1, 'KSBA', 'sid', 'FLOUT5', None, None, None, '2609'),
    (2, 'KSBA', 'star', 'PITBL2', None, None, None, '2609'),
    (3, 'KSBA', 'approach', 'I07', '07', 'I', None, '2609'),
]
TRANSITIONS = [
    (1, 1, 'runway', 'RW07'),
    (2, 1, 'runway', 'RW15B'),
    (3, 1, 'runway', 'RW25'),
    (4, 1, 'enroute', 'GVO'),
    (5, 1, 'enroute', 'RZS'),
    (6, 1, 'enroute', 'VTU'),
    (7, 2, 'enroute', 'HEC'),
    (8, 2, 'enroute', 'PORPS'),
    (9, 2, 'common', None),
    (10, 2, 'runway', 'RW07'),
    (11, 2, 'runway', 'RW25'),
    (12, 3, 'enroute', 'GOLET'),
    (13, 3, 'enroute', 'GVO'),
    (14, 3, 'common', None),
]
LEGS = [
    (1, 10, 'VA', None, None, None, None, None, None, None, 75.0, None, None, '+', 413, None, None, None, None, 0, None, None, None, None),
    (1, 20, 'CI', None, None, None, None, None, None, None, 227.0, None, None, None, None, None, None, 'R', None, 0, None, None, None, None),
    (1, 30, 'CF', 'FLOUT', 34.25758889, -119.95320278, 'waypoint', 'RZS', 197.0, 17.6, 197.0, 11.0, None, None, None, None, None, None, None, 0, None, None, None, None),
    (2, 10, 'VA', None, None, None, None, None, None, None, 152.0, None, None, '+', 413, None, None, None, None, 0, None, None, None, None),
    (2, 20, 'CF', 'FLOUT', 34.25758889, -119.95320278, 'waypoint', 'RZS', 197.0, 17.6, 197.0, 11.0, None, None, None, None, None, None, None, 0, None, None, None, None),
    (3, 10, 'VA', None, None, None, None, None, None, None, 255.0, None, None, '+', 413, None, None, None, None, 0, None, None, None, None),
    (3, 20, 'CI', None, None, None, None, None, None, None, 167.0, None, None, None, None, None, None, None, None, 0, None, None, None, None),
    (3, 30, 'CF', 'FLOUT', 34.25758889, -119.95320278, 'waypoint', 'RZS', 197.0, 17.6, 197.0, 11.0, None, None, None, None, None, None, None, 0, None, None, None, None),
    (4, 10, 'FC', 'FLOUT', 34.25758889, -119.95320278, 'waypoint', 'GVO', 141.3, 17.8, 321.0, 15.0, None, '+', 6000, None, None, None, None, 0, None, None, None, None),
    (4, 20, 'CF', 'GVO', 34.53131944, -120.09108889, 'vor', 'GVO', 0.0, 0.0, 321.0, 3.0, None, None, None, None, None, None, None, 0, None, None, None, None),
    (5, 10, 'FC', 'FLOUT', 34.25758889, -119.95320278, 'waypoint', 'RZS', 197.0, 17.6, 17.0, 14.0, None, '+', 6000, None, None, None, None, 0, None, None, None, None),
    (5, 20, 'CF', 'RZS', 34.50953333, -119.77098889, 'vor', 'RZS', 0.0, 0.0, 17.0, 4.0, None, None, None, None, None, None, None, 0, None, None, None, None),
    (6, 10, 'IF', 'FLOUT', 34.25758889, -119.95320278, 'waypoint', None, None, None, None, None, None, None, None, None, None, None, None, 0, None, None, None, None),
    (6, 20, 'TF', 'VTU', 34.11506389, -119.0495, 'vor', None, None, None, None, None, None, None, None, None, None, None, None, 0, None, None, None, None),
    (7, 10, 'IF', 'HEC', 34.79701944, -116.46292222, 'vor', None, None, None, None, None, None, None, None, None, None, None, None, 0, None, None, None, None),
    (7, 20, 'TF', 'FRIRR', 34.50011667, -118.37847778, 'waypoint', None, None, None, None, None, None, None, None, None, None, None, None, 0, None, None, None, None),
    (7, 30, 'TF', 'HMBOY', 34.37159722, -118.8417, 'waypoint', None, None, None, None, None, None, None, 24000, None, None, None, None, 0, None, None, None, None),
    (7, 40, 'TF', 'PITBL', 34.35308611, -119.10994444, 'waypoint', None, None, None, None, None, None, '+', 21000, None, None, None, None, 0, None, None, None, None),
    (8, 10, 'IF', 'PORPS', 34.27640278, -118.14697778, 'waypoint', None, None, None, None, None, None, '-', 30000, None, None, None, None, 0, None, None, None, None),
    (8, 20, 'TF', 'HMBOY', 34.37159722, -118.8417, 'waypoint', None, None, None, None, None, None, None, 24000, None, None, None, None, 0, None, None, None, None),
    (8, 30, 'TF', 'PITBL', 34.35308611, -119.10994444, 'waypoint', None, None, None, None, None, None, '+', 21000, None, None, None, None, 0, None, None, None, None),
    (9, 10, 'IF', 'PITBL', 34.35308611, -119.10994444, 'waypoint', None, None, None, None, None, None, '+', 21000, None, None, None, None, 0, None, None, None, None),
    (9, 20, 'TF', 'TELLA', 34.37064444, -119.49486389, 'waypoint', None, None, None, None, None, None, None, None, None, None, None, None, 0, None, None, None, None),
    (10, 10, 'IF', 'TELLA', 34.37064444, -119.49486389, 'waypoint', None, None, None, None, None, None, None, None, None, None, None, None, 0, None, None, None, None),
    (10, 20, 'TF', 'STBBZ', 34.37166667, -119.68, 'waypoint', None, None, None, None, None, None, None, None, None, None, None, None, 0, None, None, None, None),
    (10, 30, 'TF', 'HHOME', 34.35895556, -119.84296389, 'waypoint', None, None, None, None, None, None, '+', 9000, None, None, None, None, 0, None, None, None, None),
    (10, 40, 'TF', 'LCLRK', 34.34119167, -120.16931111, 'waypoint', None, None, None, None, None, None, None, 4000, None, None, None, None, 1, None, None, None, None),
    (10, 50, 'FM', 'LCLRK', 34.34119167, -120.16931111, 'waypoint', 'RZS', 229.1, 22.2, 250.7, None, None, None, None, None, None, None, None, 0, None, None, None, None),
    (11, 10, 'IF', 'TELLA', 34.37064444, -119.49486389, 'waypoint', None, None, None, None, None, None, None, None, None, None, None, None, 0, None, None, None, None),
    (11, 20, 'TF', 'STBBZ', 34.37166667, -119.68, 'waypoint', None, None, None, None, None, None, None, None, None, None, None, None, 0, None, None, None, None),
    (11, 30, 'TF', 'HHOME', 34.35895556, -119.84296389, 'waypoint', None, None, None, None, None, None, '+', 9000, None, None, None, None, 0, None, None, None, None),
    (11, 40, 'TF', 'LCLRK', 34.34119167, -120.16931111, 'waypoint', None, None, None, None, None, None, None, 4000, None, None, None, None, 1, None, None, None, None),
    (11, 50, 'FM', 'LCLRK', 34.34119167, -120.16931111, 'waypoint', 'RZS', 229.1, 22.2, 250.7, None, None, None, None, None, None, None, None, 0, None, None, None, None),
    (12, 10, 'IF', 'GOLET', 34.28135, -119.864375, 'waypoint', None, None, None, None, None, None, None, None, None, None, None, None, 2, None, None, None, None),
    (12, 20, 'TF', 'LOBER', 34.26329722, -120.08545833, 'waypoint', None, None, None, None, None, None, '+', 4000, None, None, None, None, 0, None, None, None, None),
    (12, 30, 'FC', 'LOBER', 34.26329722, -120.08545833, 'waypoint', 'GVO', 163.0, 16.1, 343.0, 7.5, None, '+', 3500, None, None, None, None, 0, None, None, None, None),
    (12, 40, 'CF', 'HABUT', 34.42236944, -120.08879444, 'waypoint', 'ISBA', 254.6, 12.9, 343.0, 2.0, None, '+', 3500, None, None, None, None, 0, None, None, None, None),
    (13, 10, 'IF', 'GVO', 34.53131944, -120.09108889, 'vor', None, None, None, None, None, None, None, None, None, None, None, None, 2, None, None, None, None),
    (13, 20, 'TF', 'YONNI', 34.48125, -120.09003333, 'waypoint', None, None, None, None, None, None, '+', 5200, None, None, None, None, 0, None, None, None, None),
    (13, 30, 'FC', 'YONNI', 34.48125, -120.09003333, 'waypoint', 'GVO', 163.0, 3.0, 163.0, 1.5, None, '+', 3500, None, None, None, None, 0, None, None, None, None),
    (13, 40, 'CF', 'HABUT', 34.42236944, -120.08879444, 'waypoint', 'ISBA', 254.6, 12.9, 163.0, 2.0, None, '+', 3500, None, None, None, None, 0, None, None, None, None),
    (14, 10, 'IF', 'HABUT', 34.42236944, -120.08879444, 'waypoint', 'ISBA', 254.6, 12.9, None, None, None, 'J', 3500, 1800, None, None, None, 4, None, None, None, None),
    (14, 11, 'CF', 'GOYED', 34.42389722, -120.02124167, 'waypoint', 'ISBA', 254.6, 9.5, 75.0, 3.4, None, '+', 2600, None, None, None, None, 0, None, None, None, None),
    (14, 20, 'CF', 'NAPPS', 34.42515, -119.96445833, 'waypoint', 'ISBA', 254.6, 6.7, 75.0, 2.8, None, 'H', 1800, 1800, None, None, None, 4, 'RZS', 34.50953333, -119.77098889, None),
    (14, 30, 'CF', 'RW07', 34.4275, -119.85464167, 'runway', 'ISBA', 254.6, 1.2, 75.0, 5.5, None, None, 64, None, None, None, None, 9, None, None, None, None),
    (14, 40, 'CA', None, None, None, None, None, None, None, 74.6, None, None, '+', 700, None, None, None, None, 32, None, None, None, None),
    (14, 50, 'CF', 'GOLET', 34.28135, -119.864375, 'waypoint', 'RZS', 184.8, 14.4, 184.8, 10.0, None, '+', 4000, None, None, 'R', None, 1, None, None, None, None),
    (14, 60, 'HM', 'GOLET', 34.28135, -119.864375, 'waypoint', None, None, None, 307.0, None, 1.0, '+', 4000, None, None, 'R', None, 16, None, None, None, None),
]


def build(path, procedures=PROCEDURES, transitions=TRANSITIONS, legs=LEGS):
    """Write the pack to *path* and return it."""
    con = sqlite3.connect(str(path))
    con.executescript(SCHEMA)
    con.executemany("INSERT INTO procedures VALUES (?, ?, ?, ?, ?, ?, ?, ?)", procedures)
    con.executemany("INSERT INTO transitions VALUES (?, ?, ?, ?)", transitions)
    con.executemany("INSERT INTO legs VALUES (%s)" % ", ".join("?" * 24), legs)
    con.commit()
    con.close()
    return path
