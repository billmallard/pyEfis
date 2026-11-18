# Data Status, Updates and Notices

The device keeps its navigation data (airports, navaids, procedures, obstacles,
terrain, water, roads) in signed packs from the navdata service,
[navdata.aerocommons.org](https://navdata.aerocommons.org). The `pyefis-data`
updater installs them and records their state. pyEFIS shows that state in three
places: the **Data Status** screen, the **DATA** flag, and the **About**
screen. This page also covers the software notice shown at start-up.

Data Status and About are always one swipe away: the
[system menu](The-Panel-at-a-Glance#the-system-menu) opens either from any
screen, and brings you back to that screen afterwards.

How packs are built, signed and verified is in the makerplane-data wiki:
[Navigation Data Currency](https://github.com/billmallard/makerplane-data/wiki/Navigation-Data-Currency).
Installing `pyefis-data` and its daily timer is on
[Setting Up a Device](Setting-Up-a-Device#6-install-navigation-data).

## The Data Status screen

![The Data Status screen on the bench (an October capture): NAVIGATION DATA with the catalog date, one row per installed pack with its status and cycle, all current in green, and the Continue, About and Update buttons](../images/about/bench_beelink_datastatus.png)

One row per installed pack: its name, its status, and a detail such as the
cycle and its effective dates. The row's colour is the updater's verdict:

| Colour | Means |
|---|---|
| Green | Current. |
| White | Expiring soon, or missing. |
| Amber | Expired, or outside its effective window. |

The words in each row come from the updater as it wrote them; pyEFIS only
colours them. Two exceptions keep the list on one screen:

- Terrain comes as one pack per region, and two or more of them share one row,
  `Terrain (N regions)`. When every region is current the row reads as they do.
  Otherwise it takes the worst region's colour and status, and the detail names
  each region that is not current.
- A detail too long for its column is shortened to the cycle and its expiry,
  such as `2611 to 2026-11-26`, adding `, next 2612 staged` when that fits too.

`Data status unavailable — run an update to populate it.` means the updater has
not written a status yet.

### After a panel change

When a config pull installs a new panel, an amber banner opens the screen:
`PANEL CHANGED AT BOOT` (or `PANEL CHANGED` when the pull was run by hand), the
config version and when it was installed, the start of its hash, and *Check
every instrument shows the right source before flight.* Check the panel, then
touch **Acknowledge** on the banner. The banner stays until you do; **Continue**
works either way.

The acknowledgement is recorded by `pyefis-data panel-ack`, for the exact
config shown. If another pull has installed a newer config in the meantime,
the record is refused and the banner shows the newer change: *A newer panel
change was installed. Check it, then acknowledge again.*

| Button | What it does |
|---|---|
| **Continue** | Go to the panel's flight screen, the one marked as the default. When the system menu opened Data Status, go back to the screen it was opened from. |
| **About** | Open the About screen. |
| **Update** | Check for and install newer packs. |

**How you get here.** On the ground, pyEFIS starts on this screen, so you see
the state of your data as part of a normal start. Touch **Continue** for the
flight screen. Later, touch the DATA flag where a screen carries one.

pyEFIS starts here only when it knows the aircraft is on the ground: airspeed
is valid and below the aircraft's on-ground IAS limit (`IAS.Vgnd`, the
configurator's "on-ground IAS limit", 40 kt by default), and a valid GPS
groundspeed is below the same figure. In every other case it starts on the
flight screen, because pyEFIS can restart in flight:

- airspeed at or above the limit, or GPS groundspeed at or above it (a blocked
  pitot reads slow);
- airspeed flagged bad, failed or old, or no valid airspeed within 3 seconds
  of start;
- the limit not set for this aircraft.

While this screen is up after a ground start, airspeed or groundspeed reaching
the limit switches to the flight screen by itself, so a takeoff never waits on
**Continue**. Otherwise it stays until you touch **Continue**. A panel that
names this screen as its default uses the screen behind Continue as its flight
screen.

### Updating

Updating needs an internet connection or a USB drive with packs on it. Do it on
the ground.

1. Touch **Update**. pyEFIS asks the updater what sources it can see. With
   neither a connection nor a USB drive it says so, and nothing changes.
2. A list of packs opens, grouped as Navigation Data, Water, Roads, Terrain and
   Charts, with each pack's size and status. The packs already installed are
   ticked. The footer shows the total size, flagged if it exceeds the free
   space. **Use** switches source and **Change** picks the storage drive.
3. Touch **Install selected**. A progress bar shows each pack in turn.
   **Cancel** stops the install and goes back to the list.
4. If the data needs you to accept a notice first, it is shown with **Accept**
   and **Decline**. Decline installs nothing.
5. `Update complete.`, or `Update finished with problems — your previous data is
   still in place.` with the rows showing which pack failed. A pack that fails
   leaves the previous one in use.

The screen re-reads the status every minute and each time it is shown.

## The DATA flag

A small `DATA` outline, on screens that carry the **Data Annunciation**
instrument. It is hidden while every pack is current, white when one is
expiring soon or missing, and amber when one has expired or a
[panel change](#after-a-panel-change) is waiting to be acknowledged. Touch it to
open Data Status.

The bench panel does not carry it. Add it from the configurator palette's
system category.

## The About screen

![About on the bench (an October capture): About pyEfis, the version, the software notice, and the installed data packs with their cycles](../images/about/bench_beelink_about.png)

- The pyEFIS version and the software notice.
- **Safety advisories**, directly under the version, when the updater has
  any for this device. Each shows its severity (`WARNING` in red, `CAUTION` in
  amber, `ADVISORY` in white) and title, its id and date, a description, and
  `Required action:`. Advisories that apply are listed first, then by
  severity. One the device cannot match against an installed version says
  `May apply to this device`. With none, the section is not shown at all. If
  you have not turned the advisory feed on, a grey `Safety advisories: off`
  line shows instead. When the last verified feed is more than 28 days old,
  or there has never been one, a grey line says so.
- **Installed data packs:** each pack with its cycle and any notice its
  publisher attached.
- **Notice acknowledgments:** each time the software notice was accepted on
  this device, newest first: when, by whom, how (typed at a terminal, accepted
  on screen, or auto-accepted on a bench unit, which is marked as not a
  person's accept), and the versions it covered.

**Back** returns to Data Status, or, when the system menu opened About, to the
screen you opened it from. pyEFIS adds the About screen to every
configuration, and the Data Status screen's **About** button and the system
menu open it.

## The software notice at start-up

![The notice strip across the bottom of the bench panel, 7 seconds after start, on a bench where the notice has been accepted](../images/aer4339_startup_notice/beelink_banner_8s.png)

Each start, a strip across the bottom reads: *"pyEfis is experimental software
for Experimental / Amateur-Built aircraft. It is not certified. It is provided
as-is with no warranty, and any use of it is at your own risk."*

- It needs no tap. Touches go through it to the instruments underneath.
- It clears after **8 seconds** once the notice has been accepted for this
  pyEFIS version, and after **20 seconds** if not.
- The acceptance is a record in
  `~/.local/state/makerplane/acknowledgments.jsonl` (or
  `$XDG_STATE_HOME/makerplane/`, or the file named by `$MAKERPLANE_ACK_LOG`).
  pyEFIS reads it and never writes it.

**Accepting.** Run `pyefis-accept-notice` at a terminal on the device. It shows
the notice through `pyefis-data` and asks you to type `accept`; it exits 0 when
accepted. `pyefis-accept-notice --check` only reports. Accepting a data notice
during an update does not shorten the start-up strip, because that record names
the updater's version, not pyEFIS's. See
[Setting Up a Device](Setting-Up-a-Device#2-accept-the-software-notice).

## Customizing

None of the three screens has options in the configurator; pyEFIS adds Data
Status and About to every panel. By hand:

| Instrument | Option | Default | What it does |
|---|---|---|---|
| Data Status (`data_status`) | `update_command` | `pyefis-data` | The updater Update runs. The shipped screen uses `~/.local/bin/pyefis-data`. |
| | `continue_screen` | the boot screen | Where Continue goes. |
| | `about_screen` | `About` | Where About goes. |
| | `status_path` | `~/.makerplane/pyefis/status.json` | The updater's status file. |
| Data Annunciation (`data_annunciation`) | `target_screen` | `DataStatus` | Where a touch goes. |
| | `status_path` | as above | |
| About (`about`) | `back_screen` | `DataStatus` | Where Back goes. |

## See also

- [Setting Up a Device](Setting-Up-a-Device)
- [How the System Fits Together](How-the-System-Fits-Together)
