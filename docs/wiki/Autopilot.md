# Autopilot

pyEFIS does not fly the aircraft. The autopilot is a separate source behind
fix-gateway, such as the X-Plane or MAVLink plugin; see the fix-gateway
[Plugins](https://github.com/billmallard/fix-gateway/wiki/Plugins) page.
pyEFIS gives you two instruments for it:

- **`autopilot_panel`**, the mode controller: mode keys and the target boxes.
  A key press asks the autopilot for a mode. The autopilot decides.
- **`ap_annunciator`**, the mode strip across the top of the attitude display.
  It shows the modes the autopilot reports.

Both draw only what the autopilot reports on the FIX keys. A key never lights
because you pressed it.

## The autopilot panel

### Layout

The keys come in three groups:

| Group | Keys |
|---|---|
| Lateral | `APR`, `NAV`, `HDG`, `TRK` |
| Centre | `AP`, `FD`, `YD`, `LVL` |
| Vertical | `IAS`, `VNAV`, `VS`, `ALT` |

Every key is shown except `TRK`. The `buttons` option picks the keys; an
unknown name is ignored with a warning in the log. `LVL` has its own face
colour (blue by default) so you can find it without reading it.

There are four target boxes: **HDG**, **VS**, **IAS** and **ALT SEL**.

- **`layout: full`** (the default) is three columns, one per group, with two
  keys to a row. The HDG box sits over the lateral keys. The VS, IAS and ALT
  SEL boxes sit side by side over the centre and vertical keys. A message line
  runs along the bottom.
- **`layout: compact`** is two rows for small panels and side strips: the four
  boxes and the message line on top, and all the keys in one row below.

### Pressing a key

A press sends the key's name to the autopilot. pyEFIS writes `APCMD` (for
example `HDG`) and then adds one to `APCMDSEQ`. The autopilot acts when the
counter changes.

- A press is never confirmed and never waits on anything. `LVL` is one press.
- A greyed key still sends its request. The autopilot refuses what it cannot
  fly and says why on the message line.
- If the gateway has no `APCMD` or `APCMDSEQ`, the press is dropped and logged.

### What a key shows

Each key has a bar across its top. The bar shows the state the autopilot
reports for that mode:

| You see | It means |
|---|---|
| Solid green bar | The mode is active. |
| White outline bar | The mode is armed. |
| Dark bar | The mode is off. |
| Flashing white border | You pressed it and the autopilot has not answered yet. This lasts up to 2 seconds. |
| Amber border (and amber outline bar if not active) | The autopilot did not take the request within 2 seconds. It stays for 3 seconds. |
| Grey label | The mode is off and the autopilot does not list it in `APCAPS`. The key is still there, and still sends. |

The flash ends as soon as the key's reported state changes.

How each key reads the reported state:

- `AP`, `FD` and `YD` are active while `APENG`, `FDENG` and `YDENG` are true.
- `HDG`, `TRK`, `IAS`, `VNAV`, `VS` and `ALT` are active when they are the
  active lateral or vertical mode, and armed when they are in the armed list.
- `NAV` lights for a lateral navigation mode: `GPS`, `VOR`, `LOC` or `BC`.
- `APR` lights for vertical approach guidance: `GS` or `GP`. So a coupled ILS
  lights both `NAV` and `APR`, and a localizer-only approach lights `NAV`
  alone.
- `ALT` also shows armed while the autopilot is capturing the selected
  altitude (`APALTCAP`).
- `LVL` is active while `LVL` is the lateral or the vertical mode.

### The message line

The message line shows the autopilot's own message (`APMSG`) in white. After a
request that was not taken it turns amber, and shows `APMSG`, or
`<KEY> NOT TAKEN` (for example `VS NOT TAKEN`) when the autopilot sent no
message.

### No autopilot data

If any of the autopilot's state keys is old, bad or failed, or the gateway
does not define it, the panel shows **NO AUTOPILOT DATA** in amber on the
message line. Every bar goes dark and every key greys. The panel never keeps
the last state. The keys it checks are `APENG`, `FDENG`, `YDENG`, `APLAT`,
`APLATARM`, `APVERT`, `APVERTARM`, `APALTCAP`, `APCAPS` and `APMSG`.

### The target boxes

Each box shows a target in cyan, or `---` when there is none. Touch a box to
give it the knob, as on
[The Panel at a Glance](The-Panel-at-a-Glance#touch-a-value-then-turn-the-knob).
On the knob walk the panel is one stop, and it starts on the first box.

| Box | Key | Inner knob | Outer ring | Push |
|---|---|---|---|---|
| **HDG** | `HEADBUG` | 1° | 10° | Bug to current heading (`HEAD`); wraps through 360 |
| **VS** | `VSSEL` | 100 ft/min | 500 ft/min | Current vertical speed (`VS`), rounded to 100 ft/min |
| **IAS** | `IASSEL` | 1 kt | 10 kt | Current airspeed (`IAS`), rounded to 1 kt |
| **ALT SEL** | `ALTSEL` | 100 ft | 1000 ft | Current altitude, rounded to 100 ft |

- Every step is sent to the gateway at once.
- A push syncs and ends the edit. With no valid value to sync to, nothing is
  written and the box keeps the knob.
- An `IASSEL` of 0 means no target, and shows `---`. The first step from no
  target starts from the current value. With no valid airspeed either, the
  step writes nothing.
- The IAS box never writes 0: a step or a push stops at 1 kt, so the knob
  cannot unset the target the autopilot is flying. These are the airspeed
  tape's rules.
- The ALT SEL box follows the same rules as the selected altitude on the
  altitude tape.
- The VS or IAS box gets a green label and border while that is the active
  vertical mode.
- `touch_edit: false` turns touch editing off.

These are the same keys the HSI, the airspeed tape and the altitude tape set,
so a change on one shows on the others.

## The mode annunciator

`ap_annunciator` is a strip of three groups. With `ap_position: left` (the
default) the order is AP and YD, then lateral, then vertical. With
`ap_position: center` it is lateral, then AP and YD, then vertical: the order
of the panel's groups.

| Part | Shows |
|---|---|
| **AP**, **YD** | Green while `APENG` and `YDENG` are true. |
| Lateral, left half | The active lateral mode (`APLAT`), green. |
| Lateral, right half | The armed lateral modes (`APLATARM`), white. |
| Vertical, left half | The active vertical mode (`APVERT`), green, with its target where there is one. |
| Vertical, right half | The armed vertical modes (`APVERTARM`), white. |

**The vertical target.** `VS` shows `VSSEL` (`VS +500`), `IAS` shows `IASSEL`
(`IAS 120`), and `ALT` shows `APALTREF` (`ALT 8500`), the altitude the
autopilot reports it is holding. If the target key is missing, old, bad or
failed, the mode shows alone. While the autopilot captures the selected
altitude (`APALTCAP`) the vertical mode reads `ALT CAP`.

**A mode change** is boxed and flashes for `mode_flash_s` seconds (10 by
default). This includes armed to active, a reversion and the start of
altitude capture. The first reading after start-up does not flash.

**A disconnect.** While the autopilot holds `APDISC`, the strip shows a red
boxed `AP` that blinks. It stays as long as the autopilot holds the flag. With
`touch_ack` on (the default), a tap on the strip acknowledges it: pyEFIS sends
`APCMD` `DISC`. The tap works only while `APDISC` is set and `APENG` is false,
so it cannot disconnect anything.

**No data.** The strip draws nothing until it has had one good reading, so an
aircraft with no autopilot gets no caption. After that, if any of its state
keys goes old, bad or failed, it shows **NO AP DATA**: amber if the autopilot
was engaged at the last good reading, grey if not. The keys it checks are
`APENG`, `YDENG`, `APLAT`, `APLATARM`, `APVERT`, `APVERTARM`, `APALTCAP` and
`APDISC`.

`background_opacity` here runs from 0 (clear) to 1 (opaque), not 0 to 100.

## On the PFD

The tapes and the attitude display carry their own autopilot cues:

- The `IASSEL` bug and box on the airspeed tape, the capture border on the
  altitude tape's `ALTSEL` box, and the `VSSEL` bug on `vsi_pfd` and on an
  altitude tape set to `VS`: see
  [Airspeed, Altitude and Vertical Speed](Airspeed-Altitude-and-Vertical-Speed).
- The flight director: see
  [Attitude and Synthetic Vision](Attitude-and-Synthetic-Vision).

## Customizing

### In the configurator

#### `autopilot_panel`

<!-- generated:autopilot_panel -->

**Autopilot Panel** · palette category `navigation`

FIX keys it reads by default: `APCMD`, `APCMDSEQ`, `APENG`, `FDENG`, `YDENG`, `APLAT`, `APLATARM`, `APVERT`, `APVERTARM`, `APALTCAP`, `APCAPS`, `APMSG`, `HEADBUG`, `VSSEL`, `IASSEL`, `ALTSEL`, `HEAD`, `VS`, `IAS`, `ALT`.

| Option | Configurator label | Default | Values | What it does |
|---|---|---|---|---|
| `layout` | Layout | `full` | `full`, `compact` | full: three columns (lateral, centre, vertical), each with its value boxes over its keys; compact: two rows, the boxes over one row of keys, for small panels and side strips |
| `buttons` | Buttons | `APR,NAV,HDG,AP,FD,YD,LVL,IAS,VNAV,VS,ALT` |  | comma list of the keys shown, from APR, NAV, HDG, TRK, AP, FD, YD, LVL, IAS, VNAV, VS, ALT; drop YD for an airplane with no yaw damper. TRK is off by default. A key the autopilot cannot fly is greyed, never hidden |
| `touch_edit` | Touch to edit | on | on / off | touch a value box (HDG, VS, IAS, ALT SEL) to give it the knob: inner/outer steps, push to sync |
| `active_color` | Active colour | `#00ff00` | colour | indicator bar of an active mode, and the accent on the active vertical mode's box |
| `armed_color` | Armed colour | `#ffffff` | colour | outline of an armed mode's indicator bar |
| `caution_color` | Caution colour | `#ffaa00` | colour | a request not taken, and the no-autopilot-data message |
| `key_color` | Key colour | `#101418` | colour | key face |
| `level_color` | LVL colour | `#1f5fbf` | colour | the LVL key's own face colour, so it can be found without looking for its label |
| `text_color` | Text colour | `#ffffff` | colour | key labels and the autopilot message |
| `muted_color` | Unavailable colour | `#aaaaaa` | colour | greyed keys and the box labels |
| `line_color` | Line colour | `#ffffff` | colour | key and box borders |
| `target_color` | Target colour | `#00ffff` | colour | the selected values in the boxes |
| `bg_color` | Background | `#000000` | colour | panel ground behind the keys and boxes |
| `encoder_order` | Knob order | unset | step 1 | place on the screen's knob walk: turning the knob visits instruments in ascending order, and push gives the highlighted one the knob; blank = not on the walk |

<!-- /generated -->

#### `ap_annunciator`

<!-- generated:ap_annunciator -->

**Autopilot Mode Annunciator** · palette category `attitude`

FIX keys it reads by default: `APENG`, `YDENG`, `APLAT`, `APLATARM`, `APVERT`, `APVERTARM`, `APALTCAP`, `APALTREF`, `APDISC`, `VSSEL`, `IASSEL`.

| Option | Configurator label | Default | Values | What it does |
|---|---|---|---|---|
| `ap_position` | AP/YD position | `left` | `left`, `center` | left: AP YD \| lateral \| vertical; center: lateral \| AP YD \| vertical, the control head's order |
| `mode_flash_s` | Mode change flash (s) | `10` |  | how long a new active mode is boxed and flashes |
| `touch_ack` | Tap acknowledges disconnect | on | on / off | a tap on the strip sends APCMD DISC while a disconnect alert (APDISC) is shown and the autopilot is disengaged |
| `active_color` | Active mode colour | `#00ff00` | colour | active modes and AP/YD engaged (AC 25-11B Table 5-1: engaged modes green) |
| `armed_color` | Armed mode colour | `#ffffff` | colour | armed modes |
| `warning_color` | Disconnect warning colour | `#ff0000` | colour | the flashing AP of a disconnect alert (APDISC) |
| `background_color` | Background colour | `#000000` | colour | the strip's fill |
| `background_opacity` | Background opacity | `0.75` |  | 0 (clear) to 1 (opaque) |

<!-- /generated -->

### Feeding it

The autopilot source writes the state keys and reads the requests. The full
list, with who reads and writes each, is on
[FIX Database Keys](FIX-Database-Keys#autopilot).

## See also

- [The Panel at a Glance](The-Panel-at-a-Glance): the knob and touch editing.
- [The HSI](The-HSI): the heading bug and nav sources.
- [Widget Reference](Widget-Reference): every instrument type.
