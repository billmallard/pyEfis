# Customizing Beyond the Configurator

Start in the configurator: it lays out screens, sets every instrument option and
holds the aircraft's numbers ([Designing Your Panel](Designing-Your-Panel)).
This page is for what sits underneath: the YAML files on the device, how they
load, and how to change what the configurator does not reach. Every
instrument's options are in the [Instrument Reference](Widget-Reference).

## The files on the device

pyEFIS reads its configuration from `~/makerplane/pyefis/config/`. On every
start it copies the shipped configuration there:

- A file you have not edited is replaced with the new shipped version.
- A file you have edited is kept, and the new shipped version is written beside
  it as `<file>.dist`, for you to compare.

Run with `--config-file <path>` to use another file instead; nothing is copied
then, and `preferences.yaml` must sit beside it.

| Path | What it holds |
|---|---|
| `default.yaml` | The top of the configuration. Each section is a pointer into the `includes:` map of the preferences. |
| `preferences.yaml` | The shipped preferences: styles, gauge slots, feature flags, includes. |
| `preferences.yaml.custom` | Your changes to the preferences. |
| `main/default.yaml` | Display-wide settings: the FIX-Gateway address (`FixServer`, `FixPort`), the [link watchdog](#the-data) (`FixLinkTimeout`, `FixLinkPingKey`), `nodeID`, `screenFullSize`, `screenColor` and `defaultScreen`. |
| `screens/` | One file per screen, plus `default_list.yaml`, the list of screens to load. |
| `includes/` | Reusable groups of instruments. |
| `buttons/` | Button definitions. |
| `lists/` | Listbox lists. |
| `hmi/`, `keybindings/`, `databindings/`, `outputs/`, `logging/` | Knob inputs, keyboard keys, data bindings, outputs and logging. |

## What the configurator owns

`pyefis-data config-pull` installs the panel you designed. It writes only these
files, and replaces them on every pull:

| File | What config-pull puts there |
|---|---|
| `screens/managed.yaml` | A one-screen panel, named after the device's `defaultScreen`. |
| `screens/managed_<name>.yaml`, `screens/managed_list.yaml` | A panel with several screens, and the list of them. |
| `buttons/managed-next*.yaml` | The **SCREEN >** button added to each screen of a multi-screen panel. |
| `preferences.yaml.custom` | The `includes:` entries that point at the managed screens (`SCREEN_<name>`, and `SCREENS_CONFIG` for several screens), and the units from the aircraft parameters. It leaves every other key in the file alone. |
| `.panel_prefs.yaml` | Which unit settings config-pull wrote, so it removes only its own. |
| `.panel_backup/` | The previous panel, restored if a new one stops pyEFIS starting. |

The shipped files are never modified. So:

- **Edit the managed screen files only to try something.** The next pull
  replaces them; make lasting changes in the configurator.
- **Your own keys in `preferences.yaml.custom` are safe.** Styles, gauge
  slots, flags and your own includes survive a pull.
- **A one-screen panel keeps the stock screens loaded.** It replaces only the
  default screen. A multi-screen panel replaces the whole screen list.

See [Setting Up a Device](Setting-Up-a-Device#5-pull-your-panel).

## How the configuration loads

1. `preferences.yaml` is read, and `preferences.yaml.custom` is merged over it.
   Nested sections merge key by key; a value or a list in `.custom` replaces
   the shipped one outright.
2. `default.yaml` is read. Its sections are includes: `main: include:
   MAIN_CONFIG`, `screens: include: SCREENS_CONFIG`, and so on.
3. An `include:` is looked up in three places, in order: relative to the file
   that names it, relative to the configuration directory, and as a name in the
   preferences' `includes:` map.

The shipped `includes:` map names every screen (`SCREEN_PFD: screens/pfd.yaml`)
and the screen list (`SCREENS_CONFIG: screens/default_list.yaml`). Point one at
another file in `preferences.yaml.custom`, and every place that uses the name
follows. That is how config-pull swaps in your panel.

**To add a screen of your own:** write `screens/myscreen.yaml`; copy
`screens/default_list.yaml` to a list of your own and add `SCREEN_MYSCREEN` to
it; then, under `includes:` in `preferences.yaml.custom`, add
`SCREEN_MYSCREEN: screens/myscreen.yaml` and point `SCREENS_CONFIG` at your
list. A configurator panel with several screens sets `SCREENS_CONFIG` to its own
list on every pull, so on such a device build the screen in the configurator
instead.

## Screen files

A screen file holds one or more screens by name:

```yaml
MYSCREEN:
  module: pyefis.screens.screenbuilder
  title: My Screen
  include:
    - HMI_ENCODER_BUTTONS          # the knob's FIX keys
  layout:
    rows: 110
    columns: 200
  instruments:
    - type: airspeed_tape
      row: 6
      column: 15
      span: {rows: 60, columns: 12}
```

### The grid

`layout:` divides the screen into `rows` by `columns` cells. Instruments are
placed in cells, not pixels, so a layout scales to any display. The shipped
screens, and the configurator, use 200 columns by 110 rows; the About and Data
Status screens use 100 by 100.

| `layout:` key | What it does |
|---|---|
| `rows`, `columns` | The grid. |
| `draw_grid: true` | Draws the grid over the screen while you lay it out. |
| `margin: {top, bottom, left, right}` | Keeps a band free, in percent. Left and right are a percent of the screen's **height**. Each must be above 0 and below 100. |

![Grid overlay](../images/draw_grid.png)

### Placing an instrument

| Key | What it does |
|---|---|
| `type` | The instrument type. |
| `row`, `column` | The top-left cell, from 0. Fractions are allowed (`column: 130.5`). |
| `span: {rows, columns}` | How many cells it covers; one cell if left out. Instruments that keep an aspect ratio, such as the HSI and the dials, are drawn as large as fits, centred; `ratio:` overrides the ratio. Others fill the span. |
| `move: {shrink, justify}` | Shrinks it by a percent (0 to below 99) inside its span, then pushes it to `top`, `bottom`, `left` or `right`. `justify` works only with `shrink`. |
| `options:` | The instrument's options; see the [Instrument Reference](Widget-Reference). |
| `disabled:` | Leaves it out; see [Feature flags](#feature-flags-enabled). |
| `preferences:` | A gauge slot name (`ARC1`, `BAR15`) whose settings apply; see [Gauge slots](#gauge-slots-gauges). |

Instruments draw in list order, so a later one paints over an earlier one: put
the attitude display first and the tapes and HSI after it.

![Span](../images/span.png) ![Shrink and justify](../images/shrink.png)

### Screen-level keys

| Key | What it does |
|---|---|
| `encoder`, `encoder_button` | The knob's turn and push FIX keys. Both must be set for the knob to work. |
| `encoder_outer` | The outer ring's FIX key, if there is one. |
| `encoder_timeout` | How long a selection lasts with no input, in ms (10000). |
| `alat_multiplier`, `alat_filter_depth` | The turn coordinator's ball gain and smoothing. |
| `dbpath`, `indexpath`, `metadata`, `refresh_period` | The legacy CIFP Virtual VFR data, from `screens/virtualvfr_db.yaml`. |
| `update_period` | The VSI tape's redraw period, in seconds (0.1). |

The shipped screens take the knob keys from the `HMI_ENCODER_BUTTONS` include
(`ENC3` turn, `BTN3` push, `ENC4` outer ring, 10000 ms).

### `nodeID` and `{id}`

`main/default.yaml` sets `nodeID` (1 by default), one number per display. In
instrument entries and includes, `{id}` is replaced with it. Buttons use this so
each display's touchscreen keys differ: `TSBTN{id}12` is `TSBTN112` on display
1 and `TSBTN212` on display 2.

## Includes

An include is a file whose top level is `instruments:`, built like a screen's
list. Use it as a type:

```yaml
- type: include,RADIO_COMBINED         # a name from the includes: map
  row: 70
  column: 156
  span: {rows: 40, columns: 45}
  replace:
    radio_id: 1
```

- The name is looked up as a path relative to the configuration directory, then
  in the `includes:` map. An unknown name stops the screen loading.
- The include is drawn as if it starts at 0,0; its `row` and `column` move the
  whole group, and its `span` scales it.
- `replace:` fills `{name}` placeholders inside it: `COMACTFREQ{radio_id}`
  becomes `COMACTFREQ1`. Replacements carry into nested includes and into
  listbox list files.
- Includes can nest, through further `type: include,...` entries; not
  recursively.

## Ganged instruments

A `ganged_` prefix repeats a type across groups. The stock screens build their
cylinder rows this way.

```yaml
- type: ganged_vertical_bar_gauge
  gang_type: horizontal               # required: horizontal or vertical
  row: 8
  column: 1
  span: {rows: 5, columns: 27}
  groups:
    - name: Power
      instruments:
        - {options: {name: Volt, dbkey: VOLT, show_units: false}}
        - {options: {name: Amp, dbkey: CURRNT, show_units: false}}
    - name: EGT
      gap: 10                         # space between this group's instruments
      common_options:
        egt_mode_switching: true
        normalize_range: 400
      instruments:
        - {options: {name: "1", dbkey: EGT11}}
        - {options: {name: "2", dbkey: EGT12}}
```

- `gang_type` is required; without it the screen does not load.
- `common_options` apply to every instrument in a group; an instrument's own
  `options` override them.
- `gap` spaces the instruments **within** a group, as a percent of one
  instrument's cell. The space **between** groups is fixed.
- The group `name` is a label for you; pyEFIS does not use it.
- A child hidden with `options: {disabled: ...}` keeps its slot.

## Preferences

`preferences.yaml` ships the defaults; put your changes in
`preferences.yaml.custom`. Its sections:

### Styles: `style` and `styles`

`style:` turns named styles on and off. It is a map of name to `true`/`false`,
not a list, and every style set to `true` applies together:

```yaml
style:
  basic: true
  segmented: true
  dseg: false
```

The shipped styles are `basic`, `segmented` (LED-like segmented gauges),
`dseg` (a segmented digital font), `ghost` (faint unlit segments, with `dseg`),
`8khz` (8.33 kHz radio channel spacing) and `radio_confirm` (confirm a radio
frequency after typing it).

`styles:` says what each style changes, per gauge family:

```yaml
styles:
  ARC:
    segmented:
      segments: 28
  BAR:
    segmented:
      segments: 28
```

The family is an instrument's `preferences:` slot name with the digits removed:
`BAR15` is in `BAR`. The shipped families are `ARC`, `BAR` and `TEXT`. The
settings are ordinary instrument options.

### Gauge slots: `gauges`

The stock screens place gauges by slot (`preferences: ARC1`) rather than by
key, so you re-purpose one in one place:

```yaml
gauges:
  ARC1:
    name: MAX EGT
    dbkey: EGTMAX1
    temperature: true
  BAR32:
    styles:
      segmented:
        segments: 22      # this slot only
```

**Which setting wins**, lowest first: the screen file's own options, then the
style's family settings, then the slot's settings, then the slot's own style
settings. So a slot's settings override the screen file.

### Feature flags: `enabled`

Flags that turn parts of the stock screens on and off: `CYLINDER_1` to
`CYLINDER_4`, `TRIM_CONTROLS` and `PITCH_TRIM` / `YAW_TRIM` / `ROLL_TRIM`,
`WIND_DISPLAY`, `VSI_BALL`, `VSI_TAPE`, and `AUTO_START` (needed for pyEFIS to
stay running when started by systemd).

An instrument refers to a flag with `disabled:`:

| Where | Effect | `not FLAG` |
|---|---|---|
| `disabled: FLAG` beside `type:` | Not built at all when the flag is false. `true` always leaves it out. | yes |
| `options: {disabled: FLAG}` in a ganged group | Built, then hidden; its slot is kept. | yes |
| `options: {disabled: FLAG}` on any other instrument | Built, then hidden. | yes |

A flag that is not in `enabled:` stops the screen loading.

```yaml
enabled:
  CYLINDER_3: false
  CYLINDER_4: false      # a two-cylinder engine
```

### Units: `units`

The unit each unit group starts in:

```yaml
units:
  Pressure: hPa
```

The groups are `Temperature` (°F, °C), `Pressure` (inHg, hPa) and `Altitude`
(Ft, M); each starts in the first unless this names the other. Names match in
any case; an unknown one is logged and ignored. config-pull writes
`units.Pressure` from the aircraft's altimeter-setting units. The **Units**
button and the `set instrument units` action switch at runtime.

### Includes: `includes`

The map of names to files, described [above](#how-the-configuration-loads).

## Colours

A colour option takes a Qt colour name (`green`, `darkRed`), `#rrggbb`,
`#aarrggbb` for transparency, or a **token**:

| Token | Used for |
|---|---|
| `surface.base`, `surface.raised` | The panel ground; readout boxes, plates, buttons. |
| `ink.primary`, `ink.secondary`, `ink.muted` | Data values; labels and prefixes; inactive text. |
| `line.border`, `line.major`, `line.minor`, `line.fine` | Frames; tick weights. |
| `accent` | Interactive, selected, focused. |
| `state.valid`, `state.caution`, `state.warning` | Received or complete; attention; exceeded or failed. |
| `nav.course`, `nav.reference`, `nav.ownship` | Active course and track; bugs and selected values; own-ship symbol. |
| `map.road`, `map.water`, `map.terrain` | Map layers. |

`line.major`, `line.minor`, `line.fine`, `state.warning` and `map.terrain` have
no value yet; an option naming one is dropped with a warning and the instrument
keeps its default.

A style can give tokens values in a `colors` block:

```yaml
styles:
  colors:
    basic:
      surface.base: "#000000"
      ink.primary: "#f0f0f0"
```

Tokens are resolved after everything else, so a screen, slot or style setting
can itself be a token. A colour option that nothing sets takes its token's
value from the active styles. `nav.*` and `state.*` mean the same in every
style, so a `colors` block cannot change them. With no `colors` block, every
instrument keeps its own default.

## Fonts

`font_family` and `font_percent` come from the instrument's options, after the
styles and slots have been applied. The configurator offers DejaVu Sans
Condensed (the default), DejaVu Sans, DejaVu Sans Mono, B612, Inter, Roboto and
Open Sans. pyEFIS bundles no fonts; the DejaVu family is on every Raspberry Pi
OS, and the others must be installed on the device. The `dseg` style uses
`DSEG14 Classic`.

Text instruments and gauges also take:

| Option | What it does |
|---|---|
| `font_mask` | A sizing template. The text is sized so this string fits: `"000"` makes room for three digits, so the text never jumps as digits change. |
| `font_ghost_mask` | A dim string drawn behind the text, like unlit LCD segments: `"88.88"` behind `font_mask: "00.00"`. |
| `font_ghost_alpha` | The ghost's opacity, 0 to 255 (50). |
| `units_font_mask`, `name_font_mask`, and their `_ghost_mask` forms | The same for a gauge's units and name. |

![Numeric display with a segmented font and ghosting](../images/numeric_display_segmented_ghosting.png)

## The data

pyEFIS draws what fix-gateway publishes. Every value is a **FIX key** with a
value, a range (min and max), units, quality flags and **aux** values.

- **Aux values** carry each key's limits: a gauge reads `lowAlarm`, `lowWarn`,
  `highWarn` and `highAlarm`; the airspeed key `IAS` carries `Vs`, `Vs0`,
  `Vfe`, `Vno` and `Vne`. To move a redline, change the aux value in
  fix-gateway, or enter it under the configurator's
  [aircraft parameters](Designing-Your-Panel#aircraft-parameters).
- **Quality flags:**

| Flag | Means | Shown as |
|---|---|---|
| old | Not updated within its time limit. | Dimmed; tape readouts go blank. |
| bad | Present but untrusted. | Dimmed; tape readouts go blank. |
| fail | The source has failed. | The value is treated as 0; `X`s fill the readout (`xxx` with no mask). |
| annunciate | Attention requested. | Red text. |

Each instrument's page says how it shows them. The keys pyEFIS reads and writes
are on [FIX Database Keys](FIX-Database-Keys).

**Link watchdog.** pyEFIS asks fix-gateway for one input key every 0.5 s (every
half `FixLinkTimeout` when that is under 1 s). If nothing comes back for
`FixLinkTimeout` seconds (2.0), it marks every value failed; when the gateway
answers again, it re-reads every key. Both settings go in `main/default.yaml`:

| Key | Default | What it does |
|---|---|---|
| `FixLinkTimeout` | `2.0` | Seconds of silence before every value is marked failed. `0` turns the watchdog off. |
| `FixLinkPingKey` | the first of `PITCH`, `ROLL`, `ALT`, `IAS` in the database | The key it asks for. Pick an input key pyEFIS never writes. |

If the ping key is not in the database, the watchdog does not run and pyEFIS
logs an error.

### Gauge colours

The four gauges share two palettes, one for good data and one for old, bad or
failed data, and every colour can be set:

| Part | Good | Old, bad or failed | Options |
|---|---|---|---|
| Background | black | black | `bg_good_color`, `bg_bad_color` |
| Normal band | green | dark grey | `safe_good_color`, `safe_bad_color` |
| Warning band | yellow | dark yellow | `warn_good_color`, `warn_bad_color` |
| Alarm band | red | dark red | `alarm_good_color`, `alarm_bad_color` |
| Text | white | grey | `text_good_color`, `text_bad_color` |
| Indicator | white | grey | `pen_good_color`, `pen_bad_color` |
| Highlight | magenta | dark magenta | `highlight_good_color`, `highlight_bad_color` |
| Annunciating text | red | | `text_annunciate_color` |

The readout turns to the warning colour past a warning limit, and the alarm
colour past an alarm limit.

## The knob

With `encoder` and `encoder_button` set on a screen, a rotary encoder drives
it. Instruments that can be selected, in the order of their `encoder_order`:
gauges, `numeric_display`, `button`, `listbox`, `checklist`, `flight_plan` and
the altitude tape's two boxes.

- Turning moves an orange highlight between them.
- Pushing selects one. Turning then changes its value or scrolls its list.
- Pushing again keeps the value. Letting the knob time out puts it back.

The stock screens number `encoder_order` in blocks by include: 1000xx for the
side buttons, 2000xx for attitude, trim and dimmer, 4000xx for the radio and
6000xx for the engine screens.

Gauge editing options:

| Option | What it does |
|---|---|
| `encoder_set_key` | Edit a different key from the one shown. |
| `encoder_multiplier` | Step per click (1). |
| `encoder_coarse_multiplier` | Outer-ring step, as a multiple (10). |
| `encoder_set_real_time` | Write each step at once (still put back on timeout). |
| `encoder_num_mask` | Digit-by-digit entry with a mask such as `"000.000"`, for radio tuning. |
| `clipping` | Keep the value inside the key's range. |
| `touch_edit` | Allow selecting it by touch too. |

## How options reach an instrument

An instrument's options are the screen file's `options:` with its style and
slot settings merged over them, as [above](#gauge-slots-gauges). A few are
handled specially:

- any option whose name contains `dbkey` binds the instrument to that key;
- `encoder_order` puts it in the knob's order;
- `egt_mode_switching: true` on a vertical bar connects the EGT buttons;
- `temperature`, `pressure` and `altitude: true` turn on unit switching;
- `font_percent` as a whole number is read as a percent.

Everything else is set on the instrument as an attribute, converted to the
attribute's type. An option the [Instrument Reference](Widget-Reference) does
not list is still applied, with a warning in the log that it may have no
effect.

## Example: a classic six-pack screen

pyEFIS no longer ships a six-pack screen. Here is the steam-gauge layout as a
screen file to start from: airspeed, attitude and altimeter across the top;
turn coordinator, HSI and VSI across the bottom; a message strip along the
bottom edge.

```yaml
SIXPACK:
  module: pyefis.screens.screenbuilder
  title: Standard Instrument Panel
  include:
    - HMI_ENCODER_BUTTONS
  layout:
    rows: 110
    columns: 200
  instruments:
    - type: airspeed_dial
      row: 0
      column: 0
      span: {rows: 50, columns: 62}
    - type: atitude_indicator
      row: 0
      column: 62
      span: {rows: 50, columns: 62}
    - type: altimeter_dial
      row: 0
      column: 124
      span: {rows: 50, columns: 62}
      options:
        altitude: true
    - type: turn_coordinator
      row: 50
      column: 0
      span: {rows: 50, columns: 62}
    - type: horizontal_situation_indicator
      row: 50
      column: 62
      span: {rows: 50, columns: 62}
      move:
        shrink: 11
        justify: [bottom]
    - type: vsi_dial
      row: 50
      column: 124
      span: {rows: 50, columns: 62}
    - type: value_text
      row: 100
      column: 60
      span: {rows: 10, columns: 140}
      options:
        dbkey: MAVMSG
```

Save it as `screens/sixpack.yaml` and add it as described in
[How the configuration loads](#how-the-configuration-loads).
