#  Copyright (c) 2023 Eric Blevins, 2026 Bill Mallard
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.

"""The ``conditions`` grammar: a state dict built from FIX keys, and the
``when`` expressions evaluated against it.

Written for the Button (Eric Blevins) and moved here unchanged so the
``annunciator`` instrument reads the same grammar from the same code
(ANN1, ORG-018: one evaluator, never a copy).

The state dict holds, for every subscribed key ``K``::

    K              the value
    K.old          the quality flags
    K.bad
    K.fail
    K.annunciate
    K.aux.<name>   each auxiliary value (highAlarm, lowWarn, ...)

A ``when`` string is a pycond expression over those names, tokenized on
spaces with ``[]`` brackets, e.g. ``OILP lt 25 and not OILP.old`` or
``CLICKED eq true``. A bare name is true when its value is truthy.
Callers may add their own names (the Button adds ``SCREEN``, ``CLICKED``,
``DBKEY`` and ``PREVIOUS_CONDITION``).
"""

import pycond as pc

#: The signals a subscriber follows, by the name the state dict uses.
FLAGS = ("old", "bad", "fail", "annunciate")


def item_fields(item):
    """``{name: value}`` for every state-dict entry *item* contributes."""
    key = item.key
    out = {key: item.value}
    for flag in FLAGS:
        out[f"{key}.{flag}"] = getattr(item, flag)
    for aux in item.aux:
        out[f"{key}.aux.{aux}"] = item.aux[aux]
    return out


def refresh_field(data, item, signal):
    """Copy the part of *item* that *signal* (``value``, a flag, or ``aux``)
    names into *data*. An unknown signal changes nothing."""
    key = item.key
    if signal == "value":
        data[key] = item.value
    elif signal in FLAGS:
        data[f"{key}.{signal}"] = getattr(item, signal)
    elif signal == "aux":
        for aux in item.aux:
            data[f"{key}.aux.{aux}"] = item.aux[aux]


def connect_item(item, callback):
    """Call ``callback(key, signal)`` on every value, flag and aux change of
    *item*. The value is followed through each typed overload."""
    key = item.key
    for typ in (bool, int, str, float):
        item.valueChanged[typ].connect(
            lambda _v, key=key: callback(key, "value"))
    for flag in FLAGS:
        getattr(item, f"{flag}Changed").connect(
            lambda _v, key=key, flag=flag: callback(key, flag))
    item.auxChanged.connect(lambda _v, key=key: callback(key, "aux"))


def compile_when(when):
    """The callable ``fn(state=dict) -> bool`` for one ``when`` string.
    Raises on a malformed expression."""
    return pc.pycond(pc.to_struct(pc.tokenize(when, sep=" ", brkts="[]")))


def evaluate(when, state):
    """Is the ``when`` string *when* true for *state*?"""
    return compile_when(when)(state=state) == True  # noqa: E712 -- pycond's own truth
