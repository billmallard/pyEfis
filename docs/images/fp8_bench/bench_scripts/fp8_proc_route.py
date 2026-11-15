"""FP8 session 2 (AER-809): publish the profile's procedure route (KSMX RNAV
30 via GVO, missed approach with the WINCH HM hold) over netfix, exactly as
the SYN1 generator builds it (fixgw.sim.fplroute), so the live session and
the headless replay (tests/sim/test_fp8_headless.py) fly the same plan.

    python3 fp8_proc_route.py publish     -> route block + FPLSEQ commit, GPSSRC 0, NAVSRC 2
    python3 fp8_proc_route.py actslot     -> print the slot whose ID is the profile's start fix
"""
import sys
import time

from fixgw.sim import fplroute
from fixgw.sim.cifp import Cifp
from fixgw.sim.profile import load_profile
from nfx import NFX

FGW = "/home/pyefis/src/fix-gateway/src/fixgw/sim/profiles/fp8-ksmx-rnav30-missed.yaml"


def build():
    prof = load_profile(FGW)
    cifp = Cifp(prof.cifp_file)
    p = prof.procedure
    slots, segs = fplroute.procedure_slots(cifp, p["airport"], p["approach"], p["transition"], prof.magvar_deg)
    act = next(i for i, s in enumerate(slots, start=1) if s["ID"] == prof.start["fix"] and i > 1)
    name = f"{p['airport']} {p['approach']} {p['transition']}"[:32]
    return prof, cifp, slots, segs, act, name


def main(what):
    prof, cifp, slots, segs, act, name = build()
    if what == "actslot":
        print(act)
        return
    c = NFX()
    seq = int(float(c.read("FPLSEQ")[0] or 0)) + 1
    for k, v in fplroute.route_block_writes(slots, segs, name, "RNAV", cifp.cycle, seq):
        c.write(k, v)
    time.sleep(1.0)
    c.write("GPSSRC", 0)
    c.write("NAVSRC", 2)
    print("published", name, "cycle", cifp.cycle, "slots",
          " ".join("%d:%s/%s" % (i, s["ID"], s["PT"]) for i, s in enumerate(slots, 1)),
          "act", act, "FPLCOUNT", c.read("FPLCOUNT")[0], "FPLMSG", c.read("FPLMSG")[0])


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "publish")
