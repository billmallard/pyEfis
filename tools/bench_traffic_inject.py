#!/usr/bin/env python3
#  SPDX-License-Identifier: GPL-2.0-or-later
"""Synthetic ADS-B traffic for the bench (P3b, AER-5266).

Sends GDL90 Heartbeats and Traffic Reports over UDP to fix-gateway's stratux
plugin (port 4000), so its traffic writer fills the FIX ``TFC`` block and
pyEfis draws it -- the real path end to end, with no receiver. Frames are
built from the GDL90 ICD itself (560-1058-00 Rev A: G§2.2 framing and FCS,
G§3.5.1 Traffic Report layout); ``--selftest`` checks the encoder against
the document's own vectors.

The scenario places six targets around ownship, one per display state the
P3b definition of done names (plus the non-directional symbol):

  normal      2.5 NM, 330 deg relative, +500 ft, level
  alert       2.0 NM, 030 deg relative, -300 ft, climbing 1000 fpm, alert bit
  degraded    3.2 NM, 290 deg relative, +1500 ft, NIC 3 / NACp 3
  stale       3.0 NM, 070 deg relative, +800 ft, descending; reports stop
              after --warmup
  alt-invalid 2.5 NM, 230 deg relative, altitude 0xFFF
  no-track    3.5 NM, 130 deg relative, -1200 ft, track not valid (m = 00)

With ``--ownship`` it also writes ownship LAT/LONG/ALT/BARO/TRACK/TRACKM
over netfix once a second (fix-gateway's own ``fixgw.netfix`` client), for a
bench with no simulator running. Run it with the bench venv's python:

  ~/pyefis-venv/bin/python tools/bench_traffic_inject.py --ownship \\
      --lat 34.4258 --lon -119.8415 --alt 4500 --track 34 --seconds 40

The stale target goes ``old`` 3 s after --warmup and is evicted at the
writer's evict_s (10 s): capture inside that window.
"""

import argparse
import math
import socket
import struct
import sys
import time

FLAG, ESC = 0x7E, 0x7D
HEARTBEAT, TRAFFIC = 0x00, 0x14


def _crc_table():
    table = []
    for i in range(256):
        crc = (i << 8) & 0xFFFF
        for _ in range(8):
            crc = ((crc << 1) ^ (0x1021 if crc & 0x8000 else 0)) & 0xFFFF
        table.append(crc)
    return table


_CRC = _crc_table()


def fcs(data):
    """G§2.2.3: CRC-CCITT, initial 0, table-driven."""
    crc = 0
    for b in data:
        crc = (_CRC[crc >> 8] ^ ((crc << 8) & 0xFFFF) ^ b) & 0xFFFF
    return crc


def frame(msg):
    """G§2.2.1: FCS appended LSB first, then 0x7D/0x7E stuffed, flagged."""
    c = fcs(msg)
    raw = bytes(msg) + bytes((c & 0xFF, c >> 8))
    out = bytearray([FLAG])
    for b in raw:
        if b in (FLAG, ESC):
            out += bytes((ESC, b ^ 0x20))
        else:
            out.append(b)
    out.append(FLAG)
    return bytes(out)


def heartbeat(now=None):
    """G§3.1: status 1 = GPS position valid + UAT initialised."""
    t = int(now if now is not None else time.time()) % 86400
    st1 = 0x81
    st2 = (0x80 if t & 0x10000 else 0) | 0x01   # timestamp bit 16, UTC OK
    return bytes((HEARTBEAT, st1, st2, t & 0xFF, (t >> 8) & 0xFF, 0, 0))


def _s24(deg):
    v = int(round(deg * (1 << 23) / 180.0))
    return v & 0xFFFFFF


def traffic(addr, lat, lon, alt_ft=None, airborne=True, extrapolated=False,
            ttyp=1, nic=10, nacp=9, gs_kt=120, vs_fpm=0, trk_deg=0.0,
            emitter=1, callsign="", alert=0, atype=0, emergency=0):
    """G§3.5.1 Traffic Report. ``alt_ft=None`` sends 0xFFF (invalid)."""
    ddd = 0xFFF if alt_ft is None else max(0, min(0xFFE, int(round((alt_ft + 1000) / 25.0))))
    m = (ttyp & 3) | (4 if extrapolated else 0) | (8 if airborne else 0)
    hhh = max(0, min(0xFFE, int(round(gs_kt))))
    vvv = int(round(vs_fpm / 64.0)) & 0xFFF
    tt = int(round(trk_deg * 256.0 / 360.0)) & 0xFF if ttyp else 0
    cs = (callsign.upper() + " " * 8)[:8].encode("ascii")
    la, lo = _s24(lat), _s24(lon)
    b = bytearray([TRAFFIC, (alert & 0xF) << 4 | (atype & 0xF)])
    b += addr.to_bytes(3, "big")
    b += la.to_bytes(3, "big") + lo.to_bytes(3, "big")
    b += bytes((ddd >> 4, (ddd & 0xF) << 4 | m, (nic & 0xF) << 4 | (nacp & 0xF)))
    b += bytes((hhh >> 4, (hhh & 0xF) << 4 | (vvv >> 8), vvv & 0xFF))
    b += bytes((tt, emitter & 0xFF)) + cs + bytes(((emergency & 0xF) << 4,))
    return bytes(b)


def offset(lat, lon, brg_deg, nm):
    """Point *nm* from (lat, lon) on true bearing *brg_deg* (flat earth,
    fine at a few NM)."""
    d = nm / 60.0
    b = math.radians(brg_deg)
    return (lat + d * math.cos(b),
            lon + d * math.sin(b) / math.cos(math.radians(lat)))


#: name, relative bearing, NM, relative alt (None = invalid), report kwargs
SCENARIO = (
    ("normal", 330, 2.5, 500, dict(vs_fpm=0, trk_rel=150, callsign="N111NM")),
    ("alert", 30, 2.0, -300, dict(vs_fpm=1000, trk_rel=200, alert=1, callsign="N222AL")),
    ("degraded", 290, 3.2, 1500, dict(vs_fpm=0, trk_rel=90, nic=3, nacp=3, callsign="N333DG")),
    ("stale", 70, 3.0, 800, dict(vs_fpm=-600, trk_rel=250, callsign="N444ST")),
    ("alt-invalid", 230, 2.5, None, dict(vs_fpm=0, trk_rel=40, callsign="N555AI")),
    ("no-track", 130, 3.5, -1200, dict(vs_fpm=0, trk_rel=0, ttyp=0, callsign="N666NT")),
)


def reports(lat, lon, palt_ft, track, skip=()):
    out = []
    for i, (name, rel, nm, dalt, kw) in enumerate(SCENARIO):
        if name in skip:
            continue
        kw = dict(kw)
        tlat, tlon = offset(lat, lon, track + rel, nm)
        trk = (track + kw.pop("trk_rel")) % 360.0
        alt = None if dalt is None else palt_ft + dalt
        out.append(traffic(0xA10000 + i, tlat, tlon, alt, trk_deg=trk, **kw))
    return out


def selftest():
    hb = bytes.fromhex("7E 00 81 41 DB D0 08 02 B3 8B 7E".replace(" ", ""))
    assert frame(bytes.fromhex("0081 41DB D008 02".replace(" ", ""))) == hb, "G§2.2.4"
    # the encoded position, decoded (the document's printed 44.90708 /
    # -122.99488 are one LSB off, spec section 7 T1)
    lat = 0x1FEF15 * 180.0 / (1 << 23)
    lon = (0xA88978 - (1 << 24)) * 180.0 / (1 << 23)
    ex = traffic(0xAB4549, lat, lon, 5000, ttyp=1, nic=10,
                 nacp=9, gs_kt=123, vs_fpm=64, trk_deg=45.0, emitter=1,
                 callsign="N825V")
    want = bytes.fromhex(
        "7E 14 00 AB 45 49 1F EF 15 A8 89 78 0F 09 A9 07 B0 01 20 01 4E 38 32"
        " 35 56 20 20 20 00 57 D6 7E".replace(" ", ""))
    assert frame(ex) == want, "G§3.5.2: %s" % frame(ex).hex(" ")
    print("selftest ok: G§2.2.4 heartbeat and G§3.5.2 traffic vectors match")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=4000)
    ap.add_argument("--lat", type=float, default=34.4258)
    ap.add_argument("--lon", type=float, default=-119.8415)
    ap.add_argument("--alt", type=float, default=4500.0,
                    help="ownship pressure altitude, ft (targets are placed relative to it)")
    ap.add_argument("--track", type=float, default=34.0, help="ownship true track")
    ap.add_argument("--magvar", type=float, default=-12.0,
                    help="written as MAGVAR with --ownship (positive west)")
    ap.add_argument("--seconds", type=float, default=40.0)
    ap.add_argument("--warmup", type=float, default=20.0,
                    help="seconds before the stale target's reports stop")
    ap.add_argument("--ownship", action="store_true",
                    help="also write ownship keys over netfix (no simulator)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    selftest()
    if a.selftest:
        return 0
    client = None
    if a.ownship:
        import fixgw.netfix as netfix
        client = netfix.Client("127.0.0.1", 3490)
        client.connect()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    t0 = time.monotonic()
    n = 0
    try:
        while time.monotonic() - t0 < a.seconds:
            el = time.monotonic() - t0
            if client is not None:
                for k, v in (("LAT", a.lat), ("LONG", a.lon), ("BARO", 29.92),
                             ("ALT", a.alt), ("TRACK", a.track),
                             ("TRACKM", (a.track + a.magvar) % 360.0),
                             ("MAGVAR", a.magvar)):
                    client.writeValue(k, v)
            skip = ("stale",) if el >= a.warmup else ()
            msgs = [heartbeat()] + reports(a.lat, a.lon, a.alt, a.track, skip)
            sock.sendto(b"".join(frame(m) for m in msgs), (a.host, a.port))
            if n % 5 == 0:
                print("t=%5.1fs sent %d reports%s" % (
                    el, len(msgs) - 1, " (stale stopped)" if skip else ""),
                    flush=True)
            n += 1
            time.sleep(1.0)
    finally:
        if client is not None:
            client.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
