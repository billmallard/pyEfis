# FIX dynamic-list model, with the ADS-B traffic contract

Status: **SPEC, 2026-10-31** -- closes the pyEfis #52 decision; ready for the
traffic implementation items (fix-gateway writer, pyEfis #53 layer).
Authority: `MAOS-DESIGN/docs/AVIONICS_STACK_ROADMAP.md` §9.2 names this the
single most important open interface item and frames the three candidate
shapes; this document closes it and does not restate the framing.
Target repos: `billmallard/fix-gateway` (database YAML + traffic writer),
`billmallard/pyEfis` (consumer). Pattern: [fixgw_canaerospace_in_spec.md](fixgw_canaerospace_in_spec.md).
Tracking: AER-4336 (BACKLOG `P3`, CAP-401).

Code citations are against fix-gateway `dev` @ `b15055e` and pyEfis `dev` @
`71daf5c`. GDL90 citations are to the **GDL 90 Data Interface Specification,
560-1058-00 Rev A, 2007-06-05** (Garmin AT; the public copy the FAA hosts, see
§8), by section and table, written **G§** (G§3.5.1.4)
to keep them apart from this document's own § numbers.

---

## 0. The decision, in one paragraph

A variable-length list crosses the FIX bus as an **indexed key block**: a
fixed number of slots, each slot a set of ordinary scalar keys named
`<PREFIX><n><FIELD>`, plus a few block-level keys. This is the shape the route
already uses (`FPL1..100`, decided in `makerplane/briefs/flight_plan_plan.md`
§3.2 and recorded by Bill on #52), and traffic adopts it. What the two lists do
**not** share is how a reader knows a slot is complete and how a slot gets
reused, so the model has two **commit disciplines**: *block commit* (one
counter written last, the whole list is atomic -- the route) and *slot commit*
(one identity key per slot written last, each entry is atomic on its own --
traffic). Everything else -- naming, capacity, aging, quality flags,
one-key-one-writer -- is one set of rules for both.

## 1. Scope

In scope: the general model (§2); the route block restated as an instance of
it, with no change to its keys (§3); the new traffic block and its GDL90
decode contract (§4); what the display may assume (§5); every place the FIX
model departs from GDL90 semantics (§6); a hardware-free test plan (§7).

Not in scope: code. The fix-gateway traffic writer, the database YAML, the
pyEfis traffic layer, and the prerequisites found while writing this (§9) are
separate follow-on items. No threat or alerting logic is specified here -- the
gateway republishes what the receiver says; collision-avoidance semantics are
not something a display may infer from this block.

---

## 2. The general model

### 2.1 Chosen shape: indexed key blocks

Each list is a block of `N` slots. Slot `n` (1-based) is a set of scalar FIX
keys, one per field, each with its own type, units, min/max, `tol` and quality
flags -- i.e. each field is an ordinary database item and gets everything the
bus already does for scalars (persistence, recording, playback, netfix
subscription, per-key quality). A handful of block-level keys describe the
list as a whole.

### 2.2 The two rejected shapes, and why

**Structured value (one key holding a JSON or delimited string).** Rejected
for the route in `flight_plan_plan.md` §3.2 and the reasons are worse for
traffic:

- netfix is a line protocol, `KEY;VALUE;FLAGS\n`
  (`plugins/netfix/__init__.py:63-74`), with no escaping for `;` or newline,
  and a 1024-byte default buffer (`netfix/__init__.py:48-51`). Thirty-two
  targets of ~15 fields do not fit and cannot be escaped.
- It throws away per-field quality. GDL90 marks altitude, velocity, vertical
  rate and track individually unavailable (G§3.5.1.4, .7, .8, .9); a single
  string key has one `bad` flag for the whole list.
- Every consumer -- display, recorder, playback, a second head -- must parse
  it, and the writer must rewrite the whole list every second to change one
  target.

**Side channel (a file, socket, or shared object outside the database).**
Rejected because it is outside the one normalized model of aircraft state
(roadmap §2: the display, the recorder, the maintenance port and the ground
link all read the key database). A second display or control head would not
see it, `data_recorder`/`data_playback` would not capture it, and it would need
its own staleness and quality conventions, duplicating the bus's.

The cost of the chosen shape is key count (fields x N) and the need for the
commit disciplines below. The route block is already over 2,000 keys
(`flightplan.yaml`, 20 slot and segment-table fields x `f: 100`), so
traffic's 578 (18 x 32 + 2) is inside what the gateway already carries.

### 2.3 Naming and the index letter

- Slot keys are `<PREFIX><index><FIELD>`, written in the YAML with a lowercase
  **index letter** in place of `<index>`: `FPLfLAT`, `TFCkLAT`. The database
  expands any lowercase character in a key name as an index variable
  (`database.py:313-333`), so **field and prefix names must be uppercase
  letters and digits only** -- a stray lowercase letter is silently treated as
  a second index.
- The letter and its count are registered in `config/database/variables.yaml`.
  Letters in use today: `a b c d e f g n r s t w`. This spec registers
  **`k`** for traffic. A letter is never reused for a second list; a list that
  must share a capacity with another indexes on the other's letter
  (the route segment table `FPLSf*` indexes on `f`, `flightplan.yaml`).
- Prefix: three uppercase letters, unique (`FPL`, `TFC`). Block-level keys use
  the prefix plus a word with no index (`FPLCOUNT`, `TFCCOUNT`).

### 2.4 Capacity

`N` is fixed when the database loads; raising it is one number in
`variables.yaml` and costs fields x delta keys. A consumer must not hard-code
`N` beyond the gateway it talks to: it either takes `N` from its own config,
matched to the gateway's, or discovers it from the netfix key list (`@l`).
A writer with more entries than slots applies the list's **overflow rule**
(route: reject the commit; traffic: §4.6) and never silently truncates without
a visible count.

### 2.5 Commit disciplines

A reader can observe a slot between two field writes. The discipline says
which single key's write means "this slot (or this list) is now consistent":

| | Block commit | Slot commit |
|---|---|---|
| Use when | the list is edited as a unit by one actor | entries arrive and die independently |
| Commit key | one block counter, `<PFX>SEQ`, incremented last | one identity key per slot, `<PFX><n>TGT` (or ID), written last in every slot update |
| Reader acts on | the counter's change: re-read every slot | the identity key's write: re-read that slot |
| Atomic unit | whole list | one slot |
| Instance | route (`FPLSEQ`) | traffic (`TFCkTGT`) |

Both rely on one ordering guarantee: **a subscriber sees one writer's writes
in the order they were made.** In-process plugins write through
`database.write`, whose value setter fires callbacks synchronously
(`database.py` value setter, `send_callbacks()`); netfix queues every outbound
update for a connection on one FIFO (`netfix/__init__.py:47`, `:74`) drained
by one send thread; and netfix processes one inbound connection's writes in
order (`flight_plan_plan.md` §3.2). This is load-bearing and is tested end to
end (§7, T8), not assumed.

### 2.6 Slot assignment and reuse

- **Positional** lists (route): slot `n` is the `n`th entry; order is meaning.
  Slots past `<PFX>COUNT` are empty.
- **Identity-allocated** lists (traffic): an entry's identity maps to whichever
  slot the writer allocated; slot order carries **no** meaning. An empty slot
  is marked by its identity key holding the empty value.
- **Reuse rule (identity-allocated):** a slot never changes identity in one
  step. The writer empties it (identity key -> empty, written **first**), and
  only then fills it for the new entry (fields, then identity last). A reader
  therefore never pairs one entry's identity with another's fields.

### 2.7 Aging and staleness -- two layers, both required

1. **Consumer layer, `tol`.** Every slot key carries a `tol` (ms). The database
   reports `old` when a key's age exceeds it (`database.py:138-155`) and the
   periodic `update()` latches it and fires callbacks (`database.py:448-452`).
   This catches a writer that has stopped -- thread wedged, socket dead,
   plugin crashed -- which is exactly when the writer cannot clean up after
   itself.
2. **Writer layer, eviction.** The writer removes entries its source has
   stopped reporting, after a list-specific interval, by emptying the slot
   (§2.6). Eviction runs on a **monotonic deadline**, independent of input
   arriving: a writer that evicts only when a packet comes in never evicts
   once the link goes quiet.

Neither substitutes for the other. A pilot-edited, persisted list (route) uses
`tol: 0` and no eviction: age is meaningless for a plan the pilot entered.

### 2.8 Quality and fail-flag semantics

The existing per-key flags keep their meaning (`database.py` `db_item`:
`old`, `bad`, `fail`, `secfail`, plus `annunciate`). In a list:

| Flag | On a field key | On the slot's identity key | On a block-level key |
|---|---|---|---|
| `old` | that field has not been refreshed within `tol` | the slot is stale; **do not display the entry** | the writer has gone quiet |
| `bad` | the source says this field is unavailable (a protocol special value, §4.5); dash that field only | never set (an entry with no identity is not allocated) | the block-level value is not trustworthy |
| `fail` | not used per field | set on every occupied slot when the source fails (§4.7) | the source has failed |

The slot identity key governs the slot: if it is `old` or `fail`, the entry is
not drawn, whatever its fields say. A field's own `bad` dashes that field and
nothing else. Writers pass the flags as the tuple `(value, annunc, bad, fail)`
the value setter already accepts.

### 2.9 One key, one writer

Every list block has exactly **one** writer module. Documented exceptions are
named in the block's YAML header (the route editor's boot-time republish,
`flightplan.yaml`). Two sources for the same list do not both write it; see
§4.10.

### 2.10 Clamping hazard

The database silently clamps a numeric write to the key's `min`/`max`
(`database.py` value setter, "bounds check and cap"). A list field's range must
cover its source's full encodable range, or an out-of-range input becomes a
plausible wrong value with no flag. Traffic altitude is the live case: GDL90
encodes up to 101,350 ft (G§3.5.1.4); a 60,000 ft `max` copied from `ALT` would
pin a high target at 60,000 ft and call it good.

---

## 3. Worked example 1: route legs (existing, unchanged)

The route block is defined in fix-gateway `config/database/flightplan.yaml`
and documented key by key in `doc/flightplan_keys.md`; pyEfis writes it in
`src/pyefis/flightplan/fixbridge.py`. Mapped onto the model, with no key
changes:

| Model element | Route |
|---|---|
| Prefix / index | `FPL` / `f` (`f: 100`, `variables.yaml`, matched to the GNX's 100-waypoint limit) |
| Slot fields | `FPLfID LAT LON TYPE PT CRS DST ALT SPD SGI FLAGS CTRLAT CTRLON TURN` |
| Second table on the same index | segment table `FPLSf{KIND,ID,ENT,EXT,FIRST,LAST}`, `FPLSEGCNT` |
| Assignment | positional, pilot-ordered; slots past `FPLCOUNT` empty |
| Commit | **block**: every slot, the segment table, `FPLCOUNT`, `FPLNAME`, `FPLDBCYC`, then `FPLSEQ + 1` last (`fixbridge.py:246-299`); the engine and the display act on `FPLSEQ` change (`fixbridge.py:348-353`) |
| Writer | the editor (pyEfis); the engine republishes on restore -- the one documented exception |
| Aging | none: `tol: 0`, persisted. The engine's *outputs* (`FPLACTLEG`, `FPLCRS`, ...) are scalars with `tol: 5000` |
| Overflow | the engine rejects the whole commit with a reason on `FPLMSG` |
| Quality | an invalid route is never partially displayed: it is rejected as a unit |

The only thing this spec adds for the route is the reading rule, now general:
**act on the commit key, never on a field write.**

---

## 4. Worked example 2: ADS-B traffic (new)

### 4.1 Source and wire

The traffic writer decodes **GDL90** Traffic Reports. GDL90 is defined on
RS-422 at 38,400 baud (G§2.1); the Stratux delivers the same framing as UDP
datagrams on port 4000, which is where the existing `stratux` plugin already
listens (`plugins/stratux/__init__.py:18-19`). Today that plugin decodes the
Stratux AHRS extension (`0x4C`, not part of GDL90) and the Ownship Report
(`0x0A`) only (`stratux/__init__.py:30-55`); traffic is absent end to end
(pyEfis #53). The framing and decode below are independent of transport.

### 4.2 GDL90 framing (G§2.2)

- A message is `0x7E | ID | data | FCS(2) | 0x7E` (G§2.2.1). Back-to-back
  messages carry two flag bytes in a row (`... 0x7E 0x7E ...`), so **one
  datagram can hold several messages**, and the decoder must split on flags,
  not assume one message per datagram.
- Byte stuffing (G§2.2.1): inside a frame, `0x7D` and `0x7E` are sent as `0x7D`
  followed by the byte XOR `0x20`. On receipt only `0x7D` is an escape; a bare
  `0x7E` is a frame boundary.
- Message ID is the low 7 bits; a byte with the MSB set is discarded (G§2.2.2).
- FCS is CRC-CCITT, polynomial `0x1021`, initial value 0, table-driven as in
  G§2.2.3, computed over ID + data **before** stuffing, appended **LSB first**.
  A frame whose FCS does not match is discarded (G§2.2.1, reception step 4).
- Test vector (G§2.2.4): `7E 00 81 41 DB D0 08 02 B3 8B 7E` is a valid
  Heartbeat; its FCS is `0x8BB3`.

### 4.3 Messages the traffic writer uses

| ID | Message | Section | Use |
|---|---|---|---|
| 0 (`0x00`) | Heartbeat, 7 bytes, once per UTC second | G§3.1, Table 3 | source liveness (§4.7); its time stamp is the time of applicability of the traffic reports that follow it (G§3.5) |
| 10 (`0x0A`) | Ownship Report, 28 bytes, same layout as 0x14 | G§3.4, Table 6 | ownship identity for filtering (§4.8). Never written into the traffic block |
| 20 (`0x14`) | Traffic Report, 28 bytes | G§3.5, Table 7 | one target |

Ownship Geometric Altitude (`0x0B`, G§3.8) is height above the WGS-84
ellipsoid and is **not** a reference for traffic altitude (§4.9).

Per G§3.5 the source sends a Traffic Report **every second for each tracked
target**, for at least 32 targets, and when no ADS-B message has been received
for a tracked target it sends an **extrapolated** report until its own track
is discontinued.

### 4.4 Traffic Report (0x14) field grammar (G§3.5.1, Figure 2, Table 8)

Data bytes 2-28 (byte 1 is the ID), each letter a 4-bit nibble, most
significant first unless stated:

```
st aa aa aa ll ll ll nn nn nn dd dm ia hh hv vv tt ee cc cc cc cc cc cc cc cc px
```

| Field | Bits | Encoding | Special values | Section |
|---|---|---|---|---|
| `s` traffic alert status | 4 | 0 no alert, 1 traffic alert, 2-15 reserved | -- | G§3.5.1.1 |
| `t` address type | 4 | 0 ADS-B ICAO, 1 ADS-B self-assigned, 2 TIS-B ICAO, 3 TIS-B track file ID, 4 surface vehicle, 5 ground station beacon, 6-15 reserved | -- | G§3.5.1.2 |
| `aaaaaa` participant address | 24 | unsigned | -- | G§3.5.1.2 |
| `llllll` latitude | 24 | signed binary fraction, LSB = 180/2^23 deg, north positive | lat = lon = NIC = 0: no valid position | G§3.5.1.3 |
| `nnnnnn` longitude | 24 | as latitude, east positive | as latitude | G§3.5.1.3 |
| `ddd` altitude | 12 | pressure altitude ref 29.92 inHg: `ddd * 25 - 1000` ft, range -1,000 to +101,350 | `0xFFF` invalid or unavailable | G§3.5.1.4 |
| `m` misc | 4 | bits 1-0: `tt` type (00 not valid, 01 true track, 10 magnetic heading, 11 true heading); bit 2: 0 updated / 1 extrapolated; bit 3: 0 on ground / 1 airborne | -- | G§3.5.1.5, Table 9 |
| `i` NIC | 4 | 0-11 per Table 10 (HPL bins), 12-15 unused | 0 unknown | G§3.5.1.6 |
| `a` NACp | 4 | 0-11 per Table 10 (HFOM bins), 12-15 unused | 0 unknown | G§3.5.1.6 |
| `hhh` horizontal velocity | 12 | unsigned, 1 kt | `0xFFF` unavailable; `0xFFE` = 4,094 kt or more | G§3.5.1.7 |
| `vvv` vertical velocity | 12 | signed, 64 fpm, +-32,576 | `0x800` unavailable; `0x1FE` / `0xE02` = beyond +-32,576; `0x1FF-0x7FF`, `0x801-0xE01` unused | G§3.5.1.8 |
| `tt` track/heading | 8 | 360/256 deg, 0 = north | not valid when `m` bits 1-0 = 00 | G§3.5.1.9 |
| `ee` emitter category | 8 | 0-39 per Table 11 | 0 no type information | G§3.5.1.10 |
| `cc` x 8 call sign | 64 | ASCII `0-9`, `A-Z`, space (trailing pad / unavailable); SW Mod C and earlier use `-` for an unavailable character | -- | G§3.5.1.11 |
| `p` emergency/priority | 4 | 0 none, 1 general, 2 medical, 3 min fuel, 4 no comm, 5 unlawful interference, 6 downed aircraft, 7-15 reserved | -- | G§3.5.1.12 |
| `x` spare | 4 | reserved | -- | G§3.5.1 |

Target identity is the 28-bit combination of `t` and `aaaaaa` (G§3.5.1.2),
and GDL90 itself warns it is **not guaranteed unique** (same section).

### 4.5 The traffic key block

Index letter `k`, **`k: 32`** -- the minimum target count GDL90 guarantees to
output (G§3.5). All slot keys have `tol: 3000` (three missed 1 Hz reports).
"bad when" is how the GDL90 special value is carried (§2.8).

| Key | Type | Units / range | From | `bad` when |
|---|---|---|---|---|
| `TFCkTGT` | int | -1 .. 268435455 | identity `(t << 24) | aaaaaa`; **-1 = empty slot**; the slot's commit key, written last | never |
| `TFCkADDR` | int | 0 .. 16777215 | `aaaaaa` | -- |
| `TFCkATYP` | int | 0 .. 15 | `t` | -- |
| `TFCkLAT` | float | deg, -90 .. 90 | `llllll` | lat = lon = NIC = 0 |
| `TFCkLON` | float | deg, -180 .. 180 | `nnnnnn` | lat = lon = NIC = 0 |
| `TFCkALT` | float | ft pressure altitude, **-1000 .. 101350** | `ddd` | `0xFFF` |
| `TFCkGS` | float | kt, 0 .. 4094 | `hhh` | `0xFFF` |
| `TFCkVS` | float | fpm, -32640 .. 32640 | `vvv` x 64 | `0x800` |
| `TFCkTRK` | float | deg, 0 .. 359.9 | `tt` x 360/256 | `m` bits 1-0 = 00 |
| `TFCkTTYP` | int | 0 .. 3 | `m` bits 1-0 (what `TRK` is) | -- |
| `TFCkEXTR` | bool | | `m` bit 2 (1 = extrapolated) | -- |
| `TFCkAIR` | bool | | `m` bit 3 (1 = airborne) | -- |
| `TFCkNIC` | int | 0 .. 15 | `i` | -- |
| `TFCkNACP` | int | 0 .. 15 | `a` | -- |
| `TFCkCAT` | int | 0 .. 39 | `ee` | -- |
| `TFCkCS` | str | <= 8 chars | `cc` x 8, trailing spaces trimmed | -- |
| `TFCkALRT` | int | 0 .. 15 | `s` | -- |
| `TFCkEMRG` | int | 0 .. 15 | `p` | -- |

Block-level keys (one writer, the traffic writer):

| Key | Type | `tol` | Meaning |
|---|---|---|---|
| `TFCCOUNT` | int, 0 .. 32 | 3000 | occupied slots after the latest update. Informational -- a reader still checks each slot's `TGT`. `fail` = source failure (§4.7) |
| `TFCDROP` | int, 0 .. 1000 | 3000 | targets reported in the last second that got no slot because the block was full (§4.6). 0 normally |

No other fields. Nothing here is invented beyond the two block-level counters
and the empty-slot value; every slot field is a GDL90 field or a sub-field of
one.

### 4.6 Slot allocation, update and eviction

The writer keeps an in-memory map identity -> slot, and per slot the
monotonic time of its last report.

- **Refresh** (identity already has a slot): write every field of that slot
  (with its flags), then `TFCkTGT` (same value) **last**. `TGT`'s write is
  the commit; it is rewritten on every report so its age is the slot's age.
- **New target**: take the lowest-numbered empty slot (`TGT == -1`); write the
  fields, then `TGT` last.
- **Block full**: if ownship position (`LAT`/`LONG`) is valid and the new
  target is nearer than the farthest occupied slot, evict that slot (below)
  and fill it; otherwise drop the report and count it in `TFCDROP`. This
  mirrors GDL90's own prioritisation of proximate traffic (G§2.3). With no
  valid ownship position, drop the newcomer (first come, first kept).
- **Evict**: write `TGT = -1` **first**; the field keys are left as they are and
  mean nothing while `TGT` is -1. Re-filling follows §2.6.
- **Eviction interval**: a target with no report for `evict_s` seconds
  (plugin config, **default 10**) is evicted. Because the source extrapolates
  through gaps (G§3.5), a target that stops being reported has normally been
  discontinued by the source itself; `evict_s` only needs to outlast a short
  link dropout. It must exceed the 3 s `tol`, so a stale target is shown as
  stale (`old`) before it disappears.
- Eviction and the `TFCCOUNT`/`TFCDROP` write run once per second on a
  monotonic timer with a socket receive timeout, **not** per packet (§2.7).

### 4.7 Source liveness

A source with no valid Heartbeat for 3 s is failed: the writer sets `fail` on
`TFCCOUNT` and on every occupied slot's `TGT`, then evicts normally at
`evict_s`. A Heartbeat clears it. A dead writer is caught by `tol` instead
(§2.7). The Heartbeat's status bits -- GPS position valid, maintenance
required, CSA requested / not available (G§3.1.1, G§3.1.2) -- are **not** carried
on the bus by this spec (§6, D8).

### 4.8 Ownship filtering

The receiver hears our own ADS-B Out (and possibly a TIS-B rebroadcast of it).
The writer:

1. Learns ownship identity from each Ownship Report (`0x0A`): `t` and
   `aaaaaa` in the same layout as G§3.5.1 (G§3.4). A plugin setting
   `ownship_address` (hex) supplies it when the receiver does not.
2. Drops any Traffic Report whose 24-bit address equals ownship's and whose
   type is 0 or 2 (ICAO address, ADS-B or TIS-B). Type 1 (self-assigned) is
   dropped only when ownship's own type is also 1.
3. Does **not** filter type 3 (TIS-B track file ID). A track-file shadow of
   ownship -- the case G§3.5.1.2 explicitly warns about -- carries no ownship
   address and cannot be recognised from GDL90 fields alone. A geometric
   filter (near and co-altitude) would hide a real close target, which is
   the target that matters most, so it is left to a decision by Bill (§9, F6).

### 4.9 Altitude reference

`TFCkALT` is **pressure altitude referenced to 29.92 inHg** (G§3.5.1.4). GDL90
asks that a display support both absolute and ownship-relative altitude
(same section). Relative altitude is therefore `TFCkALT - PALT`, where `PALT`
is ownship pressure altitude (`ahrs.yaml:87`) -- never `ALT` (indicated,
corrected to the local setting: wrong by about 1,000 ft per inHg of
difference from 29.92) and never geometric altitude (`0x0B`, ellipsoid
height, G§3.8). If `PALT` is `old`/`bad`/`fail` or absent, relative altitude
is unavailable and is dashed, not computed from another reference.

Found while writing this: **nothing in this stack writes `PALT` today** (the
only writer is the `dynon` plugin). A `PALT` source is a prerequisite for the
display item (§9, F3). The gateway does not publish a relative altitude key:
it would be a computed value with a second reference, and the display has
both inputs.

### 4.10 A second ADS-B source (GNX-375)

The roadmap names the GNX-375 as a second ADS-B source. The `garmin_gnx375`
plugin reads NMEA 0183 navigation sentences only
(`plugins/garmin_gnx375/__init__.py:21`), and the roadmap §10 sends traffic
to the Stratux because Connext is handshake-gated. This spec does not
characterise a GNX traffic output. When one is wired, its plugin writes the
**same** `TFC` block under §2.9: exactly one traffic writer is enabled per
installation, as `ifly`/`navigator_adapter`/`mavlink` are kept disabled
beside the flight-plan engine. Merging two receivers into one block is the
source-selection problem of roadmap §9 item 3 and is a follow-on (§9, F5).

---

## 5. What the display may assume

May assume:

- An entry exists in slot `k` exactly when `TFCkTGT != -1` and `TFCkTGT` is
  not `old` or `fail`. React to `TFCkTGT` writes; when one arrives, the slot's
  other fields are already that target's (§2.5, §2.6).
- Slot numbers carry no meaning and an entry may move slot after eviction and
  re-acquisition; key any display state (trails, selection) by `TFCkTGT`, not
  by `k`.
- Positions are WGS-84 degrees; `TFCkALT` is pressure altitude; `TFCkVS` is
  fpm, positive up; `TFCkGS` is ground speed in kt along `TFCkTRK`.
- A field marked `bad` is unavailable at the source. Dash it; do not draw a
  zero.
- `TFCkTRK` is what `TFCkTTYP` says: normally true track (G§3.5.1.9); magnetic
  heading and true heading are possible. A magnetic-up map converts with
  `MAGVAR` as it does for ownship. `TTYP = 0` means `TRK` is `bad`: GDL90
  recommends a non-directional symbol (G§3.5.1.9).
- `TFCkALRT = 1` is the source's traffic alert. GDL90's display
  recommendations -- flashing yellow symbol; an audible annunciation when the
  count of alerted targets rises (G§3.5.1.1); a degraded-target symbol when NIC
  or NACp is 4 or lower (G§3.5.1.6); symbol choice from address type, emitter
  category, NIC, air/ground and alert (G§3.5.1.2, G§3.5.1.10) -- are the
  display item's to implement, from these keys.

Must not assume:

- That `TFCkTGT` is unique to one physical aircraft (G§3.5.1.2; §6, D3), or
  that `TFCkCS` identifies a target at all (G§3.5.1.11).
- That the block holds every target in range. At capacity the farthest are
  missing and `TFCDROP > 0`; a display that wants to say so reads it.
- That the gateway has applied any threat logic beyond the source's own
  alert bit.
- That a position is current to the instant: see §6, D1.

---

## 6. Where the FIX model departs from GDL90 semantics

Every deviation, flagged as the item requires:

- **D1 Time of applicability is dropped.** GDL90 traffic applies at the start
  of the second stamped by the preceding Heartbeat (G§3.5); there is no
  per-report time. The FIX key carries only its write time. The display
  treats a fresh slot as current; the error is up to about one second plus
  transport latency, about 0.17 nm at a 600 kt closure. Not corrected here;
  carrying the stamp would add a key nothing consumes yet.
- **D2 Special values become flags.** `0xFFF`/`0x800`/`tt not valid`/no-position
  are carried as `bad` on the field rather than as sentinel values. The
  meaning is kept; the encoding changes. The **saturation** codes lose their
  "or more" qualifier: `hhh = 0xFFE` publishes 4,094 kt, `vvv = 0x1FE/0xE02`
  publishes +-32,640 fpm, with no flag. Neither is reachable by GA traffic.
- **D3 Identity collisions collapse.** The allocator keys on the 28-bit
  identity, which GDL90 says may not be unique (G§3.5.1.2). Two targets sharing
  one identity occupy one slot and the slot alternates between their
  positions. Nothing on the bus can reveal it. The test plan pins the
  behaviour (T7) so any change to it is visible.
- **D4 Capacity is GDL90's floor.** `k: 32` equals the minimum the source
  guarantees (G§3.5); a Stratux can report more. Overflow is counted
  (`TFCDROP`), and the nearest-kept rule follows G§2.3, but the farthest
  targets are not on the bus. Raising `k` is one number.
- **D5 Ownship TIS-B track-file shadows are not filtered** (§4.8, item 3).
  G§3.5.1.2 asks the display vendor to "cope" with this; this spec leaves it to
  the display and to a decision on a geometric filter.
- **D6 Call sign is trimmed.** Trailing pad spaces are removed; a pre-Mod-D
  `-` for an unavailable character is passed through unchanged.
- **D7 The gateway does not extrapolate.** The source's own extrapolation is
  passed through as `TFCkEXTR`; between reports the FIX value simply holds.
- **D8 Receiver status is not carried.** Heartbeat status (GPS position valid,
  maintenance required, CSA requested / not available, G§3.1) and the
  recommendation to annunciate them reach the bus only as the source-failure
  `fail` flag (§4.7). Carrying them is a follow-on if the display wants them.

And one inherited from the bus, not GDL90: numeric clamping (§2.10). The YAML
ranges in §4.5 are set to the full GDL90 range so it never applies.

---

## 7. Test plan -- synthetic GDL90, no hardware

All vectors are built from the GDL90 document itself, so a failure points at
the decoder, not at a capture. Injection is a UDP datagram to the writer's
port on `127.0.0.1`; the database is the real `fixgw.database` loaded with the
traffic YAML; time is a fake monotonic clock where a test needs one.
(The existing `plugins/stratux/fake_server/` is an HTTP mock of the Stratux
web API, not a GDL90 source, and is not reused.)

**T1 Framing and FCS.**
- G§2.2.4 Heartbeat `7E 00 81 41 DB D0 08 02 B3 8B 7E` accepted; FCS `0x8BB3`.
- G§3.5.2 worked traffic example, framed: `7E 14 00 AB 45 49 1F EF 15 A8 89 78
  0F 09 A9 07 B0 01 20 01 4E 38 32 35 56 20 20 20 00 57 D6 7E` (FCS `0xD657`,
  sent `57 D6`; computed with the G§2.2.3 algorithm, verified against the
  Heartbeat vector). Decodes to: no alert, type 0, address `0xAB4549`
  (octal 52642511 -- the document prints "526425118", a typo), latitude
  44.90707, longitude -122.99486 (the document's 44.90708 / -122.99488 are
  within one LSB, 2.1e-5 deg), 5,000 ft, airborne, updated, true track,
  NIC 10, NACp 9, 123 kt, +64 fpm, 45.0 deg, emitter 1 (light), call sign
  `N825V`, no emergency.
- G§2.2.1 stuffing: a payload byte `0x7E` sent `7D 5E`, `0x7D` sent `7D 5D`,
  and an FCS containing `7D 7E` sent `7D 5D 7D 5E`, all round-trip.
- Two and three back-to-back messages in one datagram are all decoded.
- One flipped bit: frame discarded, nothing written. ID byte with MSB set:
  discarded (G§2.2.2).

**T2 Field boundaries.** Each special value and example in G§3.5.1.3
(latitude/longitude table), G§3.5.1.4 (`0x000`, `0x028`, `0x050`, `0xFFE`,
`0xFFF`), G§3.5.1.7 (`0xFFE`, `0xFFF`), G§3.5.1.8 (`0x001`, `0xFFF`, `0x1FD`,
`0x1FE`, `0xE03`, `0xE02`, `0x800`), G§3.5.1.9 (`tt` 0 and 128; `m` = 00 ->
`TRK` bad), Table 9 all `m` combinations, call sign all spaces and
`N825V` + pad. Assert value and `bad` flag per §4.5.

**T3 Slot lifecycle.** New target -> lowest empty slot; refresh stays in the
same slot; a callback recorder on the database asserts every update writes
`TGT` **after** all fields, and every eviction writes `TGT = -1` before any
other key of that slot. Advance the clock: eviction at `evict_s`, with **no
datagrams arriving** (proves the timer, §2.7). Evict-then-reuse passes
through -1.

**T4 Staleness.** Stop injecting: all slot keys of a live target report
`old` after 3,000 ms, before eviction at 10 s.

**T5 Capacity.** Ownship at a fixed `LAT`/`LONG`; inject 40 targets at
distinct ranges: the nearest 32 hold slots, `TFCDROP = 8`. A nearer 41st
evicts the farthest. With ownship position `bad`, newcomers are dropped.

**T6 Ownship filter.** `0x0A` with type 0 address A, then `0x14` with address
A types 0 and 2: no slot. Type 3 with A: slotted. `ownship_address` config
with no `0x0A`: same result. Ownship never appears in the block.

**T7 Identity collision.** Two alternating reports, same identity, positions
1 nm apart: one slot whose position alternates. Pins D3.

**T8 End to end through netfix.** A real gateway with the writer enabled and
a netfix client subscribed to one slot: inject a new target, then a
different target into the same slot after eviction. The client's received
line order is fields -> `TGT` for each fill and `TGT = -1` first for the
eviction. This is the ordering guarantee §2.5 rests on.

**T9 Source failure.** Stop Heartbeats, keep Traffic Reports: after 3 s
`TFCCOUNT` and every occupied `TGT` carry `fail`; a Heartbeat clears it.

**T10 Clamp.** A target at `ddd = 0xFFE` publishes 101,350 ft unclamped.

**T11 Route regression.** None needed: the route block does not change. The
existing route conformance tests (pyEfis #339) remain the guard.

---

## 8. References

- GDL 90 Data Interface Specification, 560-1058-00 Rev A, 2007-06-05,
  Garmin AT. Public copy:
  <https://www.faa.gov/sites/faa.gov/files/air_traffic/technology/adsb/archival/GDL90_Public_ICD_RevA.PDF>
  (fetched 2026-10-31, 54 pages).
- `MAOS-DESIGN/docs/AVIONICS_STACK_ROADMAP.md` §2, §9 item 2, §10.
- `makerplane/briefs/flight_plan_plan.md` §3.2 (maos-workspace) -- the route
  half of this decision and the rejection of the JSON key and side channel.
- fix-gateway `config/database/flightplan.yaml`, `config/database/variables.yaml`,
  `doc/flightplan_keys.md`, `src/fixgw/database.py`,
  `src/fixgw/plugins/netfix/__init__.py`, `src/fixgw/plugins/stratux/`.
- pyEfis #52 (this decision), #53 (traffic layer), #48 (MFD epic).

## 9. Follow-on items (not part of this spec)

- **F1** fix-gateway: traffic writer -- GDL90 `0x00`/`0x0A`/`0x14` decode, the
  `TFC` YAML with `k: 32`, allocation/eviction/liveness/ownship filter per §4,
  tests T1-T10.
- **F2** pyEfis #53: traffic layer consuming §5.
- **F3** A `PALT` writer for this stack (compute from `ALT` + `BARO`, or the
  receiver's own pressure altitude from `0x0A`), prerequisite for relative
  altitude in F2.
- **F4** Existing `stratux` plugin defects seen while reading it (out of this
  spec's scope): it writes Ownship Report **ground speed to `IAS`**
  (`stratux/__init__.py:48-52`); its decoder treats a bare `0x7E` inside a
  frame as an escape and assumes one message per datagram
  (`stratux/gdl90.py:22-48`); and `recvfrom` has no timeout, so nothing
  periodic can run in that loop. F1 should fix the decoder; the `IAS` write
  is a defect on its own.
- **F5** Two ADS-B receivers into one block (roadmap §9 item 3).
- **F6** Decision for Bill: filter suspected TIS-B ownship shadows by geometry,
  or leave them to the display (§4.8, D5).
- **F7** After F1 merges, add a ratified "Traffic" block to roadmap §9.1 and
  close the §10 "Dynamic lists over FIX" row.
