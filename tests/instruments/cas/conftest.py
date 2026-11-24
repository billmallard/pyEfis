#  SPDX-License-Identifier: GPL-2.0-or-later
"""The CAS keys, defined as fix-gateway's database/cas.yaml does."""

import pytest

from pyefis.instruments import cas
from pyefis.instruments.cas import model as cm

# key, dtype, min, max, tol (fix-gateway src/fixgw/config/database/cas.yaml)
CAS_KEYS = [("CASMSG{}".format(n), "str", None, None, 3000)
            for n in range(1, 13)] + [
    ("CASCNT", "int", 0, 1000, 3000),
    ("CASTOP", "int", 0, 3, 3000),
    ("CASSEQ", "int", 0, 2147483647, 3000),
    ("CASACK", "int", 0, 2147483647, 0),
]


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def cas_db(fix):
    """Every CAS key defined and fresh; returns ``publish(slots, seq=None)``,
    which writes a list the way the plugin does (slots, CASCNT, then CASSEQ
    last), with ``.fix`` and ``.flag(key, **flags)``."""
    for key, dtype, lo, hi, tol in CAS_KEYS:
        fix.db.define_item(key, key, dtype, lo, hi, "", tol, "")
        item = fix.db.get_item(key)
        item.value = "" if dtype == "str" else 0
        item.old = item.bad = item.fail = False
    state = {"seq": 0}

    def publish(slots, seq=None, count=None):
        slots = list(slots) + [""] * (cm.SLOTS - len(slots))
        for key, value in zip(cm.SLOT_KEYS, slots):
            fix.db.get_item(key).value = value
        fix.db.get_item("CASCNT").value = (
            count if count is not None else sum(1 for s in slots if s))
        state["seq"] = seq if seq is not None else state["seq"] + 1
        fix.db.get_item("CASSEQ").value = state["seq"]
        return state["seq"]

    def flag(key, **flags):
        for name, v in flags.items():
            setattr(fix.db.get_item(key), name, v)

    fix.db.clientthread.sendqueue.put.reset_mock()
    publish.fix = fix
    publish.flag = flag
    cas.reset_shared_model()
    yield publish
    cas.reset_shared_model()


def sent(fix, keys=("CASACK",)):
    """The (key, value) writes queued to fix-gateway, in order."""
    out = []
    for call in fix.db.clientthread.sendqueue.put.call_args_list:
        line = call.args[0].decode().strip()
        if line.startswith("@"):
            continue
        key, value, _flags = line.split(";")
        if key in keys:
            out.append((key, value))
    return out
