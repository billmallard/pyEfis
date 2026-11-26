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

import pyavtools.fix as fix


# Set a value in the FIX database.  arg should be "key,value"
def setValue(arg):
    args = arg.split(",")
    i = fix.db.get_item(args[0].strip())
    i.value = args[1].strip()
    # Always output values we set
    # In most cases we are setting a value to trigger some
    # action and most actions take place outside of pyEFIS
    i.output_value()


# Change a value in the FIX database by a certain value.  arg should be "key,value"
def changeValue(arg):
    args = arg.split(",")
    i = fix.db.get_item(args[0])
    i.value += i.dtype(args[1])
    i.output_value()


# Change a value but wrap within the key's [min, max] range instead of clamping.
# arg should be "key,delta" or "key,delta,period".  Without a period the span is
# max - min, which suits an index key (NAVSRC 0..3 cycles 0, 1, 2).  A circular
# key declares its circle as the period: HEADBUG is 0.0..359.9 on the bus, so
# "HEADBUG, -1" alone would land 0 on 358.9; "HEADBUG, -1, 360" lands it on 359.
def changeValueWrap(arg):
    args = arg.split(",")
    i = fix.db.get_item(args[0].strip())
    if len(args) > 2:
        span = float(args[2])
    else:
        span = i.max - i.min
    if span <= 0:
        i.value += i.dtype(args[1])
    else:
        v = (float(i.value) + float(args[1]) - i.min) % span
        i.value = i.dtype(i.min + v)
    i.output_value()


# Copy one key's value into another.  arg should be "dest,source"; used for a
# "sync" control (e.g. set the heading bug to the current heading).
def syncValue(arg):
    args = arg.split(",")
    dest = fix.db.get_item(args[0].strip())
    src = fix.db.get_item(args[1].strip())
    dest.value = dest.dtype(src.value)
    dest.output_value()


def toggleBool(arg):
    bit = fix.db.get_item(arg)
    bit.value = not bit.value
    bit.output_value()
