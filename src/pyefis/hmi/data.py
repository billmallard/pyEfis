#  Copyright (c) 2018 Phil Birkelbach
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


import operator
import logging
log = logging.getLogger(__name__)

from PyQt6.QtCore import QTimer

import pyavtools.fix as fix
from pyefis import hmi

__bindings = []
# Keys a binding acts on.  A button on one of these keys leaves the key to the
# binding, so a press acts once whether or not the button is on screen (DSP2).
_bound_keys = set()


def binds(key):
    return key in _bound_keys


def release(key, why):
    """Stand down every binding on key.  A toggle button holds its key true,
    which a binding would read as a press held forever."""
    for b in __bindings:
        if getattr(b, 'key', None) == key:
            b.released = True
            if b.timer is not None:
                b.timer.stop()
    if key in _bound_keys:
        log.error("Data binding on {} switched off: {}".format(key, why))
    _bound_keys.discard(key)


class DataBinding(object):
    __COMPARE_FUNCTIONS = {"=": operator.eq,
                           "<": operator.lt,
                           "<=": operator.le,
                           ">": operator.gt,
                           ">=": operator.ge}

    def __init__(self, config, node_id=1):
        # {id} is the display's nodeID, as in a button's dbkey, so one
        # bindings file serves several displays (TSBTN{id}12 -> TSBTN112).
        self.key = str(config['key']).replace('{id}', str(node_id))
        self.compare = None
        self.args = ""
        self.value = None
        self.item = fix.db.get_item(self.key)
        self.lastResult = False
        # Hold-to-repeat, as a repeat button: while the condition stays true
        # the action fires again after repeat_delay ms, then every
        # repeat_interval ms.  Without repeat_interval a binding fires once.
        self.repeat_interval = config.get('repeat_interval')
        self.repeat_delay = config.get('repeat_delay', self.repeat_interval)
        self.timer = None
        self.released = False

        a = config['action']
        if hmi.actions.findAction(a):
            self.action = a
        else:
            log.error("Action Not Found - {}".format(a))
            return None

        if 'args' in config:
            self.args = config['args']
        if self.args is None: self.args = ""
        else: self.args = str(self.args)
        if self.args.lower() == "<value>":
            self.args = None

        if "condition" in config:
            self.parseCondition(config["condition"])

        # If we are unconditionally sending the value then we need to send
        # an initial one here in case the receiver needs it.
        if self.args is None and self.compare is None:
            hmi.actions.trigger(self.action, str(self.item.value))

        self.item.valueChanged[self.item.dtype].connect(self.changeFunctionFactory())


    def changeFunctionFactory(self):
        if self.compare:
            cfunc = self.__COMPARE_FUNCTIONS[self.compare]

        def actionTrigger(value):
            if self.released: return
            if self.args is None:
                hmi.actions.trigger(self.action, str(value))
            else:
                hmi.actions.trigger(self.action, self.args)

        def repeat():
            actionTrigger(self.item.value)
            self.timer.start(int(self.repeat_interval))

        def compareFunction(value):
            if cfunc(value, self.value):
                if self.lastResult: return
                actionTrigger(value)
                self.lastResult = True
                if self.repeat_interval:
                    if self.timer is None:
                        self.timer = QTimer()
                        self.timer.setSingleShot(True)
                        self.timer.timeout.connect(repeat)
                    self.timer.start(int(self.repeat_delay))
            else:
                self.lastResult = False
                if self.timer is not None:
                    self.timer.stop()

        if self.compare is None:
            return actionTrigger
        else:
            return compareFunction


    def parseCondition(self, condition):
        if type(condition) in [bool, int, float]:
            self.value = condition
            self.compare = "="
        else:
            s = condition.replace(" ", "")
            op = ""
            val = ""
            for possible_op in ["<=", ">=", "<", ">", "="]:
                if s.startswith(possible_op):
                    op = possible_op
                    val = s[len(possible_op):]
                    break
            if op not in ["<", ">", "<=", ">=", "="]:
                log.error("Unknown Condition Operator {}".format(op))
                return None
            self.value = self.item.dtype(val)
            self.compare = op


    def __str__(self):
        if self.compare:
            s = "Data Binding: {}{}{} - {}({})".format(self.key, self.compare, self.value, self.action, self.args)
        else:
            s = "Data Binding: {} - {}({})".format(self.key, self.action, self.args)
        return(s)


def initialize(config, node_id=1):
    del __bindings[:]
    _bound_keys.clear()
    if config is None: return
    for x in config:
        try:
            d = DataBinding(x, node_id)
        except:
            log.error("Unable to load Data Binding {}".format(x))
            raise
        # Kept so a repeat timer lives as long as the app does
        __bindings.append(d)
        if hasattr(d, 'action'):
            _bound_keys.add(d.key)
