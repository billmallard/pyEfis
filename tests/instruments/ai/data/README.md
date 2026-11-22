# Test data: flight director replay (AFC5, AER-6052)

`afc2_bf3a33402db4_fd_bus.csv.gz` is a slice of the fix-gateway bus log of
sim-bench session `bf3a33402db4`: X-Plane 12.4.3, Laminar C172 G1000 (GFC-700),
en route on V27 near KSBA, 2026-11-18 05:03-05:08Z, flown pilotless by the
xplane-bench driver while the AFC2 sequencer pressed HDG, VS (ALT armed, then
captured), IAS, NAV, LVL and AP disconnect (AER-5806). A private fix-gateway on
the Beelink ran the AFC2 X-Plane adapter and logged every published value.

Kept: every row for `PITCH`, `ROLL`, `FDENG`, `FDPITCH`, `FDROLL`, `APLAT`,
`APVERT`, `APLATARM`, `APVERTARM`. Columns: `t_s` (seconds after the first logged
row), `key`, `value` (angles rounded to 1e-4 deg), `flags` (netfix order:
annunciate, old, bad, fail, secondary fail). After the disconnect at about
176.5 s the driver paused the sim; `PITCH`/`ROLL` go old at 178.5 s and the FD
keys at 179.5 s.

The gateway mode timeline for the same flight is fix-gateway
`doc/evidence/aer-5806-xplane-autopilot/modes.md`; its raw dataref log is
fix-gateway `tests/plugins/xplane/data/afc2_c172_bf3a33402db4_raw.jsonl`.
