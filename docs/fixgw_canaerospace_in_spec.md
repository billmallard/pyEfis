# FIX-Gateway plugin spec: `canaerospace` (CANaerospace-in)

Status: **spec, ready to implement** (authored 2026-07-05).
Target repo: `makerplane/fix-gateway` (work in the billmallard fork,
`src/fixgw/plugins/canaerospace/`).
Companion docs: [canaerospace_background.md](canaerospace_background.md)
(history + why this is an input bridge, not a migration),
[fixgw_dronecan_in_spec.md](fixgw_dronecan_in_spec.md) (sibling bridge).

## 1. Goal

A listen-only FIX-Gateway input plugin that decodes CANaerospace
(V1.7) frames from a CAN interface and writes mapped values into the
FIX database. The motivating device is the **Rotax 912iS/915iS engine
ECU**, which broadcasts engine data as CANaerospace — this plugin gives
any MakerPlane panel native Rotax engine instruments with no extra
hardware beyond a CAN transceiver.

Posture (from the background doc §6): CAN-FIX semantics are the
standard; CANaerospace is a **federated input**. Consume it; don't
adopt it.

## 2. Scope and non-goals

In scope (v1):

- Receive-only decode of CANaerospace **Normal Operation Data** (NOD)
  and **Emergency Event Data** (EED) frames with 11-bit identifiers.
- Data-driven mapping (YAML mapfile) from `(canid, element)` →
  FIX database key, with scale/offset and named unit converters.
- Source-node filtering with a priority policy (Rotax dual-lane).
- A Rotax iS mapfile skeleton + a bench-capture procedure to fill it.
- A bus simulator script for hardware-free development and tests.

Explicit non-goals (v1) — do not build these:

- **No transmit.** Not even Node Service replies (IDS). The plugin is a
  silent listener; on an engine bus, zero bus impact is a feature.
- No 29-bit identifier support (CANaerospace allows it; Rotax doesn't
  need it).
- No Node Service Data handling (ID ranges 128–199 / 2000–2031) beyond
  counting-and-ignoring.
- No sensor fusion, no derived values — that belongs in the `compute`
  plugin.
- No new PyPI dependency. `python-can` (already a hard dep,
  `pyproject.toml:40`) is sufficient; the decode layer is ~150 lines
  and is implemented in-plugin. Do **not** vendor or depend on any
  third-party CANaerospace library.

## 3. Protocol summary (decode rules)

Authoritative source: **CANaerospace Interface Specification V1.7**
(canas_17.pdf, linked in §11). The tables below were written from
memory of that spec cross-checked against Pavel Kirienko's C library —
**transcribe/verify both tables against the PDF before coding**; the
PDF is the tie-breaker.

### 3.1 Frame layout

Every CANaerospace frame has a DLC of 4–8 and this payload layout:

| Byte | Field | Meaning |
|---|---|---|
| 0 | Node-ID | Sending node (0 = broadcast/from-anyone semantics vary by channel) |
| 1 | Data Type | Enum selecting the encoding of bytes 4–7 (see 3.3) |
| 2 | Service Code | For NOD frames this is application/status usage — expose it, never gate on it |
| 3 | Message Code | Per-sender sequence number, wraps at 255 |
| 4–7 | Data | 0–4 bytes, **big-endian** |

The CAN arbitration ID is the *parameter identity* (which quantity this
is); the payload self-describes the encoding. This is the flexibility
Phil's 2013 critique targeted — the plugin absorbs that complexity once
so endpoints don't have to.

### 3.2 Standard identifier distribution (11-bit)

| CAN ID range | Channel | v1 handling |
|---|---|---|
| 0–127 | Emergency Event Data (EED) | decode; log WARNING; optional mapping (§6.5) |
| 128–199 | Node Service High (NSH) | count as ignored |
| 200–299 | User-Defined High (UDH) | mappable like NOD |
| 300–1799 | Normal Operation Data (NOD) | primary mapping range |
| 1800–1899 | User-Defined Low (UDL) | mappable like NOD |
| 1900–1999 | Debug Service Data (DSD) | count as ignored |
| 2000–2031 | Node Service Low (NSL) | count as ignored |

Note: an installation may use a *non-standard* distribution — this is
legal CANaerospace, and Rotax may use IDs anywhere. Therefore the
mapfile, not the channel table, is the final authority on which IDs are
decoded: any mapped canid in 0–2031 is accepted; the channel table only
drives default handling for *unmapped* traffic.

### 3.3 Data types (byte 1)

v1 must implement the types marked ●; the rest may raise a counted
"unsupported type" and be skipped.

| Code | Name | Encoding of bytes 4–7 | v1 |
|---|---|---|---|
| 0 | NODATA | no data | ● (write nothing; count) |
| 1 | ERROR | 4-byte error code | ● (mark mapped fixid failed, §6.4) |
| 2 | FLOAT | IEEE-754 single, big-endian | ● |
| 3 | LONG | int32 BE | ● |
| 4 | ULONG | uint32 BE | ● |
| 5 | BLONG | 32-bit bitfield | ● (deliver as int) |
| 6 | SHORT | int16 BE (bytes 4–5) | ● |
| 7 | USHORT | uint16 BE | ● |
| 8 | BSHORT | 16-bit bitfield | ● |
| 9 | CHAR | int8 (byte 4) | ● |
| 10 | UCHAR | uint8 | ● |
| 11 | BCHAR | 8-bit bitfield | ● |
| 12 | SHORT2 | 2× int16 BE | ● (element-addressable) |
| 13 | USHORT2 | 2× uint16 BE | ● |
| 14 | BSHORT2 | 2× 16-bit bitfield | ● |
| 15 | CHAR4 | 4× int8 | ● |
| 16 | UCHAR4 | 4× uint8 | ● |
| 17 | BCHAR4 | 4× 8-bit bitfield | ● |
| 18 | CHAR2 | 2× int8 | ● |
| 19 | UCHAR2 | 2× uint8 | ● |
| 20 | BCHAR2 | 2× bitfield | ● |
| 21 | MEMID | uint32 | – |
| 22 | CHKSUM | uint32 | – |
| 23 | ACHAR | 1 ASCII char | – |
| 24 | ACHAR2 | 2 ASCII | – |
| 25 | ACHAR4 | 4 ASCII | – |
| 26 | CHAR3 | 3× int8 | ● |
| 27 | UCHAR3 | 3× uint8 | ● |
| 28 | BCHAR3 | 3× bitfield | ● |
| 29 | ACHAR3 | 3 ASCII | – |
| 30 | DOUBLEH | high half of float64 | – |
| 31 | DOUBLEL | low half of float64 | – |
| 100–255 | user-defined | opaque | – |

Multi-element types (SHORT2, UCHAR4, …) are addressed in the mapfile
with `element: 0..3`; a single frame may feed several fixids (e.g. one
UCHAR4 frame carrying four CHT bytes → four mapfile entries with the
same canid, elements 0–3).

## 4. Architecture

New package `src/fixgw/plugins/canaerospace/` with three modules,
imitating the `canfix` plugin's shape
(`src/fixgw/plugins/canfix/__init__.py`):

```
canaerospace/
  __init__.py    # Plugin(PluginBase): lifecycle, bus, thread, get_status()
  protocol.py    # pure functions/dataclass: frame -> CanasMessage; no fixgw imports
  mapping.py     # Mapping: loads mapfile, closure-based dispatch, node priority
```

- `protocol.py` is **pure and dependency-free** (stdlib `struct` only)
  so it can be unit-tested against hex vectors and reused by the
  simulator tool. Public surface:
  `parse(arbitration_id, data: bytes) -> CanasMessage` where
  `CanasMessage` has `canid, node_id, data_type, service_code,
  message_code, values (tuple), channel (enum: EED/NSH/UDH/NOD/UDL/DSD/NSL)`.
  Raises `CanasDecodeError` on bad DLC/unknown mandatory field.
- `mapping.py` follows the closure pattern of
  `canfix/mapping.py` (pre-resolved `database.get_raw_item` closures in
  a `canid → element → func` lookup, built once at load; a 2048-slot
  `interesting` boolean list for the hot-path reject, exactly like
  `canfix/__init__.py:43`).
- `__init__.py` follows the standard lifecycle contract:
  - `Plugin.__init__(name, config, config_meta)`: parse config, build
    `Mapping`, construct `MainThread`.
  - `Plugin.run()`: `self.bus = can.ThreadSafeBus(channel, interface=interface)`,
    start thread.
  - `MainThread.run()`: `msg = self.bus.recv(1.0)` loop with `getout`
    flag checked in `finally`.
  - `Plugin.stop()`: set `getout`, `join(1.2)` (must exceed the recv
    timeout), raise `plugin.PluginFail` if still alive — copy the
    canfix `stop()` verbatim.
  - `get_status()` returns an `OrderedDict` (§6.6).

## 5. Configuration

### 5.1 Connection config

Ship `src/fixgw/config/connections/canaerospace.yaml`:

```yaml
# CANaerospace input bridge (e.g. Rotax 912iS / 915iS ECU)
canaerospace:
  load: no
  module: fixgw.plugins.canaerospace
  # python-can options. Bit rate is an interface-level concern:
  # for socketcan set it with `ip link set can0 up type can bitrate ...`;
  # for serial/slcan adapters see python-can docs.
  interface: socketcan
  channel: can0
  mapfile: "{CONFIG}/canaerospace/rotax_is_map.yaml"
  # Seconds without a frame from the preferred node before a
  # lower-priority node's data is accepted (dual-lane failover).
  node_timeout: 2.0
```

`{CONFIG}` expansion: `config["mapfile"].format(CONFIG=config["CONFIGPATH"])`,
same as `canfix/__init__.py:153`.

### 5.2 Mapfile schema

Ship `src/fixgw/config/canaerospace/rotax_is_map.yaml` (skeleton, §7)
plus schema validation in `Mapping.__init__` mirroring
`canfix/mapping.py validate_mapping_inputs()` (use `fixgw.cfg.from_yaml`
with `metadata=True` so error messages carry file/line, and honor an
`ignore_fixid_missing` top-level bool exactly like canfix).

```yaml
ignore_fixid_missing: false

inputs:
  - canid: 0x18C          # required, 0..2031
    fixid: TACH1          # required, validated against database.listkeys()
    type: USHORT          # optional; if set, frames with a different
                          # data type are counted as type_mismatch and,
                          # by default, still decoded (see strict_types)
    element: 0            # optional, default 0; index into multi-element types
    scale: 1.0            # optional, default 1.0  (value*scale + offset)
    offset: 0.0           # optional, default 0.0
    converter: none       # optional named converter, applied AFTER scale/offset:
                          #   k2c (Kelvin->degC), c2f, kpa2inhg, kpa2psi,
                          #   mps2knots, m2ft, pct (0..1 -> 0..100)
    nodes: [16, 17]       # optional; allowed sender node-ids in priority
                          # order (Rotax lane A, lane B). Absent = accept any.

events:                   # optional; EED channel (canid 0..127)
  - canid: 0x00
    fixid: EGWARN         # a bool/int fixid to set true when seen
    match_code: null      # optional; only fire when the 4-byte payload == this

strict_types: false       # if true, a type mismatch drops the frame
```

Rules:

- Reject duplicate `(canid, element)` pairs at load with a
  `ValueError` naming the line (via `cfg.message`).
- Unknown top-level keys: warn, don't fail.
- A missing mapfile is a hard `ValueError` (canfix precedent,
  `mapping.py:46`).

## 6. Runtime behavior

### 6.1 Decode pipeline (hot path)

```
bus.recv(1.0)
  -> arbitration_id > 2031 or not interesting[]  -> recvignorecount++
  -> protocol.parse()                            -> on CanasDecodeError: recvinvalidcount++
  -> node filter / priority (6.3)                -> rejected: recvignorecount++
  -> type check (6.2)
  -> raw = values[element]; v = raw*scale + offset; v = converter(v)
  -> db_write(fixid, v)   (out-of-range ValueError from the database
                           layer: recvinvalidcount++, debug log, continue)
```

Never let an exception escape the thread loop; wrap the per-frame body
in try/except with a counted, rate-limited warning (log the first
occurrence per canid at WARNING, subsequent at DEBUG).

### 6.2 Data-type discipline

The frame's type byte is authoritative for decoding (self-identifying
protocol). The mapfile `type:` is an *expectation check*: mismatch
increments `type_mismatch_count`; the frame is still decoded unless
`strict_types: true`. This keeps a Rotax firmware update that changes
USHORT→ULONG visible in status without silently corrupting values
(the decode follows the wire, the counter tells the human).

### 6.3 Source-node redundancy (Rotax lane A / lane B)

The 912iS has two ECU lanes; both may broadcast the same parameters
from different node-ids. Policy, per mapping entry with `nodes:`:

- Maintain `last_seen[node]` (`time.monotonic()`) per entry.
- A frame from list position *i* is written only if every
  higher-priority node (positions `< i`) is stale:
  `monotonic() - last_seen > node_timeout`.
- A frame from a node not in the list: `recvignorecount++`.
- Entries without `nodes:` accept any sender.

This is ~30 lines and prevents lane flip-flop on the panel. No
"lane failed" annunciation in v1 — the FIX database `tol` mechanism
already marks the fixid *old* if both lanes go quiet.

### 6.4 ERROR and NODATA types

- `NODATA`: count (`nodata_count`), write nothing.
- `ERROR` on a mapped `(canid, element=0)`: mark the mapped fixid
  failed until the next good value — use the raw item's flag interface
  (see how `canfix/mapping.py:183` writes the
  `(value, annunciate, quality, failure)` tuple; check
  `fixgw/database.py` for the item's `fail` property and prefer setting
  the flag without disturbing the value). Count in `error_frame_count`
  and log the 4-byte error code at WARNING (rate-limited per canid).

### 6.5 Emergency Event Data

EED frames (canid 0–127) are always logged at WARNING with node-id and
payload hex. If an `events:` entry matches, write `True` (or `1`) to
the fixid. No auto-reset: the sender's event is edge-triggered, so the
fixid should be a latched annunciator reset by the pilot/screen logic;
say so in the plugin docs.

### 6.6 Message-code continuity and status

Track the last Message Code per `(canid, node_id)`; a gap other than
+1 (mod 256) increments `seq_gap_count`. Do not gate decoding on it —
it's a bus-health telltale only.

`get_status()` (shown by `fixgwc` and the status screen):

```
CAN Interface, CAN Channel,
Received Frames, Decoded Writes, Ignored Frames, Invalid Frames,
Type Mismatches, Unsupported Types, Error Frames, NoData Frames,
Sequence Gaps, Emergency Events,
Nodes Seen (dict: node_id -> {frames, last_seen_age_s})
```

## 7. Rotax iS profile (mapfile deliverable)

### 7.1 What is established

- The 912iS/915iS ECU broadcasts engine data as CANaerospace frames on
  its external CAN bus; every glass-panel vendor (Dynon, MGL, Kanardia,
  Stock/RS Flight Systems EMU) consumes it.
- Parameters known to be on the bus (names, not yet IDs): engine RPM,
  manifold/airbox pressure, throttle position, oil pressure, oil
  temperature, coolant temperature, EGTs, fuel pressure (915iS),
  ECU/system voltage, lane status + warning bits, engine run time.

### 7.2 What must be verified before the mapfile is trusted

**Do not invent CAN IDs.** The authoritative sources, in order:

1. Rotax Installation Manual for the 912 iS/915 iS, CAN bus appendix
   (BRP-Rotax publishes the broadcast frame list; available via the
   Rotax owner/OEM portal).
2. A bench capture from a real engine or ECU (`candump -ta can0`
   via a USB-CAN adapter or the Pi's CAN HAT; correlate values against
   the cockpit display while varying RPM/temps).
3. Open-source decoders as cross-checks (search GitHub for
   "Rotax 912iS CAN", Kanardia/MGL protocol notes).

Also verify the bus **bit rate** from source 1 before bench day
(250 kbit/s and 500 kbit/s are both plausible; it is an `ip link`
setting, not plugin code).

### 7.3 Deliverable format

`rotax_is_map.yaml` ships with the full parameter table present but
**commented out**, each line carrying the FIX key decision (these are
final — they're the existing engine vocabulary in
`src/fixgw/config/database/engine.yaml`):

| Rotax parameter | FIX key | converter notes |
|---|---|---|
| Engine speed | `TACH1` | rpm, none expected |
| Manifold pressure | `MAP1` | likely kPa or hPa → `kpa2inhg` |
| Oil pressure | `OILP1` | likely kPa → `kpa2psi` |
| Oil temperature | `OILT1` | likely K or °C → `k2c` if needed (DB units °C/°F per config) |
| Coolant temp | `H2OT1` | as above |
| EGT cyl n | `EGT1n` | one entry per reported cylinder |
| Throttle position | `THR1` | likely 0–1 or % → `pct` if needed |
| Fuel pressure (915iS) | `FUELP1` | |
| System voltage | `VOLT` | |
| Lane/status word | (v1: status page only; latching annunciator keys are a follow-up) | BSHORT/BLONG bitfield |

An entry is uncommented only after it has passed a bench check. The
mapfile header must say exactly that.

## 8. FIX database impact

None. All target keys above already exist (engine keys are templated
per engine/cylinder in `database/engine.yaml`). This plugin adds no
database yaml.

## 9. Testing

Follow the two existing test styles:

1. **Pure decode tests** (`tests/plugins/canaerospace/test_protocol.py`):
   hex-vector table like `tests/plugins/canfix/conftest.py ptests_data`
   — `(arbitration_id, payload_hex, expected CanasMessage fields)`.
   Cover every ● type incl. big-endian sign edge cases, DLC 4 (NODATA),
   DLC<4 rejection, multi-element extraction, and one vector transcribed
   from a worked example in canas_17.pdf itself (provenance anchor).
2. **Mapping/unit tests** (`test_mapping.py`): FakeParent/FakeBus style
   from `tests/plugins/megasquirt/test_megasquirt.py` — feed
   `SimpleNamespace(arbitration_id=…, data=…)` frames, assert
   `db_write` tuples, scale/offset/converter math, node-priority
   failover (monkeypatch `time.monotonic`), strict_types behavior,
   ERROR flagging, mapfile validation errors (bad canid, dup
   (canid,element), missing fixid with/without ignore_fixid_missing).
3. **Plugin lifecycle test**: virtual-bus integration like
   `tests/plugins/canfix/conftest.py` (`interface: virtual`,
   `channel: tcan0`) — start plugin, send frames with `can.Bus`,
   assert database values via the real database fixture, assert
   `get_status()` counters, stop cleanly (PluginFail path covered by
   monkeypatched thread like the megasquirt lifecycle test).

**Simulator tool** (`src/fixgw/tools/canas_sim.py`): sends a scripted
set of CANaerospace frames (reusing `protocol.py` in reverse — add a
`build()` inverse function, which the decode tests then round-trip)
onto any python-can interface at configurable rates. Used for the
virtual-bus tests and for desk demos; its default script is the Rotax
skeleton parameters with plausible values.

## 10. Documentation

- `doc/plugins/canaerospace.rst` following `doc/plugins/canfix.rst`:
  what it is, one paragraph of the background doc's "consume it, don't
  adopt it" framing, config reference, mapfile reference, Rotax
  bench-verification procedure (§7.2), simulator usage. Add to
  `doc/plugins/toc.rst`.
- GPLv2+ header block on every new file (copy from an existing plugin;
  new files may credit "MakerPlane contributors").

## 11. Acceptance criteria

- [ ] `pytest tests/plugins/canaerospace` green on Windows and Linux
      (no socketcan dependency in tests; `virtual` interface only).
- [ ] Data-type and ID-distribution tables in `protocol.py` verified
      line-by-line against canas_17.pdf (cite section numbers in code
      comments — this is the one place a "source" comment is a
      constraint, not noise).
- [ ] `canas_sim.py` + plugin on a virtual bus drives TACH1/OILP1/…
      visibly in `fixgwc` — and in pyEfis on the Windows twin.
- [ ] Rotax mapfile ships fully commented-out with the §7.3 table and
      verification instructions; no invented IDs anywhere.
- [ ] `get_status()` shows all §6.6 counters; unsupported/invalid
      traffic never kills the thread (soak: simulator fuzz script
      sending random payloads for 60 s, plugin still healthy).
- [ ] Connection yaml ships with `load: no`; default server config
      untouched otherwise.
- [ ] Black-formatted (`[tool.black]` config exists); no new deps.

References:

- CANaerospace V1.7 spec: https://www.stockflightsystems.com/tl_files/downloads/canaerospace/canas_17.pdf
- Kirienko C implementation (cross-check for enums): https://github.com/mjs513/CANaerospace/tree/master/pavel_kirienko-canaerospace
- Background/rationale: [canaerospace_background.md](canaerospace_background.md)
- Plugin patterns: `fix-gateway/src/fixgw/plugins/canfix/`, `fix-gateway/src/fixgw/plugins/megasquirt/`
