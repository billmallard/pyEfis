# CERT18b: the safety pages on the test-evidence site

Rendered from this branch's `tools/verification_report.py` and `docs/safety/`, using the
latest successful `dev` CI records of pyEfis and fix-gateway (the `test-results` artifacts),
then screenshotted at 1200 px wide with Playwright's headless Chrome.

- `index.png`: the top of `index.html`. The link bar, the new "Hazard assessment and tool
  inventory" section, and Requirements rows carrying "cited in hazard rows PFD-n" back-links.
- `hazard_assessment.png`: `hazard_assessment.html`, the first 5200 px. Requirement IDs link
  to their Requirements rows; IDs the table does not list are underlined with dots.
- `tool_inventory.png`: `tool_inventory.html`, the first 4300 px.

To make them again:

```bash
gh run download <pyEfis dev CI run> -R billmallard/pyEfis -n test-results -D rec
gh run download <fix-gateway dev CI run> -R billmallard/fix-gateway -n test-results -D fgw
python tools/verification_report.py page rec/verification.json fgw/verification.json \
    --expect pyEfis fix-gateway --safety docs/safety --out site
chrome-headless-shell --no-sandbox --hide-scrollbars --window-size=1200,5200 \
    --screenshot=hazard_assessment.png file://$PWD/site/hazard_assessment.html
```
