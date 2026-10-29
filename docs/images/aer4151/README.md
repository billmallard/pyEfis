# AER-4151 (TV11) evidence: the test-evidence page

- `page_top.png`: the top of the page, 1200x1500 viewport: standing text, sources,
  and the start of the requirements table.
- `page_register.png`: the same page with the requirements table and the per-test list
  cut out, to show the deviation register and the two empty states.

Both are rendered from the records the PR's CI uploaded (`test-results` artifacts of
pyEfis run 40889380448 and fix-gateway run 40889384958), with the generator at this
commit. The page CI deployed differs only in the colour of the "not run in this CI"
state, fixed in the same commit as these images.

```bash
gh run download 40889380448 -R billmallard/pyEfis -n evidence-page -D py
gh run download 40889384958 -R billmallard/fix-gateway -n test-results -D fgw
python tools/verification_report.py page py/pyEfis.json fgw/verification.json \
    --expect pyEfis fix-gateway --out site
chrome-headless-shell --hide-scrollbars --window-size=1200,1500 \
    --screenshot=page_top.png file://$PWD/site/index.html
# page_register.png: the same, on a copy of index.html with the
# <h2 id=requirements> .. <h2 id=deviations> and <h2 id=tests> .. footer spans removed,
# window 1200x1100.
```
