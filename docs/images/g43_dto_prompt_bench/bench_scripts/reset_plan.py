"""Republish the bench's current (empty) plan block with FPLSEQ+1, which the
flightplan engine treats as a new plan and drops any activation (mode NONE)."""
import time
from nfx import NFX
c = NFX()
before = {k: c.read(k)[0] for k in ("FPLCOUNT", "FPLSEGCNT", "FPLNAME", "FPLAPRTYPE",
                                    "FPLDBCYC", "FPLSEQ", "FPLSTATE")}
print("before", before)
assert int(float(before["FPLCOUNT"] or 0)) == 0, "plan not empty -- refusing"
seq = int(float(before["FPLSEQ"] or 0)) + 1
c.write("FPLSEQ", seq)
time.sleep(2)
print("after", {k: c.read(k)[0] for k in ("FPLSEQ", "FPLSTATE", "FPLMSG")})
