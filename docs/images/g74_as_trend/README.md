# G74 / pyEfis #403: airspeed_trend_tape reads IAS

`states.png`: `AS_Trend_Tape` at 80x400, driven only through the `IAS` FIX
item (the widget is never called directly) with a hand-stepped clock. Panels
left to right:

1. IAS rising 2.5 kt/s: bar half-way to the top edge (full scale is 5 kt/s)
2. IAS steady for 4 s: no bar
3. IAS falling 2.5 kt/s: bar half-way to the bottom edge
4. The same deceleration with `IAS` flagged failed: no bar

Before the fix, all four panels looked like panel 2: the widget subscribed to
nothing.

Regenerate (from the repo root):

```bash
QT_QPA_PLATFORM=offscreen python3 docs/images/g74_as_trend/render_states.py
```

The widget draws no text, so the sandbox's missing fonts do not affect it.
