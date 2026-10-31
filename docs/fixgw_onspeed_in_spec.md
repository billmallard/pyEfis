# FIX-Gateway plugin spec: `onspeed` (OnSpeed serial-in, AOA)

Status: **spec, ready to implement** (authored 2026-10-31, AER-4329 / BACKLOG G3).
Target repo: `billmallard/fix-gateway` (branch from `dev`,
`src/fixgw/plugins/onspeed/`). Implementation is a separate follow-on item.
Closes the data half of: [billmallard/fix-gateway#13](https://github.com/billmallard/fix-gateway/issues/13)
(EFIS-AOA-001), which data-blocks pyEfis **AI-LIM-001** (pitch-limit
indication, [ai_widget_spec.md](ai_widget_spec.md) §4,
`tests/instruments/ai/test_ai.py::test_ai_cat_pitch_limit_indication`).
Sibling input bridges: [fixgw_canaerospace_in_spec.md](fixgw_canaerospace_in_spec.md),
[fixgw_dronecan_in_spec.md](fixgw_dronecan_in_spec.md).

## 1. Goal

A listen-only FIX-Gateway input plugin that reads the **OnSpeed Gen2 AOA
computer's 10 Hz `ONSPEED` serial sentence** and publishes calibrated angle
of attack to the existing `AOA` key, plus the flap-dependent stall-warning
AOA to `AOA.Warn`. That pair is what a pitch-limit indicator needs: the
margin to stall warning is `AOA.Warn - AOA` degrees, and because AOA and
pitch move together at constant flight path, the AI can draw the limit
marker at `PITCH + (AOA.Warn - AOA)` on the ladder. How pyEfis draws it is
pyEfis's business (AI-LIM-001); this plugin only has to make the two numbers
honest.

Posture: OnSpeed is a federated source, like CANaerospace. Consume its
sentence; don't adopt its vocabulary.

## 2. Source of truth for the sentence

**Authority:** `Software/OnSpeedTeensy_AHRS/DisplaySerial.ino`,
`writeSerialData()`, in `billmallard/OnSpeed-Gen2` at **`be1481c`** (master,
2026-10-31). The field comments there are the repo's own sentence document;
the `sprintf` format string on the line that builds the `ONSPEED` sentence is
the tie-breaker where the two disagree (they do once, §3.3). The PDF user
manual in `Documents/` does not define the sentence.

Nothing below is invented. Every field, width, scale and sign is read off that
`sprintf`; where the firmware leaves a field hardcoded to zero, this spec says
so and the plugin does not publish it.

Not covered: OnSpeed Gen3 / later firmware from flyonspeed.org. If a newer box
emits a different sentence, that is a new spec revision, pinned to its own
source SHA.

## 3. Sentence grammar

### 3.1 Transport

| Property | Value | Source |
|---|---|---|
| Rate | 10 Hz (every >100 ms) | `millis()-serialoutLastUpdate>100` |
| Baud | 115200 | `Serial1/3/5.begin(115200)` in `OnSpeedTeensy_AHRS.ino` |
| Framing | 8N1 (Arduino default; no explicit config in source) | — |
| Port on the box | `Serial3` = RS-232 levels (shipped default), `Serial1`/`Serial5` = TTL | `default_config.h` `<SERIALOUTPORT>Serial3`, comment at `OnSpeedTeensy_AHRS.ino:976` |
| Format select | `<SERIALOUTFORMAT>ONSPEED</SERIALOUTFORMAT>` (shipped default) | `default_config.h:47` |
| Terminator | `\r\n` (Teensy `println()`) | `DisplaySerial.ino` |

The box can instead emit a Garmin-G3X-style attitude sentence (`=11...`,
`<SERIALOUTFORMAT>G3X`). v1 does not decode it (§6.2).

### 3.2 Layout

ASCII, fixed width, 76 body bytes + 2 checksum bytes + CR LF = 80 bytes on the
wire in the normal case. All numbers are decimal integers, zero-padded; signed
fields always carry an explicit `+` or `-`.

| Offset | Width | Field | C format | Scale / units | Sign |
|---|---|---|---|---|---|
| 0 | 1 | Escape | `#` | — | — |
| 1 | 1 | Sentence ID | `1` | — | — |
| 2 | 4 | Pitch | `%+04i` | 0.1 deg | + = nose up |
| 6 | 5 | Roll | `%+05i` | 0.1 deg | + = right |
| 11 | 4 | IAS | `%04u` | 0.1 kt | unsigned |
| 15 | 6 | Pressure altitude | `%+06i` | 1 ft | |
| 21 | 5 | Rate of turn (body yaw rate, `gYaw`) | `%+05i` | 0.1 deg/s | + = right |
| 26 | 3 | Lateral G | `%+03i` | 0.01 g | + = leftward (sent as `-LateralGSmoothed`) |
| 29 | 3 | Vertical G | `%+03i` | 0.1 g, `ceil()`ed | + = up |
| 32 | 2 | Percent lift | `%02u` | 0-99 % | unsigned, `constrain(0,99)` |
| 34 | 4 | **AOA** | `%+04i` | 0.1 deg | |
| 38 | 4 | Instantaneous VSI | `%+04i` | 10 fpm, `floor()`ed | + = up |
| 42 | 3 | OAT | `%+03i` | 1 degC | **always `+00`** (`OATc=0`) |
| 45 | 4 | Flight path angle | `%+04i` | 0.1 deg | |
| 49 | 3 | Flap position | `%+03i` | 1 deg | |
| 52 | 4 | **Stall-warning AOA** (current flap setting) | `%+04i` | 0.1 deg | |
| 56 | 4 | OnSpeed slow AOA | `%+04i` | 0.1 deg | |
| 60 | 4 | OnSpeed fast AOA | `%+04i` | 0.1 deg | |
| 64 | 4 | Tones-on AOA (`LDmaxAOA`) | `%+04i` | 0.1 deg | |
| 68 | 4 | G onset rate | `%+04i` | 0.01 g/s | **always `+000`** (`gOnsetRate=0`) |
| 72 | 2 | Spin recovery cue | `%+02i` | -1/0/+1 | **always `+0`** (`spinRecoveryCue=0`) |
| 74 | 2+ | DataMark | `%02u` | counter | unsigned, see §3.4 |
| 76 | 2 | Checksum | `%02X` | — | — |
| 78 | 2 | CR LF | | | |

Checksum: the low 8 bits (`byte serialCRC`) of the arithmetic sum of body
bytes **0 through 75 inclusive**, printed as two uppercase hex digits. The
range is a fixed loop bound in the firmware (`for (int i=0;i<=75;i++)`), not
"everything before the checksum" — that distinction matters in §3.4.

### 3.3 Where the firmware comments and the code disagree

The second comment block lists Rate of Turn as `%+04i`; the `sprintf` uses
`%+05i`, and the first comment block says 5 bytes. The plugin follows the
`sprintf`: width 5. The offsets above are computed from the `sprintf` and sum
to 76, which matches the checksum loop bound. That agreement is the
cross-check.

### 3.4 Width overflow: the one way the layout moves

C `printf` widths are minimums. A value that needs more digits than its width
silently widens that field and shifts every field after it. Cases reachable
from this firmware:

| Field | Overflows when | Realistic? |
|---|---|---|
| Lateral G (`%+03i`, 0.01 g) | \|lateral\| >= 1.00 g | Yes, briefly (aerobatics, rough air, a hard skid) |
| DataMark (`%02u`) | >= 100 presses since power-on | Yes, over a long session; `dataMark++` per button press, never reset |
| AOA / setpoints (`%+04i`, 0.1 deg) | \|AOA\| >= 100.0 deg | Only on garbage |
| IAS (`%04u`) | IAS >= 1000.0 kt, or a negative IAS cast to unsigned | Only on garbage |
| iVSI (`%+04i`, 10 fpm) | \|VS\| >= 10,000 fpm (no clamp in code, despite the `[-999;999]` comment) | Rare |
| Pitch (`%+04i`) | \|pitch\| >= 100.0 deg | Only on garbage |

Decoding rule:

1. Strip CR LF. Take the **last two characters** as the checksum, and
   everything before them as the body. Do not locate the checksum by offset.
2. Verify the checksum over `body[0:76]` exactly as the firmware computes it
   (the first 76 bytes, whatever the body length).
3. If `len(body) == 76`: decode by the fixed offsets.
4. If `len(body) > 76` **and** `body[0:74]` still matches the fixed-width
   grammar (§3.5) **and** `body[74:]` has no leading zero (a `%02u` value of
   100 or more never does): the overflow is confined to DataMark, the last field.
   Decode normally and take DataMark as `body[74:]`. This keeps the plugin
   working after the 100th DataMark press; without this rule every sentence
   for the rest of the flight would be rejected.
5. Anything else is **malformed**: count it, publish nothing from it.
   An overflow in any field before DataMark makes the offsets of every later
   field — including AOA — ambiguous, because unsigned fields (IAS, percent
   lift) have no sign character to resynchronise on. Never guess.

Consequence worth stating plainly: **a lateral-G excursion past 1 g drops
those frames**. At 10 Hz with the 50-sample lateral smoothing in the box, an
excursion lasts long enough to age `AOA` out (§6.4). That is the correct
failure — stale, visibly — not a wrong AOA. It belongs in the plugin docs.

(With DataMark >= 1000 the firmware's `char serialOutString[78]` overflows;
that is a firmware bug, out of scope here. Beyond rule 4 the plugin makes no
promise about it.)

### 3.5 Grammar as a regex

For the fixed-width part (body bytes 0-73), with DataMark matched separately:

```
^#1[+-]\d{3}[+-]\d{4}\d{4}[+-]\d{5}[+-]\d{4}[+-]\d{2}[+-]\d{2}\d{2}
[+-]\d{3}[+-]\d{3}[+-]\d{2}[+-]\d{3}[+-]\d{2}[+-]\d{3}[+-]\d{3}
[+-]\d{3}[+-]\d{3}[+-]\d{3}[+-]\d$
```

(one line in code; broken here for width). DataMark: `^(\d{2}|[1-9]\d{2,})$`.

Why the leading-zero clause is load-bearing: without it, a spin-recovery cue
that overflowed to `+10` would leave `+1` in the grammar and push its `0` into
DataMark, and the line would parse with the wrong cue. The cue's domain is
-1/0/+1 (and it is hardcoded 0 in this firmware), so that overflow is
unreachable today; the clause makes the rule hold without leaning on that. A
randomized check of a one-digit overflow in every field before DataMark,
5,000 sentences per case, found no other acceptance; the §7.1 test makes it
permanent. The
implementation may use the regex for validation and slicing for extraction,
or a table of `(offset, width, signed)` tuples; either way, the table in §3.2
is normative.

## 4. Key mapping

### 4.1 Published (v1)

| Sentence field | FIX key | Conversion | Notes |
|---|---|---|---|
| AOA | `AOA` | raw / 10 -> deg | Quality per §5. Existing key: `database/ahrs.yaml`, `aux: [Min, Max, 0g, Warn, Stall]`, `tol: 300` |
| Stall-warning AOA | `AOA.Warn` | raw / 10 -> deg | Write only on change (§5.3). `"None"` when not calibrated |

**v1 adds no database keys.** `AOA` already exists in fix-gateway, and
CAN-FIX already defines it (parameter 386 / `0x182`, "Angle of Attack",
0.01 deg, meta `Min/Max/0g/Warn/Stall`; mapped in `canfix/map.yaml`). The
open question in fix-gateway#13 — "no AOA param exists in canfix-spec yet" —
is stale; this spec answers it with the existing key and existing aux.

Not written by v1: `AOA.Stall`, `AOA.0g`, `AOA.Min`, `AOA.Max`. OnSpeed does
not send a stall AOA, only the stall-warning setpoint. Deriving one (the
firmware internally extrapolates 100 % lift at `stallWarningAOA*100/90`)
would be inventing a field; don't.

### 4.2 Parsed but not published (v1)

These are decoded, range-checked, and shown in `get_status()` so a human can
compare them to the box's own display, but **not written to the database**:

| Field | Candidate key | Why not by default |
|---|---|---|
| Pitch, Roll | `PITCH`, `ROLL` | One key, one writer: an installation with OnSpeed already has a primary AHRS. Two writers on attitude fight. |
| IAS, Pressure alt | `IAS`, `PALT` | Same; and OnSpeed's IAS is its own pitot (or the EFIS's, with `SPHERICAL_PROBE`) |
| iVSI | `VS` | Same |
| Lateral G, Vertical G | `ALAT`, `ANORM` | Same; and OnSpeed's lateral sign ("+ = leftward") is unverified against fix-gateway's `ALAT` convention |
| Rate of turn | `ROT` | Body yaw rate, not earth-frame turn rate |
| Flight path angle | `VPATH` | `ahrs.yaml` documents `VPATH` as unpublished; a second source is a design question, not a plugin default |
| Flap position | — | No flap-position key in the fix-gateway database today |
| Percent lift, OnSpeed slow/fast, tones-on | — | No keys. See §9 |
| OAT, G onset rate, spin cue | — | **Hardcoded zero in this firmware.** Parse for grammar, never publish |

A later `extras:` option may opt individual rows in per installation. Not in v1.

## 5. Quality and validity

Two independent layers, and neither substitutes for the other:
**source-side validity** (the plugin decides a decoded value is not
trustworthy and says so in the flags) and **staleness** (the database marks
the key old when frames stop arriving).

### 5.1 The low-airspeed zero

Below its audio-mute airspeed, OnSpeed does not stop sending AOA. It sends
**AOA `+000` and percent lift `00`** (`displayAOA=0`, `percentLift=0` when
`displayIAS < muteAudioUnderIAS`). A zero AOA reads as "far from stall", so
publishing it as a good value is hazardously misleading in exactly the
low-speed regime where an AOA cue matters.

Rule: if the sentence's own IAS field is below the plugin's `min_ias`, write
`AOA` as `(0.0, False, True, False)` — value, annunciate, **bad**, fail.
Clear `bad` on the first frame at or above `min_ias`.

`min_ias` must be **at least** the box's `MUTE_AUDIO_UNDER_IAS`. The firmware's
compiled default is 30 kt (`OnSpeedTeensy_AHRS.ino:213`); the shipped
`default_config.h` sets 25 kt. Plugin default: **30 kt**, the higher of the
two. A plugin threshold above the box's errs safe (AOA flagged bad for a few
knots it did not have to be); one below it publishes the zero as good. The
connection config comment must say so.

### 5.2 What the plugin cannot detect

- **NaN AOA.** The serial path does not check `isnan(AOA)` (the WiFi path
  does). On the Teensy 3.6's Cortex-M4, a float-to-int conversion of NaN
  yields 0, so a NaN AOA arrives as `+000` — indistinguishable from the
  low-speed zero, and at speed indistinguishable from a real 0.0 deg. Record
  it in the plugin docs as a source limitation; the fix belongs in OnSpeed.
- **A real 0.0 deg AOA at speed** is legitimate and must be published as good.
  Do not add a "zero means bad" heuristic above `min_ias`.

### 5.3 `AOA.Warn`

Aux values carry no quality flags in the fix-gateway database, so validity is
expressed by presence:

- Stall-warning field `+000` -> write `"None"` to `AOA.Warn`. `0.00` is the
  firmware's initial value before a calibration loads, and a 0 deg
  stall-warning AOA is not physical.
- Setpoint order check: OnSpeed's own `percentLift` mapping assumes
  `tones-on < OnSpeed fast <= OnSpeed slow <= stall-warning`. If a nonzero
  sentence violates it, write `"None"`, count `setpoint_order_errors`, and log
  once at WARNING. A pitch-limit indicator drawn from a bad calibration is
  worse than none.
- Otherwise write the value — **only when it changes**. `set_aux_value`
  fires every callback on every write, so writing it at 10 Hz floods netfix
  clients with an unchanging number. The value changes in flight with flap
  position, so change-detection is required, not optional.

Implementer gotcha: clear an aux with the **string** `"None"`.
`set_aux_value(name, None)` raises `TypeError` from `float(None)`, which its
`except ValueError` does not catch (`database.py`, `set_aux_value`).

### 5.4 Staleness and failure

- **Old**: rely on the database `tol`. `AOA` has `tol: 300` ms, i.e. three
  missed 10 Hz frames. Don't add a parallel timer for `old`. (Whether 300 ms is
  the right `tol` for a 10 Hz source is a database question; note it, don't
  change it here.)
- **Fail**: set `fail` on `AOA` when the serial port cannot be opened, raises
  `SerialException`, or disappears (USB adapter unplugged). Clear it on the
  first good frame after the port recovers. Reopen with a backoff (1 s, capped
  at 10 s); never spin.
- **Bad on malformed input**: no. A dropped frame publishes nothing; the key
  ages to `old` on its own if the drops continue. Flagging `bad` on one
  corrupt frame among good ones would flicker the indicator.

## 6. Runtime behavior

### 6.1 Architecture

Follow the existing serial plugins (`dynon`, `mgl_serial`): a `Plugin`
(`PluginBase`) owning a `MainThread` that reads a `serial.Serial` with
`timeout=0.5`. Split the decode into a pure module so tests need no port:

```
onspeed/
  __init__.py   # Plugin + MainThread: port, line assembly, db writes, status
  sentence.py   # pure: parse(line: bytes) -> OnSpeedFrame | raises SentenceError
```

`sentence.py` imports nothing from `fixgw` (stdlib only). `OnSpeedFrame` is a
frozen dataclass of the §3.2 fields in engineering units, plus `datamark_overflow: bool`.
`SentenceError` carries a reason: `length`, `checksum`, `grammar`,
`wrong_format`, `encoding`.

Line assembly: accumulate bytes, split on `\n`, strip a trailing `\r`.
Discard any line longer than 128 bytes without parsing (a stuck line with no
terminator must not grow the buffer without bound), and discard the first
partial line after the port opens.

`stop()`: set `getout`, `join(1.0)` (must exceed the read timeout), raise
`plugin.PluginFail` if still alive — as `dynon` does.

### 6.2 Format detection

- A line starting `=11` is the box's G3X format. Count `wrong_format`, log
  once at WARNING: "OnSpeed is set to G3X output; set SERIALOUTFORMAT to
  ONSPEED". Publish nothing.
- A line starting `#` with any ID other than `1`: `grammar`.
- Any non-ASCII byte: `encoding`.

### 6.3 Per-frame pipeline

```
line -> sentence.parse()        -> SentenceError: counter[reason]++ ; return
     -> AOA quality (5.1)       -> db_write("AOA", (aoa, False, bad, False))
     -> AOA.Warn (5.3)          -> on change only: db_write("AOA.Warn", v | "None")
     -> status snapshot update
```

Never let an exception leave the thread loop; wrap the per-line body,
log the first occurrence per reason at WARNING and later ones at DEBUG.

### 6.4 Configuration

Ship `src/fixgw/config/connections/onspeed.yaml`:

```yaml
# OnSpeed Gen2 AOA computer, ONSPEED serial sentence (10 Hz, 115200 8N1).
# On the box: SERIALOUTFORMAT=ONSPEED. Serial3 is RS-232 levels; Serial1/5 are TTL.
onspeed:
  load: no
  module: fixgw.plugins.onspeed
  port: /dev/ttyUSB0
  baud: 115200
  # AOA is published bad below this indicated airspeed (kt). Must be >= the
  # box's MUTE_AUDIO_UNDER_IAS, or OnSpeed's low-speed zero is published as a
  # real AOA. Firmware default 30, shipped config 25.
  min_ias: 30
```

Unknown keys: warn, don't fail. `baud` other than 115200: warn (the firmware
cannot send anything else) but honor it.

### 6.5 Status

`get_status()` returns an `OrderedDict`:

```
Port, Port Open,
Lines Received, Frames Decoded,
Length Errors, Checksum Errors, Grammar Errors, Wrong Format, Encoding Errors,
DataMark Overflow Frames, Setpoint Order Errors, Low-IAS Frames,
Last Frame Age (s),
Last Frame (dict: every §3.2 field in engineering units)
```

`Last Frame` is how a human verifies the decode against the OnSpeed display
on the bench, including the §4.2 fields the plugin does not publish.

## 7. Test plan (synthetic frames, no hardware)

Vectors below were generated by reimplementing the firmware `sprintf` and
checksum loop in Python (`'#1%+04d%+05d%04d...' % fields`, sum of
`body[:76]` mod 256). Each is 78 characters before CR LF unless noted.

| ID | Sentence (without CR LF) | What it is |
|---|---|---|
| V1 | `#1+052-01230854+04500+0031+03+1162+098-005+00-006+00+135+112+094+060+000+0035C` | Nominal: pitch 5.2, roll -12.3, IAS 85.4, AOA 9.8, warn 13.5 |
| V2 | `#1-008+00000250+00812+0000+00+1000+000+000+00+000+20+135+112+094+060+000+0001E` | Taxi: IAS 25.0, AOA 0, percent lift 0, flaps 20 |
| V3 | `#1+052-01230854+04500+0031+03+1162+098-005+00-006+00+135+112+094+060+000+01005A` | DataMark = 100 (79 chars); checksum still over bytes 0-75 |
| V4 | `#1+052-01230854+04500+0031-120+1162+098-005+00-006+00+135+112+094+060+000+0035B` | Lateral -1.20 g overflow (79 chars) |
| V5 | `#1+052-01230854+04500+0031+03+1162+098-005+00-006+00+000+000+000+000+000+0033C` | Uncalibrated: all setpoints zero |

### 7.1 `tests/plugins/onspeed/test_sentence.py` (pure)

1. V1 decodes to the exact field values in the table, every field, signs included.
2. Golden-offset test: build a sentence with a distinct value in every field
   and assert each lands in its own slot — catches an off-by-one in the
   offset table that a single nominal vector can hide.
3. Checksum: flip one body byte of V1 -> `checksum`; lowercase hex checksum
   (`5c`) -> accept (be liberal in what you accept; the firmware prints upper).
4. V3 decodes with `datamark == 100`, `datamark_overflow is True`, and its
   checksum verifies over bytes 0-75 only.
5. V4 -> `SentenceError("grammar")`, and no partial frame is returned.
   Then the general case: for **every** field before DataMark, widen it by
   one digit (as the firmware would on overflow) and assert rejection. Rule 4
   of §3.4 is only safe if no single-field overflow upstream of DataMark can
   still match the 74-byte grammar; this test is what proves it.
6. Truncated V1 (cut at every length 0..77) -> error, never an exception
   other than `SentenceError`, never a frame.
7. G3X-format line (`=1100000000...`) -> `wrong_format`.
8. Non-ASCII byte in V1 -> `encoding`.
9. Property test, if `hypothesis` is already a dev dependency (don't add it):
   any field tuple within its width round-trips through the reference
   `sprintf` and back. Otherwise a table of boundary values per field
   (`-999/+999`, `0000/9999`, `+0/-1/+1` for the spin cue).

### 7.2 `tests/plugins/onspeed/test_plugin.py` (db writes)

FakeParent / fake-serial style from `tests/plugins/megasquirt/test_megasquirt.py`,
or the real database fixture — whichever the implementing PR finds already
in use for serial plugins. Feed byte chunks, not whole lines, including a
sentence split across two reads and two sentences in one read.

1. V1 -> `AOA == 9.8`, `bad False`; `AOA.Warn == 13.5`.
2. V2 with `min_ias: 30` -> `AOA` written `bad True`. Then V1 -> `bad False`.
3. V2 with `min_ias: 20` -> `AOA == 0.0`, `bad False` (the threshold is the
   plugin's; this test pins that the zero is only suppressed by it, not by a
   zero heuristic, §5.2).
4. V5 -> `AOA.Warn` is `None`. Then V1 -> `13.5`.
5. Setpoint order violated (warn < slow) -> `AOA.Warn` is `None`,
   `setpoint_order_errors == 1`.
6. V1 sent 10 times -> `AOA.Warn` callback fired **once** (change-only write).
7. V1 then the same frame with warn `+150` -> callback fired twice, value 15.0.
8. V4 between two V1s -> V4 counted, `AOA` holds 9.8, nothing else written.
9. 129 bytes with no newline -> buffer discarded, counted; the next V1 decodes.
10. First partial line after open is discarded.
11. Serial `SerialException` from the fake port -> `AOA.fail True`;
    port recovers, V1 -> `fail False`.
12. Staleness: no frames for > 300 ms -> `AOA.old True` via the database
    `update()` path (monkeypatched time), confirming the plugin added no
    timer of its own.
13. Lifecycle: `run()` then `stop()` joins within 1.0 s; a hung thread raises
    `PluginFail`.

### 7.3 Simulator

`tools/onspeed_sim.py` (in fix-gateway): writes V-style sentences at 10 Hz to
a pty or a serial port, sweeping AOA from 0 toward and past the warn setpoint
and stepping flaps. It shares the reference `sprintf` with the tests. This is
how pyEfis AI-LIM-001 gets exercised end to end on the bench without an
OnSpeed box, and how the implementer demonstrates the indicator moving.

### 7.4 What would prove it on hardware

Not required for the implementation DoD — the whole point of this route is
synthetic frames — but the hardware check, for whoever has a box: OnSpeed's
Serial3 into a USB RS-232 adapter on the bench, `fixgwc` reading `AOA` and
`AOA.Warn`, compared against the OnSpeed display while the pitot/AOA ports
are driven (or `LogReplay` is running on the box). `get_status()` `Last Frame`
should match the display field for field.

## 8. Implementation DoD (the follow-on item)

- `onspeed/` package, `connections/onspeed.yaml`, `doc/plugins/onspeed.md`
  (including §3.4's lateral-G drop and §5.2's NaN limitation).
- §7.1-7.2 tests green; §7.3 simulator committed.
- No database yaml changes.
- pyEfis follow-up (separate PR, separate issue): flip
  `test_ai_cat_pitch_limit_indication` out of `xfail` by implementing
  `_show_pitch_limit` against `AOA` + `AOA.Warn`, and update
  `docs/ai_widget_spec.md` / `docs/instrument_verification_status.md`.

## 9. Open questions (not blocking v1)

1. **Percent lift and the OnSpeed band as keys.** OnSpeed's percent lift is
   a normalised margin (90 % = stall warning), close to what fix-gateway#13
   asked for as "normalized 0..1 margin". It and the OnSpeed slow/fast band
   would let pyEfis draw an OnSpeed-style AOA indexer. Publishing them needs
   new FIX keys, which is a key-authorization decision, not a plugin default;
   propose separately if wanted.
2. **`AOA` range drift.** fix-gateway's `AOA` is `min -180, max 180`;
   CAN-FIX parameter 386 is `-90 to 90`. Harmless for this plugin (the
   sentence cannot carry more than +/-99.9), but it is cross-repo drift worth
   a one-line fix in fix-gateway.
3. **A computed low-speed annunciation** in fix-gateway (fix-gateway#13's
   second open question) is out of scope here; it would consume `AOA` and
   `AOA.Warn` like any other client.
