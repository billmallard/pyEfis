# PA12 Charts page (pyEfis #241, AER-1611)

Renders of the real `flight_plan` widget, drawn by its own paint path
offscreen at the Beelink's Flight Plan tab size (649 x 993 px on its 21.5 in
1920 x 1080 panel, `font_percent: 0.8`). They were produced **on the
Beelink**, 2026-11-16, from a scratch clone of `aer-1611/pa12-plate-viewer`
@ `00baa327` under `~/bench-scratch/aer-1611`, with the bench's own
`~/pyefis-venv` (PyQt6 6.8, Qt PDF included) and fonts. The live display,
its checkout and its config were not touched.

- **Procedures:** the bench's installed pack,
  `/data/makerplane-data/procedures/current/procedures.sqlite`, AIRAC 2611.
  The route is RZS then KSBA, with the ILS RWY 7 (`I07`) loaded through the
  real PROC page calls, transition VECTORS. The engine is played by hand: a
  commit is accepted by writing `FPLLDSEQ`.
- **Plates:** a KSBA-only `plates` pack built by makerplane-data's own PA11
  builder (`packtools.build.plates.build_plates`, makerplane-data `dev` @
  `5c27da4`) from the real d-TPP cycle 2611 metafile and the 16 KSBA PDFs
  fetched from `https://aeronav.faa.gov/d-tpp/2611/`. No plates pack is
  published to R2 yet, so this is a local build. Georeferencing was not
  attempted (`fix_index=None`), so the pack has no `plate_georef` rows, and
  the page draws no ownship in any case.

| File | State |
|---|---|
| `1_fpl_charts_key.png` | the FPL page with the approach loaded, and the CHARTS soft key |
| `2_plate.png` | one tap on CHARTS: ILS OR LOC RWY 07, fitted to the pane, AMDT 7, AIRAC 2611 |
| `3_zoomed.png` | ZOOM + twice (2x), centred on the plan view's IAF at GAVIOTA |
| `4_list.png` | LIST: KSBA's 16 charts, the airport diagram first (CAP-207); the down arrow pages on |
| `5_diagram.png` | the airport diagram, tapped from the list |
| `sheet.png` | all five side by side at 1:1 |

To regenerate:

```bash
# makerplane-data checkout: build the pack from the live cycle.
curl -O https://aeronav.faa.gov/d-tpp/2611/xml_data/d-TPP_Metafile.xml
# ...fetch each KSBA pdf_name the metafile lists from https://aeronav.faa.gov/d-tpp/2611/
python3 -c "
from packtools.dtpp import parse_metafile
from packtools.build.plates import build_plates
recs = [r for r in parse_metafile('d-TPP_Metafile.xml') if r.icao_ident == 'KSBA']
build_plates(recs, '.', 'plates-ksba-2611.sqlite', cycle='2611', fix_index=None)"

# pyEfis checkout:
QT_QPA_PLATFORM=offscreen PYTHONPATH=src python3 tools/render_charts_page.py OUTDIR \
    --procedures /data/makerplane-data/procedures/current/procedures.sqlite \
    --plates plates-ksba-2611.sqlite
```

The charts are FAA d-TPP products, a work of the US Government.
