# Qt PDF on the Pi 5 (AER-5813)

The Charts page drawn **on the Pi 5** (`wpballard@10.110.10.199`), 2026-11-16,
by the service's own interpreter, `~/pyEfis/.venv/bin/python`. That venv uses
Debian's PyQt6 6.9.0 through `--system-site-packages`, with
`python3-pyqt6.qtpdf` 6.9.0-2 newly installed. Before the install,
`import PyQt6.QtPdf` failed there with `ModuleNotFoundError`.

These are offscreen renders (`QT_QPA_PLATFORM=offscreen`). The Pi has no
screenshot of its eglfs display. They show the module renders plates on the
Pi's arm64 Qt build. The live glass is checked by eye.

- `2_plate.png`: one tap on CHARTS, ILS OR LOC RWY 07 at KSBA, AIRAC 2611.
- `4_list.png`: LIST, KSBA's 16 charts.

pyEfis was `aer-1611/pa12-plate-viewer` @ `0a98dbb9` (pyEfis #492), staged
with `bench-deploy.sh --bench pi5 --ref`.

To regenerate, on the Pi:

```bash
# KSBA-only plates pack, built with makerplane-data's PA11 builder
# (~/src/makerplane-data @ 761c8f8) from the d-TPP 2611 cycle.
W=~/bench-scratch/aer-5813; mkdir -p $W; cd $W
curl -sfO https://aeronav.faa.gov/d-tpp/2611/xml_data/d-TPP_Metafile.xml
PYTHONPATH=~/src/makerplane-data python3 -c "
import urllib.request, os
from packtools.dtpp import parse_metafile
from packtools.build.plates import build_plates
recs = [r for r in parse_metafile('d-TPP_Metafile.xml') if r.icao_ident == 'KSBA']
for r in recs:
    if not os.path.exists(r.pdf_name):
        urllib.request.urlretrieve('https://aeronav.faa.gov/d-tpp/2611/' + r.pdf_name, r.pdf_name)
build_plates(recs, '.', 'plates-ksba-2611.sqlite', cycle='2611', fix_index=None)"

cd ~/pyEfis   # on aer-1611/pa12-plate-viewer
QT_QPA_PLATFORM=offscreen PYTHONPATH=src ~/pyEfis/.venv/bin/python \
    tools/render_charts_page.py ~/bench-scratch/aer-5813/out \
    --procedures /data/makerplane-data/procedures/current/procedures.sqlite \
    --plates ~/bench-scratch/aer-5813/plates-ksba-2611.sqlite
```

The charts are FAA d-TPP products, a work of the US Government.
