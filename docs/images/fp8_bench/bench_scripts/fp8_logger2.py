"""FP8 session 2 logger (AER-809). Same 1 Hz CSV as fp8_logger.py plus the
integrity/command keys, over a reconnecting socket so a fixgw restart leaves
a gap of ERR rows rather than ending the log.

    python3 fp8_logger2.py out.csv
"""
import csv
import sys
import time

from nfx import NFX

KEYS = [
    "LAT", "LONG", "ALT", "GS", "TRACK", "MAGVAR", "HEAD",
    "GPSSRC", "NAVSRC",
    "FPLSTATE", "FPLACTLEG", "FPLPHASE", "FPLAPR", "FPLINTEG", "CDISCALE",
    "FPLCRS", "FPLXTK", "FPLCDI", "FPLTF",
    "EXTCRS", "EXTCDI", "EXTTF",
    "GPSCRS", "GPSCDI", "GPSTF", "COURSE", "CDI", "TOFROM",
    "WPFROM", "WPNAME", "WPNEXT", "WPDIS", "FPLMSG",
    "GPS_ACCURACY_HORIZ", "FPLCMDACK", "FPLCOUNT",
]


def main(path):
    c = NFX()
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if f.tell() == 0:
            w.writerow(["t"] + KEYS + ["flags_LAT", "flags_EXTCRS", "flags_GPS_ACCURACY_HORIZ"])
        nxt = time.time()
        while True:
            row, flags = [round(time.time(), 1)], {}
            for k in KEYS:
                v, fl = c.read(k)
                row.append(v)
                flags[k] = fl
            row += [flags["LAT"], flags["EXTCRS"], flags["GPS_ACCURACY_HORIZ"]]
            w.writerow(row)
            f.flush()
            nxt += 1.0
            d = nxt - time.time()
            if d < -5:  # fell behind (restart gap): resync instead of bursting
                nxt = time.time()
            time.sleep(max(0.0, d))


if __name__ == "__main__":
    main(sys.argv[1])
