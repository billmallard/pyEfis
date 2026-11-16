#  SPDX-License-Identifier: GPL-2.0-or-later
"""Autopilot displays (AFC, makerplane brief ``autopilot_control_head_plan.md``).

- :mod:`.state` -- :class:`~.state.APState`, the guarded reader of the AFC1
  state keys (fix-gateway ``database/autopilot.yaml``) every autopilot display
  shares.
- :mod:`.fma` -- the mode annunciation strip (AFC4).

The rule that governs every module here (brief section 3): the head asks, the
autopilot decides. A display shows the state the autopilot source reports,
never a press, and removes it when the source goes quiet.
"""
