# Pilot's Guide

Operating the panel now has its own pages:

- [The Panel at a Glance](The-Panel-at-a-Glance): what is where, the tab
  column, moving between screens, touch and the knob, flagged data.
- [Attitude and Synthetic Vision](Attitude-and-Synthetic-Vision)
- [Airspeed, Altitude and Vertical Speed](Airspeed-Altitude-and-Vertical-Speed):
  including the selected altitude and the altimeter setting.
- [The HSI](The-HSI)

This page keeps the stock screens' engine, trim and data-currency controls
until their own pages land.

---

## Engine monitoring & leaning

The **EMS** (and **EMS2**) screens show the full engine picture: RPM, manifold
pressure, oil temperature/pressure, fuel, electrical, and the per-cylinder
**EGT** and **CHT** strips (vertical bars). The hottest cylinder is highlighted.

For fuel-injected/leaning work, the EGT strip has **mode buttons**:

| Button | What it does |
|--------|--------------|
| **Normal** | Absolute EGT against the gauge range (default) |
| **Peak** | Tracks each cylinder's peak; once a cylinder falls past peak it shows **how far below peak** it is — find peak and set rich/lean of it |
| **Normalize** | Re-centers all cylinders to a common reference so you can compare them directly |
| **Lean** | Shortcut: reset peak + normalize + peak together, the usual leaning view |
| **Reset Peak** | Clears the stored peaks to start a new lean |

These are mutually-managed — selecting one clears the others — and the active
button highlights green. (Engineering detail:
[Engine & Data Gauges → EGT modes](Widgets-Engine-Gauges#egt-modes-engine-leaning).)

---

## Trim (if equipped)

If your installer enabled trim controls, the PFD shows **trim position** (pitch,
and optionally roll/yaw) with **+/−** buttons to drive it. These are off by
default and only appear when configured for your aircraft's trim axes.

---

## Data currency & updates

The **Data Status** screen lists your installed navigation-data
packs — terrain, airports, obstacles, water — and their currency, color-coded.
From here:

- **Continue** proceeds to the flight display.
- **Update** runs the data updater (downloads/installs newer packs, with a
  progress bar) — typically done on the ground with connectivity.

On screens that carry it, a small **DATA** flag is your reminder: amber when a
pack has expired, white when one is expiring soon or missing, and hidden when
everything is current. Touch it to open the Data Status screen.
