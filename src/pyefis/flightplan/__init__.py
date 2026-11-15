#  SPDX-License-Identifier: GPL-2.0-or-later
"""Qt-free flight-plan data layer (route model, waypoint lookup, catalog,
FIX bridge). See ``docs/flight_plan_widget.md`` and
``makerplane/briefs/flight_plan_plan.md`` section 3.4.

Nothing under this package may import PyQt6 — the instrument (FP5a) and the
map layer (FP6) wrap these plain-Python classes in Qt signals themselves.
"""
