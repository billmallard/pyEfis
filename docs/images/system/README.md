# Images for the Start-here pages

Captured 2026-11-07 for Home, How the System Fits Together, Setting Up a Device
and Designing Your Panel. Headless Chromium (Playwright 1.62.1), 1366x900 for
the navdata site and 1440x900 for the configurator.

| File | What it shows | Source |
|---|---|---|
| `navdata_home.png` | navdata.aerocommons.org, the pack catalog | The live public site, top of the page. |
| `configurator_dashboard.png` | The dashboard with a project open, one device, and a pairing code | The configurator's own `public/index.html` (makerplane-data `dev` 6abc9d4) with `/api/*` answered locally. |
| `configurator_editor.png` | The Panel Editor with a full-width synthetic-vision panel | `public/editor.html`, the same way, loading the panel design the simulator bench runs. |
| `configurator_aircraft.png` | Aircraft parameters with the Cessna 170B template loaded | `public/aircraft.html`, the same way. |

The configurator pages are the real, unmodified pages. Only the account API is
answered locally, with an example project ("Example aircraft"), an example
user name and an example claim code, so no real account, email address or
token appears. The editor's instrument catalog and previews are fetched from
the dev configurator, `https://pyefis-dev.aerocommons.org/assets/editor/`. This
is the approach of makerplane-data's `configurator/tools/zoom_rail_capture.mjs`.

To regenerate: serve `configurator/public/` and route `/api/*` the same way
(`/api/me`, `/api/projects`, `/api/projects/1`, `/api/devices/1/pair`,
`/api/devices/1/config`), then open `/`, `/editor?device=1&project=1` and
`/aircraft?project=1`, choosing `c170b` in **Load template**. The pairing
image is the dashboard after **Open** and **Re-pair**, cropped to the
project card.
