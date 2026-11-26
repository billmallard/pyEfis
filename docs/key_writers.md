# The FIX keys pyEfis writes (ARCHG2)

pyEfis mostly reads the FIX database, but a few instruments write to it: the
altimeter knob writes `BARO`, the HSI writes `NAVSRC`, the autopilot panel writes
`APCMD`. A key is a contract between boxes, with one meaning, one unit and one
writer at a time. fix-gateway keeps the record of who writes each key, in
`src/fixgw/database/writers.yaml` (ARCHG1, fix-gateway `doc/key_writers.md`).
That register has a `pyefis` field for the pyEfis writers, but fix-gateway's CI
cannot see pyEfis code. This check covers that from the pyEfis side.

Backlog item ARCHG2 (AER-6403). Policy: ORG-018 (maos-workspace).

## What it checks

`tools/check_fix_writers.py` fails when:

- **a pyEfis module writes a FIX key, and the register does not list that module
  under the key's `pyefis` field.** The message ends "declare it in fix-gateway
  writers.yaml first";
- **a class named for a route concept** (`Waypoint`, `Segment`, `RouteSlot`, ...)
  is defined in a file `tests/arch/concept_names.yaml` does not list for it, or
  a listed file no longer defines it.

When a module the register lists has stopped writing its key, the check prints
a notice and does not fail. The fix belongs in fix-gateway, and failing here
would force both repos to change in the same step.

CI runs it as its own step, before pytest, and copies the report into the job
summary. `tests/tools/test_check_fix_writers.py` runs the failure cases. To run
it locally (it needs git, plus network the first time):

```sh
python tools/check_fix_writers.py      # prints each failure; exit 1 if any
```

## Nothing from fix-gateway is copied

pyEfis keeps no copy of the register and no copy of the scanner. The check
fetches both from fix-gateway at one commit, the **pin**, as a sparse, shallow
checkout of a few files. It then runs fix-gateway's own
`tools/check_key_writers.py` over the pyEfis tree, using the same scan that fills
the register's `pyefis` field. The fetched files are cached under
`~/.cache/pyefis/fix-gateway-<sha>`. Pass `--fixgw DIR` to use a checkout you
already have; it must be at the pin. A write counts when it is one ARCHG1's
scan can see: a literal key or a module constant passed to `set_value`/`write`,
`.value =` or `output_value()` on an item fetched with `get_item("KEY")` or from
a method that returns one (`self._get(key)`), a wrapper function that passes its
key on, a key built by a name function (`_slot_key(i, name)`), or the `.item` of
a `bugs.BugBinding("KEY", self)` the module makes. A key held in a variable
(`fix.db.set_value(self.key, v)`) is not seen, as in fix-gateway.

When an item comes from elsewhere (an editor handed a binding whose key is the
panel's `alt_bug_dbkey`), say which keys the write reaches, on its line:

```python
item.output_value()  # writes: ALTSEL
```

The scan stops with the file and line if the comment is on no write, on a write
it can already name, or names a key the database does not have (ARCHG2b).

## When the check fails on your write

1. Decide whether the instrument should write the key at all. Most pyEfis
   state belongs on the bus from an engine, not from the display (roadmap
   section 9, "Governing rule").
2. In fix-gateway, add the module (the name the failure prints, such as
   `pyefis/instruments/baro_box`) to the key's `pyefis` list in
   `src/fixgw/database/writers.yaml`. A key nobody writes yet also needs its
   roadmap 9.1 block. fix-gateway's CI then decides whether that makes the key
   multi-writer. A key with a fix-gateway writer already (`BARO` has `canfix`
   and `grand_rapids_eis`) fails its baseline, and that ruling is the point of
   declaring the write there first.
3. When that fix-gateway PR merges to `dev`, bump the pin here (next section),
   in the PR that adds the write, or in a one-line PR before it.

## The pin, and how to bump it

`tests/arch/fix_gateway.pin` holds one full 40-character commit SHA from
fix-gateway `dev`, after its comment lines. The check refuses anything else.
To bump it:

```sh
git ls-remote https://github.com/billmallard/fix-gateway refs/heads/dev   # the new SHA
# replace the SHA line in tests/arch/fix_gateway.pin
python tools/check_fix_writers.py                                          # fetches it, checks
```

and open the one-line PR. The CI step runs against the new commit. Pin a commit
that is on fix-gateway's `dev`, not a feature branch. A branch commit can be
rebased away, and the check would then fail to fetch it.

The pin is deliberate. Without it, a fix-gateway merge would change the result
of a pyEfis PR that had not changed. A newer register reaches pyEfis only
through a bump that its CI has checked.

## The concept names

ARCH0 found seven shapes of a waypoint across the two repos. pyEfis holds three
of them: `Waypoint` in `flightplan/model.py`, a second `Waypoint` in
`flightplan/waypoints.py`, and `RouteSlot`/`DirectTo` in `flightplan/fixbridge.py`.
`tests/arch/concept_names.yaml` freezes where each such name is defined. It has
fix-gateway's six names (`Waypoint`, `Point`, `Position`, `Leg`, `Plan`, `Route`)
and the pyEfis shapes ARCH0 named (`RouteSlot`, `DirectTo`, `Segment`,
`RouteSegment`, `ProcedureLeg`).

A failure like `class Waypoint: defined in src/pyefis/instruments/map/route.py`
means a new shape. Use the existing class, or give the new shape a name that
says what it is. Adding a file to `concept_names.yaml` is a one-line edit, and
it is an architecture change: under ORG-018, INTEGRATOR holds a PR that makes it
for review. When a class is merged away, remove its file from the list. The
check fails until you do, so the list only shrinks.
