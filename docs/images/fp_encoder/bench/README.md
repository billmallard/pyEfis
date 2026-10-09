# FP5c bench captures: knob path on the live Beelink panel (AER-810)

SIGUSR1 grabs (`/tmp/pyefis_screenshot.png`) of the running pyEfis on the
Beelink, 2026-10-09 16:35Z. The panel is the live PFD (`screens/managed.yaml`).
`flight_plan` sits in its **Flight Plan** `tab_section` tab, and the plan is
whatever the bench already held (`TEST`, one waypoint, KSBA).

**These are FIX-injected, not the physical knob.** The ENC3/BTN3 writes went
through fix-gateway with `fixgwc -x "write ENC3 1"` (and BTN3 True/False). The
Knobster plugin (fix-gateway #37) writes the same keys the same way, so this
exercises fixgw -> pyEfis -> tab page -> widget end to end. It does not exercise
the knob hardware. The real-knob 4-waypoint entry is Bill's step.

- `t1_highlight_*`: one detent (`ENC3 1`) with the Flight Plan tab shown. The
  screen highlight lands on `flight_plan`, drawn as an orange outline round the
  pane.
- `t2_focus_*`: push (BTN3 True, then False), then two detents. Focus moves from
  nothing, to the KSBA row, to the ADD WPT soft key.

`*_pane.png` is the right-hand pane cropped from `*_full.png` (x 1248-1920, 1:1).
The blank attitude area is expected: SVS is a `QOpenGLWidget`, and GL does not
render into the grab.

Bench state when captured: pyEfis `e53fb40` (#265's branch with `dev` merged,
so it carries #288 and #290), fix-gateway `0abda9d`. Live-config change for
this check: in `managed.yaml`, `HMI_ENCODER_BUTTONS` was added to `PFD.include`
and `encoder_order: 1` was set on the tab's `flight_plan`. The backup is
`managed.yaml.bak-aer810-20261009T163324Z`.
