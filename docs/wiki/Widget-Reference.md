# Instrument Reference

Every instrument you can place on a pyEFIS screen, by its `type:`, with every
option it takes. To learn what an instrument shows and how to fly it, start
with its page under **Flying it**; come here for the full option list.

## How to read these pages

The option tables on the reference pages are generated from pyEFIS's instrument
registry (`src/pyefis/screens/screenbuilder_factory.py`), the same records the
configurator builds its palette and **Properties** panel from. So each table
lists exactly what the configurator offers, under the name the YAML uses:

| Column | Means |
|---|---|
| Option | The key in the instrument's `options:`. |
| Configurator label | What the Properties panel calls it. |
| Default | The value used when it is not set. `unset` means no value; `empty` means an empty string. |
| Values | The choices, or the allowed range. |
| What it does | The help text the configurator shows. |

Some instruments also read values from the FIX item itself, such as V-speeds
or gauge limits. Those are listed under each table: they are the aircraft's
numbers, set in fix-gateway through the
[aircraft parameters](Designing-Your-Panel#aircraft-parameters), not panel
options.

The tables are regenerated with `docs/images/reference/gen_reference.py`; the
README beside it has the command.

## What every instrument takes

**Placement**, at the instrument level beside `type:`:

| Field | Means |
|---|---|
| `row`, `column` | The grid cell of the top-left corner, from 0. Fractions are allowed. |
| `span` | `{rows, columns}`: how many cells it covers. |
| `move` | `{shrink: percent, justify: [top, bottom, left, right]}`: fine placement inside the cell. |
| `disabled` | A preference name from the `enabled:` section, or `true`, to leave it out. |

**Options** every instrument accepts:

| Option | Default | Means |
|---|---|---|
| `font_family` | `DejaVu Sans Condensed` | One of `DejaVu Sans Condensed`, `DejaVu Sans`, `DejaVu Sans Mono`, `B612`, `Inter`, `Roboto`, `Open Sans`. |
| `font_percent` | unset | Font size as a fraction of the instrument's height (a whole number is read as a percent). Some instruments size their text from a font mask instead. |
| `encoder_order` | unset | Its place in the knob's order, on instruments the knob can select. |

**Options outside the tables.** An option the registry does not declare is
still set on the instrument, and pyEFIS logs a warning that it "is applied but
may have no effect". Where such an option does work, the reference page says
so. A few are handled for every instrument: `temperature: true`,
`pressure: true` and `altitude: true` (unit switching, on the types their
pages name), and `egt_mode_switching` on vertical bars.

**Ganged instruments.** A `ganged_` prefix on a type (`ganged_vertical_bar_gauge`)
repeats it across groups; the stock screens build their cylinder rows this way.
See [Engine & Data Gauges](Widgets-Engine-Gauges#ganged-gauges).

## All instruments

<!-- generated:index -->

| Type | Name | Category | FIX keys read by default | Reference |
|---|---|---|---|---|
| `about` | About / System (hidden) | system | -- | [System & Containers](Widgets-System#about) |
| `airspeed_box` | Airspeed Box (hidden) | airspeed | `IAS`, `GS`, `TAS` | [Flight Instruments](Widgets-Flight-Instruments#airspeed_box) |
| `airspeed_dial` | Airspeed Dial | airspeed | `IAS` | [Flight Instruments](Widgets-Flight-Instruments#airspeed_dial) |
| `airspeed_tape` | Airspeed Tape | airspeed | `IAS` | [Flight Instruments](Widgets-Flight-Instruments#airspeed_tape) |
| `airspeed_trend_tape` | Airspeed Trend Tape | airspeed | `IAS` | [Flight Instruments](Widgets-Flight-Instruments#airspeed_trend_tape) |
| `altimeter_dial` | Altimeter Dial | altitude | `ALT` | [Flight Instruments](Widgets-Flight-Instruments#altimeter_dial) |
| `altimeter_tape` | Altimeter Tape | altitude | `ALT` | [Flight Instruments](Widgets-Flight-Instruments#altimeter_tape) |
| `altimeter_trend_tape` | Altimeter Trend Tape | altitude | `VS` | [Flight Instruments](Widgets-Flight-Instruments#altimeter_trend_tape) |
| `arc_gauge` | Arc Gauge | gauge | -- | [Engine & Data Gauges](Widgets-Engine-Gauges#arc_gauge) |
| `atitude_indicator` | Attitude Indicator | attitude | `PITCH`, `ROLL`, `ALAT`, `TAS` | [Attitude & SVS](Widgets-Attitude-and-SVS#atitude_indicator) |
| `button` | Button | control | -- | [Text & Interactive](Widgets-Text-and-Interactive#button) |
| `checklist` | Checklist | list | -- | [Text & Interactive](Widgets-Text-and-Interactive#checklist) |
| `data_annunciation` | Data Annunciation | system | -- | [System & Containers](Widgets-System#data_annunciation) |
| `data_status` | Data Status (hidden) | system | -- | [System & Containers](Widgets-System#data_status) |
| `flight_plan` | Flight Plan | navigation | `FPLCOUNT`, `FPLNAME`, `FPLSEQ`, `FPLSTATE`, `FPLACTLEG`, `FPLAPR`, `FPLINTEG` | [Navigation](Widgets-Navigation#flight_plan) |
| `heading_display` | Heading Display (hidden) | navigation | `HEAD` | [Flight Instruments](Widgets-Flight-Instruments#heading_display) |
| `heading_tape` | Heading Tape | navigation | `HEAD` | [Flight Instruments](Widgets-Flight-Instruments#heading_tape) |
| `horizontal_bar_gauge` | Horizontal Bar Gauge | gauge | -- | [Engine & Data Gauges](Widgets-Engine-Gauges#horizontal_bar_gauge) |
| `horizontal_situation_indicator` | Horizontal Situation Indicator (HSI) | navigation | `COURSE`, `CDI`, `GSI`, `HEAD`, `BRG1`, `BRG2`, `BRG1SRC`, `BRG2SRC` | [Flight Instruments](Widgets-Flight-Instruments#horizontal_situation_indicator) |
| `listbox` | Listbox | list | -- | [Text & Interactive](Widgets-Text-and-Interactive#listbox) |
| `moving_map` | Moving Map | navigation | `LAT`, `LONG`, `TRACKM`, `TRACK` | [Navigation](Widgets-Navigation#moving_map) |
| `nav_status` | Nav Status | navigation | `FPLSTATE`, `FPLPHASE`, `WPFROM`, `WPNAME`, `WPNEXT`, `WPDIS`, `WPETE`, `FPLAPRTYPE`, `FPLDBCYC`, `FPLTURN` | [Navigation](Widgets-Navigation#nav_status) |
| `numeric_display` | Numeric Display | text | -- | [Engine & Data Gauges](Widgets-Engine-Gauges#numeric_display) |
| `static_text` | Static Text | text | -- | [Text & Interactive](Widgets-Text-and-Interactive#static_text) |
| `tab_section` | Tab Section | container | -- | [System & Containers](Widgets-System#tab_section) |
| `turn_coordinator` | Turn Coordinator | attitude | `ROT`, `ALAT` | [Flight Instruments](Widgets-Flight-Instruments#turn_coordinator) |
| `value_text` | Value Text | text | -- | [Text & Interactive](Widgets-Text-and-Interactive#value_text) |
| `vertical_bar_gauge` | Vertical Bar Gauge | gauge | -- | [Engine & Data Gauges](Widgets-Engine-Gauges#vertical_bar_gauge) |
| `virtual_vfr` | Virtual VFR / Synthetic Vision | attitude | `PITCH`, `LAT`, `LONG`, `ALT`, `ROLL`, `ALAT`, `TAS` | [Attitude & SVS](Widgets-Attitude-and-SVS#virtual_vfr) |
| `vsi_dial` | VSI Dial | vertical_speed | `VS` | [Flight Instruments](Widgets-Flight-Instruments#vsi_dial) |
| `vsi_pfd` | VSI (PFD) | vertical_speed | `VS` | [Flight Instruments](Widgets-Flight-Instruments#vsi_pfd) |
| `weston` | Weston | system | -- | [System & Containers](Widgets-System#weston) |
| `wind_display` | Wind Display | wind | `HWIND`, `XWIND` | [Flight Instruments](Widgets-Flight-Instruments#wind_display) |

<!-- /generated -->

**Hidden** types are not in the configurator's palette but still load, so
panels that use them keep working.

The FIX keys themselves are described on [FIX Database Keys](FIX-Database-Keys).
