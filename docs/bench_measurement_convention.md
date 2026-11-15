# Bench measurement convention: record the box's load state

**A bench timing without the box's load state recorded beside it is not a
result.** (AER-694, from the AER-690 sweep)

Every timing taken on the Beelink between 2026-08-30 and 2026-09-06 was taken
on a box where the live `pyefis` service held 78-80% of one core because
`fixgw.plugins.demo` (`DEMO: true`) was on. The data path was clean -- no
fix-gateway TCP path into these offscreen harnesses, poses on the command
line -- but the *load* path was not, and nothing recorded whether the display
was even up. AER-689 stops `bench-deploy.sh --check` from leaving `DEMO` on;
this convention closes the general case, because the next thing that loads
the box will not be `DEMO`.

Ratios and A/Bs (qt vs numpy, before vs after a code change measured in the
same run) survive a shared load -- both legs pay the same tax. Reporting an
**absolute number against an absolute budget** is what a co-resident load can
move in either direction, so that is what needs the load recorded next to it.

Beside every absolute bench number, capture:

```bash
systemctl --user is-active pyefis
pidstat -p $(pgrep -f "pyefis-venv/bin/pyefis$") 1 3   # or: ps -p <pid> -o pcpu
cat /proc/loadavg
```

If the live display needs to be up for the measurement to be representative
(e.g. a DoD that says "niced, with the live display up"), say so and leave it
running rather than deciding silently to stop it for a cleaner-looking number.
If it doesn't, prefer an isolated clone (`git clone` to `/tmp` on the bench
host, checked out to the exact commit/branch under test) over the shared
`~/src/pyEfis` checkout, particularly when other work is in flight there.
