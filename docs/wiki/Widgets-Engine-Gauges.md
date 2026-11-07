# Engine & Data Gauges

The four general-purpose gauges that show any FIX value against its range and
limits. How they read, the EGT leaning modes and the cylinder groups are on
[Engine Monitoring](Engine-Monitoring); this page is the full option list. Each
table is generated from pyEFIS's instrument registry; see
[Widget Reference](Widget-Reference#how-to-read-these-pages).

| `type:` | Shape | Units shown by default |
|---|---|---|
| `arc_gauge` | An arc with a pointer and a readout. | no |
| `horizontal_bar_gauge` | A horizontal bar and a readout. | yes |
| `vertical_bar_gauge` | A vertical bar and a readout; the cylinder bars. | yes |
| `numeric_display` | A readout only, coloured by the limits. | no |

All four:

- have no FIX key of their own: set `dbkey`;
- take their range from the FIX item's minimum and maximum, and their bands
  from its `lowAlarm`, `lowWarn`, `highWarn` and `highAlarm`, set in fix-gateway
  through the [aircraft parameters](Designing-Your-Panel#aircraft-parameters);
- can be selected with the knob to set their value (below).

---

## `arc_gauge`

![Arc gauge](../images/arc_gauge.png)
![Arc gauge, segmented](../images/arc_gauge_segmented.png)

<!-- generated:arc_gauge -->

**Arc Gauge** · palette category `gauge`

How it reads and flies: [Engine Monitoring](Engine-Monitoring).

| Option | Configurator label | Default | Values | What it does |
|---|---|---|---|---|
| `dbkey` | FIX key | empty | FIX key | FIX-database key whose value this gauge displays |
| `name` | Name | empty |  | label drawn on the gauge (e.g. OIL P, CHT) |
| `decimal_places` | Decimal places | `1` |  | digits after the decimal point in the readout |
| `show_units` | Show units | off | on / off | append the FIX key's engineering units to the readout |
| `segments` | Segments | `0` |  | 0 = solid band; >0 draws a segmented (LED-style) band |
| `name_location` | Name location | `top` | `top`, `right` | where the name label sits relative to the gauge |

Values it reads from the FIX item, set in fix-gateway (the aircraft parameters), not on the panel:

| Value | From | Meaning |
|---|---|---|
| `Min` | min | Range minimum |
| `Max` | max | Range maximum |
| `lowAlarm` | aux | Low alarm (red) |
| `lowWarn` | aux | Low warning (yellow) |
| `highWarn` | aux | High warning (yellow) |
| `highAlarm` | aux | High alarm (red) |

<!-- /generated -->

---

## `vertical_bar_gauge`

![Vertical bar gauge](../images/vertical_bar_gauge.png)
![Vertical bar gauge, segmented](../images/vertical_bar_gauge_segmented.png)

<!-- generated:vertical_bar_gauge -->

**Vertical Bar Gauge** · palette category `gauge`

How it reads and flies: [Engine Monitoring](Engine-Monitoring).

| Option | Configurator label | Default | Values | What it does |
|---|---|---|---|---|
| `dbkey` | FIX key | empty | FIX key | FIX-database key whose value this gauge displays |
| `name` | Name | empty |  | label drawn on the gauge (e.g. OIL P, CHT) |
| `decimal_places` | Decimal places | `1` |  | digits after the decimal point in the readout |
| `show_units` | Show units | on | on / off | append the FIX key's engineering units to the readout |
| `segments` | Segments | `0` |  | 0 = solid bar; >0 draws a segmented (LED-style) bar |

Values it reads from the FIX item, set in fix-gateway (the aircraft parameters), not on the panel:

| Value | From | Meaning |
|---|---|---|
| `Min` | min | Range minimum |
| `Max` | max | Range maximum |
| `lowAlarm` | aux | Low alarm (red) |
| `lowWarn` | aux | Low warning (yellow) |
| `highWarn` | aux | High warning (yellow) |
| `highAlarm` | aux | High alarm (red) |

<!-- /generated -->

Only the vertical bar has the EGT modes and the hottest-cylinder ball. Set them
in YAML:

| Option | Default | What it does |
|---|---|---|
| `egt_mode_switching` | off | Respond to the **Set EGT mode** actions. |
| `normalize_range` | unset | The span the bar covers in Normalize. |
| `highlight_key` | unset | A FIX key such as `EGTMAX1`; a ball is drawn while this bar's value equals it. |

See [Engine Monitoring](Engine-Monitoring#leaning-egt-modes).

---

## `horizontal_bar_gauge`

![Horizontal bar gauge](../images/horizontal_bar_gauge.png)
![Horizontal bar gauge, segmented](../images/horizontal_bar_gauge_segmented.png)

<!-- generated:horizontal_bar_gauge -->

**Horizontal Bar Gauge** · palette category `gauge`

How it reads and flies: [Engine Monitoring](Engine-Monitoring).

| Option | Configurator label | Default | Values | What it does |
|---|---|---|---|---|
| `dbkey` | FIX key | empty | FIX key | FIX-database key whose value this gauge displays |
| `name` | Name | empty |  | label drawn on the gauge (e.g. OIL P, CHT) |
| `decimal_places` | Decimal places | `1` |  | digits after the decimal point in the readout |
| `show_units` | Show units | on | on / off | append the FIX key's engineering units to the readout |
| `segments` | Segments | `0` |  | 0 = solid bar; >0 draws a segmented (LED-style) bar |

Values it reads from the FIX item, set in fix-gateway (the aircraft parameters), not on the panel:

| Value | From | Meaning |
|---|---|---|
| `Min` | min | Range minimum |
| `Max` | max | Range maximum |
| `lowAlarm` | aux | Low alarm (red) |
| `lowWarn` | aux | Low warning (yellow) |
| `highWarn` | aux | High warning (yellow) |
| `highAlarm` | aux | High alarm (red) |

<!-- /generated -->

A limit of exactly 0 is not drawn on a horizontal bar.

---

## `numeric_display`

![Numeric display](../images/numeric_display.png)

<!-- generated:numeric_display -->

**Numeric Display** · palette category `text`

How it reads and flies: [Engine Monitoring](Engine-Monitoring).

| Option | Configurator label | Default | Values | What it does |
|---|---|---|---|---|
| `dbkey` | FIX key | empty | FIX key | FIX-database key whose value is displayed |
| `decimal_places` | Decimal places | `1` |  | digits after the decimal point in the readout |
| `font_mask` | Font mask | `000` |  | widest string the readout reserves space for (sizing) |
| `show_units` | Show units | off | on / off | append the FIX key's engineering units to the readout |

Values it reads from the FIX item, set in fix-gateway (the aircraft parameters), not on the panel:

| Value | From | Meaning |
|---|---|---|
| `Min` | min | Range minimum |
| `Max` | max | Range maximum |
| `lowAlarm` | aux | Low alarm (red) |
| `lowWarn` | aux | Low warning (yellow) |
| `highWarn` | aux | High warning (yellow) |
| `highAlarm` | aux | High alarm (red) |

<!-- /generated -->

It colours the value by the limits like the others, without a band. When it is
selected for editing it shows the cyan ring and knob icon from
[The Panel at a Glance](The-Panel-at-a-Glance#touch-a-value-then-turn-the-knob);
the bar and arc gauges turn orange instead.

---

## Options every gauge takes in YAML

These are read by all four but are not in the configurator's list. Except
for the unit switches, pyEFIS applies them and logs that they are undeclared.

| Option | Default | What it does |
|---|---|---|
| `temperature: true`, `pressure: true` | off | Let the **Units** button switch this gauge between °C and °F, or inHg and hPa. |
| `altitude: true` | off | The same for ft and m, on `numeric_display` only. |
| `clipping` | off | Hold the value, and any edit, inside the item's range. |
| `encoder_set_key` | the `dbkey` | The FIX key the knob edits. |
| `encoder_multiplier` | 1 | Inner-knob step. |
| `encoder_coarse_multiplier` | 10 | Outer ring step, as a multiple of the inner. |
| `encoder_set_real_time` | off | Write each step at once, rather than on the push. |
| `touch_edit` | off | Select it by touch as well as with the knob. |
| `encoder_order` | unset | Its place in the knob's order. |

Selected and turned, a gauge changes its value; a push keeps it; leaving it
until the knob times out puts the old value back.

---

## Ganged gauges

Prefix a gauge type with `ganged_` to repeat it across groups: this is how the
stock screens build their cylinder rows. `gang_type` is required.
`common_options` apply to every member of a group, and a member's own `options:`
override them.

```yaml
- type: ganged_vertical_bar_gauge
  gang_type: horizontal       # required: horizontal or vertical
  row: 8
  column: 1
  span: {rows: 5, columns: 27}
  groups:
    - name: EGT
      common_options:
        egt_mode_switching: true
        normalize_range: 400
      instruments:
        - {options: {name: "1", dbkey: EGT11, show_units: false}}
        - {options: {name: "2", dbkey: EGT12, show_units: false}}
        - {options: {name: "3", dbkey: EGT13, show_units: false}}
        - {options: {name: "4", dbkey: EGT14, show_units: false}}
```

In the configurator, use the palette's cylinder groups instead. The rules for
groups, gaps and `disabled` are on
[Screen Builder](Screen-Builder#ganged-instruments).
