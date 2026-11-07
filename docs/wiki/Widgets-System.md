# System & Containers

The navdata status screens, the About screen, the tab section and the embedded
Android panel. Each table is generated from pyEFIS's instrument registry; see
[Widget Reference](Widget-Reference#how-to-read-these-pages).

| `type:` | What it is |
|---|---|
| `tab_section` | Several pages in one area of a screen, with a tab bar. |
| `data_status` | The full-screen navdata status and updater. |
| `data_annunciation` | The small `DATA` flag. |
| `about` | The About screen. |
| `weston` | An Android app (under waydroid) in a screen region. |

---

## `tab_section`

<!-- generated:tab_section -->

**Tab Section** · palette category `container`

How it reads and flies: [The Panel at a Glance](The-Panel-at-a-Glance#the-tab-column).

| Option | Configurator label | Default | Values | What it does |
|---|---|---|---|---|
| `default_tab` | Default tab | `0` | 0 to ... | tab index shown on screen load/power-up -- always this fixed tab, never the last one selected |
| `tab_position` | Tab bar edge | `top` | `top`, `bottom`, `left`, `right` | which edge of the container the tab bar sits on; left/right also rotate the tab labels |
| `fg_color` | Tab bar foreground | unset | colour | tab label colour; unset inherits the screen's legible default |
| `bg_color` | Tab bar background | unset | colour | tab bar fill colour; unset inherits the screen's legible default |

Holds `tabs:` (Tabs): ordered list of {label, layout, instruments} tab pages; each tab is built as its own nested screen (same layout+instruments shape as a top-level screen) laid out against this container's own box, not the screen's

<!-- /generated -->

Each tab is `{label, layout, instruments}`, laid out against the section's own
box with its own grid. Only touch changes tabs. A tab section cannot hold
another, and the panel always opens on `default_tab`.

```yaml
- type: tab_section
  row: 0
  column: 130.5
  span: {rows: 110, columns: 69}
  options:
    tab_position: top
  tabs:
    - label: Map
      layout: {rows: 110, columns: 200}
      instruments:
        - type: moving_map
          row: 0
          column: 2
          span: {rows: 106, columns: 196}
    - label: Engine
      layout: {rows: 110, columns: 200}
      instruments: []
```

---

## The navigation-data status file

`data_status`, `data_annunciation` and `about` read the file the `pyefis-data`
updater writes, by default `~/.makerplane/pyefis/status.json`. pyEFIS never
writes it. A missing or unreadable file gives an "unavailable" state, never an
error, so the status display cannot stop the panel starting.

The fields pyEFIS uses:

- `ok`: when false or missing, the data is treated as unavailable.
- `generated`: the catalog date, shown as `catalog YYYY-MM-DD`.
- `packs`: one entry per installed pack, with `id`, `name`, `severity`,
  `status` and `detail`; `About` also shows `cycle` and `notice`.

| `severity` | Colour | Means |
|---|---|---|
| `none` | green | Current. |
| `white` | off-white | Expiring soon, or missing. |
| `amber` | amber | Expired, or outside its window. |

The worst pack decides the `DATA` flag.

---

## `data_status`

<!-- generated:data_status -->

**Data Status** · palette category `system` · hidden from the palette, still loads in existing panels

How it reads and flies: [Data Status, Updates and Notices](Data-Status-Updates-and-Notices).

No options in the configurator beyond the ones every instrument takes.

<!-- /generated -->

pyEFIS adds this screen to every configuration that lacks it, and never boots
to it: a panel whose default screen is Data Status, or is not loaded, boots to
the Continue target or the first other screen instead. At start-up Continue is
pointed at the panel's default screen. Its options are set in YAML:

| Option | Default | What it does |
|---|---|---|
| `update_command` | `pyefis-data` | The updater **Update** runs; `~` is expanded. The shipped screen uses `~/.local/bin/pyefis-data`. |
| `continue_screen` | the default screen | Where **Continue** goes. |
| `about_screen` | `About` | Where **About** goes. |
| `status_path` | `~/.makerplane/pyefis/status.json` | The status file. |

The update flow, the notice prompt and the progress screen are described on
[Data Status, Updates and Notices](Data-Status-Updates-and-Notices#updating).
Behind it, **Update** runs the updater's `sources --json`, `catalog --json` and
`update --only <ids> --progress` (with `--source` and `--root` when chosen),
and re-runs with `--accept-notice` when you accept a data notice.

---

## `data_annunciation`

<!-- generated:data_annunciation -->

**Data Annunciation** · palette category `system`

How it reads and flies: [Data Status, Updates and Notices](Data-Status-Updates-and-Notices#the-data-flag).

No options in the configurator beyond the ones every instrument takes.

<!-- /generated -->

Hidden while every pack is current; white or amber otherwise. A touch shows
`target_screen` (`DataStatus` by default). It also takes `status_path`.

```yaml
- type: data_annunciation
  row: 2
  column: 2
  span: {rows: 5, columns: 18}
```

---

## `about`

<!-- generated:about -->

**About / System** · palette category `system` · hidden from the palette, still loads in existing panels

How it reads and flies: [Data Status, Updates and Notices](Data-Status-Updates-and-Notices#the-about-screen).

| Option | Configurator label | Default | Values | What it does |
|---|---|---|---|---|
| `back_screen` | Back screen | `DataStatus` |  | screen the Back button returns to |

<!-- /generated -->

pyEFIS adds the About screen to every configuration that lacks it. It also
takes `status_path` and `ack_path` (the acknowledgment record, by default
`~/.local/state/makerplane/acknowledgments.jsonl`).

---

## `weston`

`weston` runs the Weston compositor with its X11 backend and embeds its window
in a screen region, so an Android app running under waydroid can show beside
the instruments. It runs only on Linux with X11.

<!-- generated:weston -->

**Weston** · palette category `system`

| Option | Configurator label | Default | Values | What it does |
|---|---|---|---|---|
| `socket` | Wayland socket | unset |  | weston -S socket name |
| `ini` | weston.ini | unset |  | path (under the config dir) to weston.ini |
| `command` | Command | unset |  | program to launch inside the compositor |
| `args` | Arguments | unset |  | arguments passed to the command |

<!-- /generated -->

```yaml
- type: weston
  row: 0
  column: 0
  span: {rows: 100, columns: 155}
  options:
    socket: pyefis-waydroid-1
    ini: weston.ini
    command: waydroid
    args: [show-full-ui]
```

- `ini` is relative to the main configuration directory; the shipped file is
  `config/weston.ini`.
- The compositor starts full-screen at the region's size in pixels, worked out
  from the span.
- `command` and `args` must be present, but the widget does not start the app;
  start it some other way on the device.
- After starting Weston it looks for the "Weston Compositor" window about 15
  times, 70 ms apart. If it never appears, nothing is embedded.
- Closing the screen stops Weston.
- It reads no FIX keys and is not on the knob.
