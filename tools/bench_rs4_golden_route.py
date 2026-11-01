#  SPDX-License-Identifier: GPL-2.0-or-later
"""Put the RS4 golden route on the LIVE fix-gateway bus (pyEfis #307, AER-3793).

Expands "KSBA GVO V27 AVOLS KSMX" from a real procedures pack, publishes it
through the real FixBridge to the gateway on localhost:3490, activates a leg
inside V27 and reads the segment table and FPLACTSEG back over an
independent raw netfix socket, so what is printed is the gateway's view, not
this process's. The plan that was on the bus is saved first; --restore puts
it back (its route, not its active-leg or direct-to state); --restore-state
republishes the route from a fix-gateway flightplan_state.json instead.

The local FIX db only fills with the gateway's values while a Qt event loop
runs, so every read and write here pumps one first. Without it the bridge
reads blank keys and publishes them flagged bad/fail, with FPLSEQ 1.

    <venv>/bin/python tools/bench_rs4_golden_route.py --procedures \\
        /data/makerplane-data/procedures/current/procedures.sqlite --save OLD.json [--act ID]
    <venv>/bin/python tools/bench_rs4_golden_route.py --restore OLD.json
    <venv>/bin/python tools/bench_rs4_golden_route.py --restore-state flightplan_state.json
"""
import argparse
import json
import os
import socket
import sys
import time

sys.path.insert(0, "src")
from PyQt6.QtWidgets import QApplication  # noqa: E402

import pyavtools.fix as fix  # noqa: E402

from pyefis.flightplan import airways, fixbridge  # noqa: E402
from pyefis.flightplan import model as fp_model  # noqa: E402

KSBA = fp_model.Waypoint(id="KSBA", type="airport", lat=34.4262, lon=-119.8404)
GVO = fp_model.Waypoint(id="GVO", type="vor", lat=34.5313, lon=-120.0910)
KSMX = fp_model.Waypoint(id="KSMX", type="airport", lat=34.8989, lon=-120.4575)


def gw_read(keys):
    s = socket.create_connection(("localhost", 3490), timeout=3)
    out = {}
    for k in keys:
        s.sendall(f"@r{k}\n".encode())
        buf = b""
        while b"\n" not in buf:
            buf += s.recv(512)
        parts = buf.decode().strip().split(";")
        out[k] = parts[1] if len(parts) > 1 else parts[0]
    s.close()
    return out


def pump(app, t=0.5):
    end = time.time() + t
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


def wait_for(app, pred, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        pump(app, 0.1)
    return False


def plan_from_state(path):
    """The route in a fix-gateway flightplan_state.json as a FlightPlan."""
    with open(path) as f:
        d = json.load(f)
    slots = [fixbridge.RouteSlot(
        id=w["id"], lat=w["lat"], lon=w["lon"],
        type=fixbridge.FPLTYPE_TO_TYPE.get(int(w.get("type", 0)), "unknown"), role="none",
        pt=w.get("pt") or "TF", crs=float(w.get("crs", 0.0)), dst=float(w.get("dst", 0.0)),
        alt=w.get("alt") or "", spd=int(w.get("spd", 0)), sgi=int(w.get("sgi", 0)))
        for w in d["route"]]
    segs = [fixbridge.RouteSegment(
        kind=fp_model.SEGMENT_KINDS[int(s.get("kind", 0))], ident=s.get("id") or "",
        entry=s.get("ent") or "", exit=s.get("ext") or "",
        first=int(s.get("first", 0)), last=int(s.get("last", 0)))
        for s in d.get("segments", [])]
    return fixbridge.route_to_plan(fixbridge.RouteBlock(
        name=d.get("name") or "", seq=0, waypoints=slots, segments=segs,
        cycle=d.get("dbcyc") or ""))


def finish(code=0):
    fix.stop()
    os._exit(code)


def dump():
    cnt = int(gw_read(["FPLSEGCNT"])["FPLSEGCNT"])
    for k in range(1, cnt + 1):
        v = gw_read([f"FPLS{k}{f}" for f in ("KIND", "ID", "ENT", "EXT", "FIRST", "LAST")])
        print(f"  FPLS{k}: " + " ".join(f"{n[len(f'FPLS{k}'):]}={x}" for n, x in v.items()))
    print("  " + " ".join(f"{k}={v}" for k, v in gw_read(
        ["FPLCOUNT", "FPLSEGCNT", "FPLSTATE", "FPLACTLEG", "FPLACTSEG", "FPLMSG"]).items()))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--procedures", help="procedures.sqlite (airways)")
    ap.add_argument("--save", help="write the plan currently on the bus here first")
    ap.add_argument("--restore", help="republish a plan saved with --save, and stop")
    ap.add_argument("--act", default="", help="activate the leg TO this fix")
    ap.add_argument("--restore-state", help="republish the route in a fixgw state file")
    args = ap.parse_args(argv)

    app = QApplication(sys.argv[:1])
    fix.initialize({"main": {"FixServer": "localhost", "FixPort": "3490"}})
    fix.db.wait_for_initialization(10)
    pump(app, 2.0)
    bridge = fixbridge.FixBridge(fix)
    if not bridge.available:
        print("FixBridge unavailable: the gateway does not define the FP keys")
        finish(1)
    # The local copy must match the gateway before anything is read or
    # written (see the module docstring).
    if not wait_for(app, lambda: int(bridge._get("FPLSEQ").value)
                    == int(gw_read(["FPLSEQ"])["FPLSEQ"]) and not bridge._get("FPLSEQ").fail):
        print("the local FIX db never matched the gateway's FPLSEQ; nothing written")
        finish(1)

    def publish(plan):
        seq0 = int(gw_read(["FPLSEQ"])["FPLSEQ"])
        bridge.publish(plan)
        if not wait_for(app, lambda: int(gw_read(["FPLSEQ"])["FPLSEQ"]) > seq0):
            print("FPLSEQ did not move on the gateway")
            finish(1)
        pump(app, 0.5)

    if args.restore or args.restore_state:
        if args.restore:
            with open(args.restore) as f:
                plan = fp_model.FlightPlan.from_json(json.load(f))
        else:
            plan = plan_from_state(args.restore_state)
        publish(plan)
        print("restored", args.restore or args.restore_state)
        dump()
        finish()

    if args.save:
        with open(args.save, "w") as f:
            json.dump(bridge.read_plan().to_json(), f)
        print("saved the plan on the bus to", args.save)

    graph = airways.AirwayGraph(args.procedures)
    if not graph.ready:
        print(f"procedures pack not readable: {args.procedures}")
        finish(1)
    plan = fp_model.FlightPlan(waypoints=[KSBA, GVO, KSMX])
    plan.insert_airway(1, "V27", "AVOLS", graph)
    ids = [w.id for w in plan.waypoints]
    print("route:", " ".join(ids))
    publish(plan)
    if args.act:
        n = ids.index(args.act) + 1
        bridge.command("ACT", n)
        wait_for(app, lambda: int(gw_read(["FPLACTLEG"])["FPLACTLEG"]) == n)
    dump()
    finish()


if __name__ == "__main__":
    main()
