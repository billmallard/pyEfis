# Test evidence page

Every CI run of pyEfis and fix-gateway keeps its results, and a static page is built
from them (TV11, `testing_visibility_plan.md` section 7). The page is evidence, not a
warranty and not a certification; its standing text says so at the top.

## What CI keeps

The `build` job in `.github/workflows/ci.yml`, in both repositories:

1. runs pytest with `--junitxml=reports/junit.xml -o junit_family=xunit1`;
2. turns that into `reports/verification.json` with `tools/verification_report.py collect`;
3. writes a job summary from the JSON: the tests that cite a requirement ID, the
   strict-xfail gap trackers, and any failing test;
4. uploads both files as the `test-results` artifact, kept 90 days.

These steps run even when tests fail, so a red run keeps its record too.

## The page

The `evidence-page` job (pyEfis only) takes this run's record and fix-gateway's latest
`dev` record, renders `index.html` with `tools/verification_report.py page`, and deploys
it to the Cloudflare Pages project `avionics-test-evidence`. `dev` is the production
branch; any other branch or PR gets its own preview URL. It deploys
with the repo's `CLOUDFLARE_API_TOKEN` (the token `editor-assets.yml` uses, which also
carries Account > Cloudflare Pages > Edit) and `CLOUDFLARE_ACCOUNT_ID`. On a `dev` push
the job also attaches `testing.aerocommons.org` to the project (Bill's D1 pick) and
prints the domain's status. The token has no DNS rights, by design: the one DNS record
for that name is made once, outside CI. Without that token (a fork's PR, for example) the
page is built and kept as the `evidence-page` artifact but not deployed. The first
deploy creates the project.

Sections:

- **Requirements**: every requirement ID defined in `docs/requirements.md` or a
  `docs/*_spec.md` table, and every ID a test docstring cites, with links to those tests
  at the exact commit and their last result. A defined requirement that no test cites
  is listed as such.
- **Deviation register**: the `xfail(strict=True)` tests, each a known, self-closing
  gap (see `instrument_verification_status.md`).
- **Tested where** and **Simulator runs**: empty until the "Tested on my hardware"
  issue form and the simulator CI tier exist. The empty state says so.
- **Every test**, grouped by file.

The same job also renders `evidence.html`, an index of every committed evidence image
and what its sidecar says about it (commit, run, device), with
`tools/evidence_index.py` (TV12). The convention is in `evidence.md`.

## Releases

Each push to `master` (a `qa -> master` promotion) runs the `release` job: a GitHub
Release tagged `promotion-<sha7>`, with that commit's job summary as its notes and
`verification.json`, `junit.xml` and the rendered site (`evidence-site.zip`) attached.
A red promotion is released as a pre-release that says so. Details in `evidence.md`.

A test joins the requirements table by naming the ID in its docstring, as the
instrument catalogues already do (`"""AI-TC-102 | AI-BANK-001 | ..."""`). `-TC-` IDs
are catalogue entries, not requirements.

## Hygiene

Text from a run (failure messages, docstrings, xfail reasons) passes through
`sanitize()`, which removes local paths, IP addresses, `user@host` and private
hostnames, and drops links to hosts outside a short public allowlist. `page` refuses to
write a site that still contains any of these. The page never calls a result verified,
certified, approved, safe, compliant or airworthy; `tests/tools/test_verification_report.py`
checks its wording.

## Run it locally

```bash
pytest --junitxml=reports/junit.xml -o junit_family=xunit1
python tools/verification_report.py collect --junit reports/junit.xml --tests tests \
    --docs docs --repo billmallard/pyEfis --sha "$(git rev-parse HEAD)" --ref local \
    --out reports/verification.json
python tools/verification_report.py summary reports/verification.json
python tools/verification_report.py page reports/verification.json --out site
```
