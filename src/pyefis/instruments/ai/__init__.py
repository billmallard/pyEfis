#  Copyright (c) 2013 Phil Birkelbach; 2018-2019 Garrett Herschleb
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

"""
The ``ai`` package holds the attitude/SVS widget (``ai_widget.py``, PyQt6)
alongside several pure-data sibling modules (``highway_db``, ``water_db``,
``airport_db``, ``obstacle_db``, ``svs`` geometry, ...) that headless data
tools import by dotted path (e.g. ``tools/build_highway_db.py``).

Importing any submodule of a package always executes the package's
``__init__.py`` first, so this file must stay free of PyQt6 (and any other
GUI-only) imports at module level -- AER-1090. ``AI``/``FDTarget`` are
re-exported lazily via ``__getattr__`` (PEP 562) so
``from pyefis.instruments.ai import AI`` keeps working without forcing Qt on
every ``pyefis.instruments.ai.<sibling>`` import.
"""

_WIDGET_EXPORTS = ("AI", "FDTarget")


def __getattr__(name):
    if name in _WIDGET_EXPORTS:
        from pyefis.instruments.ai.ai_widget import AI, FDTarget
        globals().update(AI=AI, FDTarget=FDTarget)
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(set(globals()) | set(_WIDGET_EXPORTS))
