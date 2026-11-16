#  SPDX-License-Identifier: GPL-2.0-or-later
"""The AFC1 autopilot keys, defined as fix-gateway's autopilot.yaml does."""

import pytest

# key, dtype, min, max, tol (fix-gateway src/fixgw/config/database/autopilot.yaml)
AFC1_KEYS = [
    ("VSSEL", "int", -30000, 30000, 0),
    ("IASSEL", "float", 0.0, 999.9, 0),
    ("APCMD", "str", None, None, 0),
    ("APCMDSEQ", "int", 0, 2147483647, 0),
    ("APENG", "bool", None, None, 2000),
    ("FDENG", "bool", None, None, 2000),
    ("YDENG", "bool", None, None, 2000),
    ("APLAT", "str", None, None, 2000),
    ("APLATARM", "str", None, None, 2000),
    ("APVERT", "str", None, None, 2000),
    ("APVERTARM", "str", None, None, 2000),
    ("APALTCAP", "bool", None, None, 2000),
    ("APDISC", "bool", None, None, 2000),
]

INITIAL = {"int": 0, "float": 0.0, "str": "", "bool": False}


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def ap_db(fix):
    """Every AFC1 key, defined and fresh with its initial value; returns a
    ``set(key, value, old=False, bad=False, fail=False)`` helper."""
    for key, dtype, lo, hi, tol in AFC1_KEYS:
        fix.db.define_item(key, key, dtype, lo, hi, "", tol, "")
        item = fix.db.get_item(key)
        item.value = INITIAL[dtype]
        item.old = item.bad = item.fail = False

    def set_(key, value=None, old=False, bad=False, fail=False):
        item = fix.db.get_item(key)
        if value is not None:
            item.value = value
        item.old, item.bad, item.fail = old, bad, fail
        return item

    fix.db.clientthread.sendqueue.put.reset_mock()
    set_.fix = fix
    return set_


def sent(fix, keys=("APCMD", "APCMDSEQ")):
    """The (key, value) writes queued to fix-gateway, in order."""
    out = []
    for call in fix.db.clientthread.sendqueue.put.call_args_list:
        key, value, _flags = call.args[0].decode().strip().split(";")
        if key in keys:
            out.append((key, value))
    return out
