# Publishing the manual to the GitHub wiki

The pyEFIS manual is authored in this repo under **`docs/wiki/`** (the canonical
source) and **mirrored** to the GitHub wiki. This keeps the docs version-
controlled alongside the code and reviewable in PRs, while still presenting them
as a browsable wiki.

## Layout

```
docs/wiki/            one .md per wiki page (GitHub-wiki naming, hyphenated)
  Home.md             wiki landing page
  _Sidebar.md         wiki navigation
  Concepts.md, Widgets-*.md, Screens-*.md, Pilots-Guide.md, ...
docs/images/          shared images (referenced as ../images/NAME.png)
.github/workflows/wiki-sync.yml   publishes the wiki on every merge to dev
tools/sync_wiki.sh    local preview of the mirror (does not push)
```

**Authoring rules** (so the mirror is lossless):
- One page per file; the filename (minus `.md`) is the wiki page name.
- Link between pages **without** the extension: `[Concepts](Concepts)`.
  (These resolve in the wiki. In the repo file view they are not clickable,
  which is acceptable — the repo copy is the source, the wiki is the rendered
  product.)
- Reference images as `../images/NAME.png` (a subdirectory is fine:
  `../images/nav_status/NAME.png`). The mirror publishes each referenced
  `docs/images/` file to the wiki and rewrites the path to `images/NAME.png`.
- `Home.md`, `_Sidebar.md`, `_Footer.md` are GitHub-wiki special pages.

## Mirroring

The GitHub wiki is a separate git repo: `git@github.com:billmallard/pyEfis.wiki.git`
(HTTPS: `https://github.com/billmallard/pyEfis.wiki.git`).

**Publishing is automatic.** `.github/workflows/wiki-sync.yml` runs on every push
to `dev` that touches `docs/wiki/`, `docs/images/` or the workflow itself, and on
demand (Actions tab, *wiki-sync*, *Run workflow*). It stages the pages with the
rewrites above, adds the images they reference, and mirrors the result onto the
wiki with `rsync --delete`. Renaming or deleting a page here renames or deletes it
on the wiki, and **direct wiki edits are overwritten** on the next run. Review
happens in the PR that changes `docs/wiki/`. The job runs only in
`billmallard/pyEfis`, so it never publishes upstream's wiki.

The workflow pushes with the built-in `GITHUB_TOKEN`. If a run fails with 403 on
push, that token cannot write the wiki: add a `WIKI_TOKEN` repository secret (a
fine-grained token with Contents read/write on this repo) and re-run.

To preview the mirror locally without publishing:

```bash
# from the pyEfis repo root
tools/sync_wiki.sh                       # clones/updates ../pyEfis.wiki, copies pages+images
cd ../pyEfis.wiki && git diff            # review; do not push -- the workflow publishes
```

`tools/sync_wiki.sh` copies only the top-level `docs/images/` files and never
deletes, so its preview can differ slightly from what the workflow publishes.
