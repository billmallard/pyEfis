# Evidence images and their sidecars

When a change is judged by how something looks, the screenshots and renders that
justified it are committed beside the code, one directory per issue, with a README
saying what each image shows and how to make it again (TV12):

- `docs/images/aer<NNNN>_<topic>/` (most of them), or
- `docs/aer-<NNNN>-evidence/`.

`tools/evidence_index.py` lists every such directory and image. CI renders that list as
`evidence.html` on the test-evidence site, beside the test results (see
`test_evidence.md`). Run it locally with `python tools/evidence_index.py --markdown`.

## The sidecar

Every new evidence image gets a sidecar: `<image>.json` in the same directory
(`shot.png` -> `shot.png.json`). It names the three things a reviewer otherwise has to
dig out of a commit message:

| Key | What it holds |
|---|---|
| `commit` | The pyEfis commit that drew the image. `-dirty` if it was drawn from uncommitted changes. |
| `run` | The run that produced it: a CI run URL, a bench session (`AER-1234 bench session, Pi 5`), or the exact command (`local: tools/render_x.py out/`). |
| `device` | What drew it: the board and Qt platform (`Raspberry Pi 5 Model B Rev 1.0 (eglfs)`, `GitHub Actions Linux runner (offscreen)`). Never a hostname or address. |
| `sha256` | The image's hash, so a sidecar left behind by an earlier run is caught. |
| `schema` | `evidence-sidecar/1`. |
| `created_utc` | When the sidecar was written. |

`commit`, `run` and `device` are required. A producer may add its own keys;
`tools/svs_capture.py` adds `capture_mode`, `requested_size`, `actual_size` and `argv`.

### Writing one

From a render script, after the image is saved:

```python
from evidence_sidecar import write_sidecar   # tools/ is on sys.path
write_sidecar(out_png)   # commit, run and device resolved from this checkout and machine
```

Set `EVIDENCE_RUN` to name the run (`EVIDENCE_RUN="AER-1234 bench session"`) when
the command line alone would not say enough; in CI the run URL is used.
`tools/svs_capture.py` writes one for every frame.

For an image made by hand (a live-panel photo, a screenshot off the bench), after the
fact, where only the person who made it knows the answers:

```bash
python tools/evidence_sidecar.py docs/images/aer1234_x/live.png --commit 1e7db42 \
    --run "AER-1234 bench session, SIGUSR1 screenshot" --device "Beelink bench (xcb)"
```

### What CI checks

`tests/tools/test_evidence_index.py` fails if a committed sidecar is broken: its hash
does not match the image beside it, a required key is missing, or it is not valid
JSON. A missing sidecar is not a failure; evidence from before this convention has
none, and the index lists those images as "no sidecar" rather than guessing. An older
`svs_capture.py` sidecar (only `pyefis_rev`) is listed as "older sidecar", with the
commit and command it does carry.

## Releases

Each `qa -> master` promotion gets a GitHub Release, tagged `promotion-<sha7>`, made by
the `release` job in `.github/workflows/ci.yml`. Its notes are that commit's test
report (the same Markdown as the CI job summary); its assets are `verification.json`,
`junit.xml` and `evidence-site.zip`, the test-evidence page and this index as rendered
for that commit. A promotion whose tests failed still gets a release, marked as a
pre-release with a line saying the run did not pass.
