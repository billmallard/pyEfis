# FIX-Gateway plugin spec: `dronecan` (DroneCAN-in)

Status: **spec, ready to implement** (authored 2026-07-05).
Target repo: `makerplane/fix-gateway` (work in the billmallard fork,
`src/fixgw/plugins/dronecan/`).
Companion docs: [canaerospace_background.md](canaerospace_background.md)
(§6: "bridge, don't migrate"),
[fixgw_canaerospace_in_spec.md](fixgw_canaerospace_in_spec.md)
(sibling bridge — read it first; the two specs share design principles
and this one only spells out the deltas where they differ).

## 1. Goal

A FIX-Gateway input plugin that subscribes to DroneCAN (UAVCAN v0)
broadcasts and writes mapped values into the FIX database. The
motivating hardware is **commodity drone-ecosystem sensors** — above
all a ~$50 external DroneCAN magnetometer, which closes the
magnetometer gap identified in the avionics roadmap (the last primary
data gap; see MAOS-DESIGN/docs/AVIONICS_STACK_ROADMAP.md). Secondary
targets: GNSS pucks, air-data probes, rangefinders (AGL), and battery
monitors from the ArduPilot/PX4 ecosystem.

Posture: CAN-FIX semantics stay the standard; DroneCAN is a federated
input. Harvest the sensors, not the protocol.

## 2. Scope and non-goals

In scope (v1):

- Subscribe to DroneCAN broadcast messages via the **`dronecan`** PyPI
  library and map DSDL message fields → FIX keys through a YAML
  mapfile (generic field-path mapper, so any broadcast type works
  without code changes).
- Node health monitoring (every DroneCAN node broadcasts
  `uavcan.protocol.NodeStatus` at ≥1 Hz) surfaced on the status page.
- Optional **dynamic node-ID allocation server** so factory-fresh
  sensors that expect a flight controller's allocator come up on our
  bus with no vendor tooling.
- Tested, documented mappings for: magnetometer, GNSS, battery/circuit
  status. (Air data and rangefinder are config-documentation only —
  the generic mapper covers them.)

Non-goals (v1):

- **No transmit of flight data** and no parameter/firmware services
  (`uavcan.protocol.param.*`, file transfer, firmware update). Sensor
  configuration stays with vendor tools / DroneCAN GUI tool.
  (The allocator and the library's own low-level protocol traffic are
  the sole intentional bus writes, and both are off/anonymous by
  default — see §5.1.)
- No Cyphal (UAVCAN v1). Different wire format, different library,
  drone-centric momentum; revisit only on hardware demand.
- No sensor fusion. Raw mag vector goes to the database; tilt-compensated
  heading is a `compute`-plugin follow-up (§8.2).
- No CAN-FIX re-broadcast of harvested values (fix-gateway *is* the
  hub; anything that must reach the CAN-FIX bus goes out through the
  existing canfix plugin's output mapping, not this plugin).

## 3. Protocol and library decisions

### 3.1 Why a library here (when the CANaerospace bridge hand-rolls)

CANaerospace is one frame = one value — ~150 lines to decode. DroneCAN
is not: 29-bit IDs packing priority/type/source, multi-frame transfers
with transfer-ID/toggle/CRC, and DSDL-generated message schemas.
Hand-rolling that is weeks of work and a maintenance liability; the
reference Python implementation already exists.

**Dependency:** `dronecan` (PyPI; MIT-licensed, pure Python, maintained
by the DroneCAN team as the successor of `uavcan` v0 / pyuavcan-v0).
Add to `[project] dependencies` in `pyproject.toml` (precedent:
`pymavlink` is already a hard dep for the mavlink plugin). Before
merging: confirm the license from the package metadata and record it in
the AC-IP-001 license map (MIT expected — compatible).

Version pin: `dronecan>=1.0` with the exact tested version noted in the
plugin docs.

### 3.2 Library facts the implementation relies on

Verify each against the installed library before coding (they drive the
design; API drift happens):

- `dronecan.make_node(port, node_id=…, bitrate=…)` — port strings like
  `"can0"` (SocketCAN), `"/dev/ttyACM0"` (SLCAN adapter), `"COMn"`
  (SLCAN on Windows). Omitting `node_id` yields an **anonymous** node
  that can still receive all broadcasts.
- `node.add_handler(dronecan.uavcan.equipment.ahrs.MagneticFieldStrength2, cb)`;
  the callback receives an event with `.message` (decoded DSDL object)
  and `.transfer` (source node id, timestamp, priority).
- `node.spin(timeout)` pumps the event loop; it is **not** thread-safe
  to call from multiple threads — all node interaction happens on the
  plugin's single MainThread.
- `dronecan.app.node_monitor.NodeMonitor(node)` tracks the node
  registry from NodeStatus traffic.
- `dronecan.app.dynamic_node_id.CentralizedServer(node, node_monitor, database_storage=path)`
  implements the allocator (requires the node to be non-anonymous).
- Message objects stringify via `dronecan.to_yaml(msg)` — use for debug
  logging only.

### 3.3 Standard messages of interest

Type names below are stable DroneCAN vocabulary; numeric DSDL type IDs
live in the library and must not be hard-coded anywhere in the plugin.

| DSDL type | Payload of interest | Units on wire |
|---|---|---|
| `uavcan.protocol.NodeStatus` | health, mode, uptime | — |
| `uavcan.equipment.ahrs.MagneticFieldStrength2` | `sensor_id`, `magnetic_field_ga[3]` | Gauss |
| `uavcan.equipment.gnss.Fix2` | lat/lon (1e-8 deg? verify), height, velocity, sats, status | SI + scaled ints |
| `uavcan.equipment.gnss.Auxiliary` | hdop/vdop | — |
| `uavcan.equipment.air_data.StaticPressure` | `static_pressure` | Pa |
| `uavcan.equipment.air_data.StaticTemperature` | `static_temperature` | K |
| `uavcan.equipment.air_data.RawAirData` | differential pressure | Pa |
| `uavcan.equipment.range_sensor.Measurement` | `range` | m |
| `uavcan.equipment.power.BatteryInfo` | voltage, current | V, A |
| `uavcan.equipment.power.CircuitStatus` | circuit_id, voltage, current | V, A |

For every mapping shipped in the example config, verify field names and
scaling by reading the DSDL source in the installed library
(`dronecan/dsdl_files/…`) — **do not trust this table for field-level
detail**, it is orientation only.

## 4. Architecture

```
src/fixgw/plugins/dronecan/
  __init__.py    # Plugin(PluginBase): config, thread, get_status()
  bridge.py      # MainThread: owns the dronecan node, handlers, spin loop
  mapping.py     # mapfile load/validate; field-path resolver; converters
```

Deltas from the sibling spec's architecture (which otherwise applies —
lifecycle contract, PluginFail on failed join, closure-style
pre-resolution of database items at load time):

- The `dronecan` library **owns the CAN socket** — there is no
  `can.ThreadSafeBus` here and no sharing the interface with the
  canfix plugin. Document loudly in the plugin docs: this plugin needs
  its own CAN interface (or a separate SLCAN adapter); putting DroneCAN
  and CAN-FIX on one physical bus is out of scope and a bad idea
  (bit-rate and ID-space collisions).
- `MainThread.run()`: create the node **inside the thread** (library
  objects are not guaranteed thread-portable), register handlers, then
  `while not self.getout: node.spin(0.5)` wrapped so that transient
  library/driver exceptions increment an error counter, log
  rate-limited, `time.sleep(1)`, and re-create the node if the driver
  died (`spin` raising repeatedly = reopen). On exit call
  `node.close()`.
- Import of `dronecan` happens at module top like `pymavlink` in the
  mavlink plugin (hard dep, no guard needed once it's in
  `pyproject.toml`).

## 5. Configuration

### 5.1 Connection config — `src/fixgw/config/connections/dronecan.yaml`

```yaml
# DroneCAN sensor input bridge (magnetometer, GNSS, air data, power)
dronecan:
  load: no
  module: fixgw.plugins.dronecan
  # SocketCAN: "can1"; SLCAN USB adapter: "/dev/ttyACM0" or "COM5"
  port: can1
  bitrate: 1000000        # DroneCAN convention; many sensors also run 500k/250k
  # node_id absent/null -> anonymous listen-only node (default posture).
  # Set a node id (1..125) only if you enable the allocator below or a
  # sensor requires seeing a live node to start publishing.
  node_id: null
  # Dynamic node-ID allocation server. Requires node_id to be set.
  # Turn on for factory-fresh sensors that wait for an allocator.
  allocator: false
  allocator_db: "{CONFIG}/dronecan/allocation.db"   # persisted allocations
  mapfile: "{CONFIG}/dronecan/map.yaml"
```

Config validation: `allocator: true` with `node_id: null` is a startup
`ValueError` with a clear message.

### 5.2 Mapfile schema — `src/fixgw/config/dronecan/map.yaml`

```yaml
inputs:
  - message: uavcan.equipment.ahrs.MagneticFieldStrength2
    source_node: null          # optional int; filter by sender node id
    where:                     # optional field equality guards
      sensor_id: 0
    fields:
      - path: magnetic_field_ga[0]
        fixid: MAGX
      - path: magnetic_field_ga[1]
        fixid: MAGY
      - path: magnetic_field_ga[2]
        fixid: MAGZ

  - message: uavcan.equipment.power.CircuitStatus
    where: { circuit_id: 0 }
    fields:
      - { path: voltage, fixid: VOLT }
      - { path: current, fixid: CURRNT }

  - message: uavcan.equipment.air_data.StaticTemperature
    fields:
      - { path: static_temperature, fixid: OAT, converter: k2c }
```

Field entries support the same `scale`, `offset`, `converter` options
(and the same converter names) as the CANaerospace mapfile — keep the
converter table in one shared place if trivial (`fixgw/plugins/…` may
not have a natural shared home; duplicating the ~10-line dict in each
plugin's `mapping.py` is acceptable, a shared `fixgw/units.py` is
better if upstream is receptive).

Semantics:

- `message` is resolved at load time via attribute walk on the
  `dronecan` module (`dronecan.uavcan.equipment.ahrs.MagneticFieldStrength2`);
  unknown type = load-time `ValueError` with the yaml line.
- `path` grammar: dotted names and integer indices
  (`foo.bar[2]`, `magnetic_field_ga[0]`). Resolved lazily per message
  but compiled to an accessor closure at load.
- Multiple `inputs` entries for the same `message` are allowed
  (e.g. two mags distinguished by `where: {sensor_id: …}` or
  `source_node:`) — register one handler per message type that runs all
  matching entries.
- `where` guard mismatch and `source_node` mismatch increment
  `filtered_count`, not an error.
- Missing field at runtime (DSDL rev drift): count `path_error_count`,
  warn once per (message, path).

### 5.3 GNSS key vocabulary

Mirror the existing GPS-source plugins **exactly** — before writing the
GNSS example, read `fixgw/plugins/gpsd/__init__.py` and
`fixgw/plugins/garmin_gnx375/__init__.py` and reuse the same fixids
(LAT/LONG, ground speed, track, GPS altitude as those plugins name
them). The Fix2 example ships commented out until bench-checked against
a real GNSS node, Rotax-mapfile style.

## 6. Runtime behavior

- **Handlers are thin**: decode is done by the library; the handler
  applies guards, runs accessor closures, converts, `db_write`s.
  Wrap the handler body in try/except with counted, rate-limited
  warnings — a malformed transfer must never kill the spin loop.
- **Staleness**: none in the plugin; FIX `tol` handles it (mag keys get
  their own `tol`, §8.1).
- **NodeStatus / health**: always subscribe (independent of mapfile).
  Maintain `nodes: {node_id: {health, mode, uptime, last_seen}}` via
  NodeMonitor (or a plain handler if NodeMonitor requires
  non-anonymous mode — verify; fall back to the plain handler).
  A node transitioning to WARNING/ERROR/CRITICAL logs at WARNING.
  v1 does not write health to any fixid (follow-up: latched
  annunciator keys, same posture as the CANaerospace EED decision).
- **Allocator**: when enabled, construct NodeMonitor + CentralizedServer
  after the node; the allocation DB path comes from config. Log each
  allocation at INFO. This is ~10 lines with the library.

`get_status()`:

```
Port, Bitrate, Node ID (or "anonymous"), Allocator (on/off),
Transfers Received, Values Written, Filtered, Path Errors,
Spin Errors / Reopens,
Nodes (dict: node_id -> {health, mode, uptime_s, last_seen_age_s})
```

## 7. The magnetometer use case, end to end

This is the acceptance use case; the plugin is done when this works.

1. Mag (e.g. any ArduPilot-ecosystem DroneCAN compass, RM3100/…-based)
   on `can1` at 1 Mbps, allocator on first boot if the unit ships
   without a static ID.
2. Plugin maps `magnetic_field_ga[0..2]` → `MAGX/MAGY/MAGZ`
   (new keys, §8.1).
3. pyEfis/status shows the raw vector moving as the sensor rotates.
4. **Out of scope for the plugin but specified now** (§8.2): a compute
   stage derives tilt-compensated magnetic heading from
   MAGX/MAGY/MAGZ + PITCH/ROLL into HEAD, with hard/soft-iron
   calibration constants from config. Until that lands, MAGX/Y/Z are
   present-but-unconsumed, which is fine.

## 8. FIX database impact

### 8.1 New keys (this plugin's database yaml addition)

Add to `src/fixgw/config/database/ahrs.yaml` (or `custom.yaml` if
upstream prefers; ask in the PR):

```yaml
- key: MAGX     # repeat for MAGY, MAGZ
  description: Raw magnetic field, body X axis
  type: float
  min: -10.0
  max: 10.0
  units: gauss        # matches the wire; compute layer normalizes
  initial: 0.0
  tol: 2000
```

Rationale for Gauss over µT: identical to the wire value → the bridge
stays a pure translator and calibration constants live in one place
(the compute stage). Note `MAGW` (magnetic sensor warning, 0–5) already
exists in `ahrs.yaml:537` — the future compute stage, not this plugin,
owns it.

### 8.2 Follow-up items created by this spec (not v1 deliverables)

- `compute` plugin (or a small new plugin): MAG vector + PITCH/ROLL →
  HEAD, with calibration. Track as a fix-gateway issue when this plugin
  merges — it closes the roadmap's magnetometer gap for real.
- Optional AGL key for `range_sensor.Measurement` if/when a rangefinder
  shows up on the bench.

## 9. Testing

No CAN hardware and no vcan in CI — the `dronecan` library constructs
and decodes DSDL objects without any bus, which enables the megasquirt
test pattern (`tests/plugins/megasquirt/test_megasquirt.py`):

1. **Mapping tests** (`tests/plugins/dronecan/test_mapping.py`):
   build real DSDL objects
   (`dronecan.uavcan.equipment.ahrs.MagneticFieldStrength2(magnetic_field_ga=[…])`),
   wrap them in a fake event (`SimpleNamespace(message=…, transfer=…)`),
   call the handler, assert `db_write` calls: path resolution incl.
   indices, `where` guards, `source_node` filter, converters,
   path-error counting on a fabricated wrong-shape object.
2. **Mapfile validation tests**: unknown message type, bad path syntax,
   duplicate handling, missing fixid honoring `ignore_fixid_missing`.
3. **Lifecycle tests**: monkeypatch `dronecan.make_node` (and
   NodeMonitor/CentralizedServer when allocator on) with fakes;
   assert node created inside the thread with configured port/bitrate,
   spin-loop exception → counted reopen, `stop()` joins and closes,
   PluginFail when the thread won't die, allocator+null-node-id
   rejected at init.
4. **Bench check (manual, not CI)**: documented procedure in the plugin
   docs — real mag on SLCAN or the Pi, allocator bring-up from factory
   state, rotate-and-watch MAGX/Y/Z. The Pi test unit (`ssh pyefis`)
   is the reference bench.

## 10. Documentation

`doc/plugins/dronecan.rst` (add to `doc/plugins/toc.rst`): scope and
"bridge, don't migrate" framing, the one-physical-bus warning (§4),
config + mapfile reference, allocator explanation for people who've
never seen DroneCAN dynamic addressing, supported-message examples,
bench procedure, and the §8.2 follow-ups. GPLv2+ headers on all files.

## 11. Acceptance criteria

- [ ] `pytest tests/plugins/dronecan` green on Windows and Linux with
      no CAN interface present (library objects only, fakes for the
      node).
- [ ] All shipped mapfile examples' field names verified against the
      installed library's DSDL sources; GNSS example keys verified
      against gpsd/gnx375 plugin vocabulary; unverified examples ship
      commented out.
- [ ] MAGX/MAGY/MAGZ database keys added with the §8.1 definition.
- [ ] Bench: real DroneCAN magnetometer → live MAGX/Y/Z in `fixgwc`
      on the Pi, including first-boot dynamic allocation with
      `allocator: true`.
- [ ] Malformed/foreign bus traffic soak (e.g. an ESC chattering on the
      same bus) never kills the spin loop; counters tell the story.
- [ ] `dronecan` dependency added to `pyproject.toml`, license
      confirmed and recorded per AC-IP-001 discipline.
- [ ] Connection yaml ships `load: no`; black-formatted.

References:

- DroneCAN specification: https://dronecan.github.io/Specification/
- `dronecan` Python library: https://pypi.org/project/dronecan/ and
  https://github.com/dronecan/pydronecan
- Background/rationale: [canaerospace_background.md](canaerospace_background.md) §6
- Sibling spec (shared principles): [fixgw_canaerospace_in_spec.md](fixgw_canaerospace_in_spec.md)
- Plugin patterns: `fix-gateway/src/fixgw/plugins/mavlink/` (external
  protocol lib as hard dep), `megasquirt` tests (fake-driven testing)
