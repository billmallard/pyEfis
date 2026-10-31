# AER-4347 (TV12) evidence: the generated evidence index

| File | What it shows |
|---|---|
| `index_top.png` | The top of `evidence.html` as `tools/evidence_index.py --html` renders it for commit `29883f8`: the standing text, the counts (36 directories, 93 images, 0 with a current sidecar, 5 with an older one) and the start of the directory table. 1:1, 1200 px wide. |
| `index_older_sidecars.png` | An excerpt of the per-image sections for AER-1806 and AER-1973, whose PNGs carry `svs_capture.py` sidecars from before this convention: listed as "older sidecar", with the commit and command they do carry and no device. The local path in the AER-1973 command shows as `<path>`: the sanitizer at work. Thumbnails were served from local copies for the capture; the published page loads them from `raw.githubusercontent.com` pinned to the commit. |

Each PNG has a sidecar (`*.png.json`) in the TV12 convention, written with
`tools/evidence_sidecar.py`, so this directory is listed with "sidecar" rows on the
index built from any later commit.

The capture was made in an agent sandbox with Playwright's `chrome-headless-shell`
(DejaVu fonts through a scratch `fonts.conf`). It is a picture of the HTML, not of a
deployed site; the deployed page is whatever the `evidence-page` CI job publishes.

Regenerate:

```sh
python tools/evidence_index.py --html out/evidence.html --repo billmallard/pyEfis --sha "$(git rev-parse HEAD)"
chrome-headless-shell --no-sandbox --disable-gpu --window-size=1200,1150 \
    --screenshot=index_top.png file://$PWD/out/evidence.html
```
