#  SPDX-License-Identifier: GPL-2.0-or-later
"""Put the RS4 golden route on the LIVE fix-gateway bus (pyEfis #307, AER-3793).

Expands "KSBA GVO V27 AVOLS KSMX" from a real procedures pack, publishes it
through the real FixBridge to the gateway on localhost:3490, activates a leg
inside V27 and reads the segment table and FPLACTSEG back over an
independent raw netfix socket, so what is printed is the gateway's view, not
this process's. The plan that was on the bus is saved first; --restore puts
it back (its route, not its active-leg or direct-to state).

    <venv>/bin/python tools/bench_rs4_golden_route.py --procedures \\
        /data/makerplane-data/procedures/current/procedures.sqlite --save OLD.json [--act ID]
    <venv>/bin/python tools/bench_rs4_golden_route.py --restore OLD.json
"""
import argparse
import json
import socket
import sys
import time

sys.path.insert(0, "src")
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


def wait_for(pred, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.1)
    return False


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
    args = ap.parse_args(argv)

    fix.initialize({"main": {"FixServer": "localhost", "FixPort": "3490"}})
    fix.db.wait_for_initialization(10)
    bridge = fixbridge.FixBridge(fix)
    if not bridge.available:
        sys.exit("FixBridge unavailable: the gateway does not define the FP keys")

    if args.restore:
        with open(args.restore) as f:
            plan = fp_model.FlightPlan.from_json(json.load(f))
        bridge.publish(plan)
        time.sleep(1.0)
        print("restored", args.restore)
        dump()
        fix.stop()
        return

    if args.save:
        with open(args.save, "w") as f:
            json.dump(bridge.read_plan().to_json(), f)
        print("saved the plan on the bus to", args.save)

    graph = airways.AirwayGraph(args.procedures)
    if not graph.ready:
        sys.exit(f"procedures pack not readable: {args.procedures}")
    plan = fp_model.FlightPlan(waypoints=[KSBA, GVO, KSMX])
    plan.insert_airway(1, "V27", "AVOLS", graph)
    ids = [w.id for w in plan.waypoints]
    print("route:", " ".join(ids))
    seq0 = int(gw_read(["FPLSEQ"])["FPLSEQ"])
    bridge.publish(plan)
    if not wait_for(lambda: int(gw_read(["FPLSEQ"])["FPLSEQ"]) > seq0):
        sys.exit("FPLSEQ did not move on the gateway")
    time.sleep(0.5)
    if args.act:
        n = ids.index(args.act) + 1
        bridge.command("ACT", n)
        wait_for(lambda: int(gw_read(["FPLACTLEG"])["FPLACTLEG"]) == n)
    dump()
    fix.stop()


if __name__ == "__main__":
    main()
