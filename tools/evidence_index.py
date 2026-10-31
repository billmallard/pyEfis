#!/usr/bin/env python3
#  SPDX-License-Identifier: GPL-2.0-or-later
"""Generate an index of the committed evidence images (TV12).

pyEfis keeps the screenshots and renders that justified a change beside the code, one
directory per issue: ``docs/images/aer*`` and ``docs/aer-*-evidence``. This walks
those directories and lists, per directory, the issue it belongs to, its README title,
the commit that added it, and every image with what its sidecar says about it (commit,
run, device -- see ``tools/evidence_sidecar.py`` and ``docs/evidence.md``). Images
made before the sidecar convention are listed as such; nothing is inferred for them.

Nothing here is written by hand and nothing is committed: CI renders it onto the test
evidence site as ``evidence.html`` (``--html``); ``--markdown`` prints the same index for
a terminal or a PR. ``--check`` fails on a sidecar that is present but broken (stale
hash, a required key missing, unreadable) -- a missing sidecar is reported, not failed,
because older evidence predates the convention.

Standard library only. Shares ``sanitize``/``find_leaks`` with
``tools/verification_report.py``: titles and sidecar values reach a public page.

Usage:
    python tools/evidence_index.py --markdown
    python tools/evidence_index.py --check
    python tools/evidence_index.py --html site/evidence.html \
        --repo billmallard/pyEfis --sha "$GITHUB_SHA"
"""

import argparse
import datetime
import html
import pathlib
import re
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from evidence_sidecar import check_sidecar  # noqa: E402
from verification_report import CSS, STANDING_TEXT, find_leaks, sanitize  # noqa: E402

ROOT_GLOBS = ("docs/images/aer*", "docs/aer-*-evidence")
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif")
_KEY = re.compile(r"aer[-_]?(\d+)", re.I)

STATE_WORDS = {
    "ok": "sidecar",
    "none": "no sidecar",
    "legacy": "older sidecar",
    "incomplete": "sidecar missing a key",
    "stale": "sidecar does not match the image",
    "unreadable": "sidecar unreadable",
}
BROKEN = ("incomplete", "stale", "unreadable")


def _git(repo, *args):
    try:
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def _title(directory):
    mds = sorted(directory.glob("*.md"), key=lambda p: (p.name.lower() != "readme.md", p.name))
    for md in mds:
        for line in md.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("# "):
                return line[2:].replace("`", "").strip()
    return ""


def _issue_key(name):
    m = _KEY.search(name)
    return f"AER-{int(m.group(1))}" if m else ""


def _provenance(state, record):
    """(commit, run, device) as far as the sidecar says; '' where it says nothing."""
    if state in ("ok", "incomplete", "stale"):
        return record.get("commit", ""), record.get("run", ""), record.get("device", "")
    if state == "legacy":
        # svs_capture.py's sidecar before TV12: the checkout and the command, no device.
        return record.get("pyefis_rev", ""), record.get("argv", ""), ""
    return "", "", ""


def scan(repo):
    repo = pathlib.Path(repo)
    roots = [str(repo), str(repo.resolve())]
    dirs = sorted({d for g in ROOT_GLOBS for d in repo.glob(g) if d.is_dir()},
                  key=lambda d: (int(_KEY.search(d.name).group(1)) if _KEY.search(d.name) else 0, d.name))
    entries = []
    for d in dirs:
        rel = d.relative_to(repo).as_posix()
        added = _git(repo, "log", "--diff-filter=A", "--format=%h %as", "--", rel).splitlines()
        images = []
        for img in sorted(p for p in d.rglob("*") if p.suffix.lower() in IMAGE_SUFFIXES and p.is_file()):
            state, record = check_sidecar(img)
            commit, run, device = _provenance(state, record)
            images.append({
                "path": img.relative_to(repo).as_posix(),
                "state": state,
                "commit": sanitize(str(commit), roots),
                "run": sanitize(str(run), roots),
                "device": sanitize(str(device), roots),
            })
        entries.append({
            "dir": rel,
            "issue": _issue_key(d.name),
            "title": sanitize(_title(d), roots),
            "readme": next((p.relative_to(repo).as_posix() for p in sorted(d.glob("*.md"))), ""),
            "added": added[-1] if added else "",
            "images": images,
        })
    return entries


def counts(entries):
    imgs = [i for e in entries for i in e["images"]]
    return {"dirs": len(entries), "images": len(imgs),
            "ok": sum(1 for i in imgs if i["state"] == "ok"),
            "legacy": sum(1 for i in imgs if i["state"] == "legacy"),
            "broken": sum(1 for i in imgs if i["state"] in BROKEN)}


# --------------------------------------------------------------------------- markdown

def render_markdown(entries):
    c = counts(entries)
    out = ["# pyEfis evidence index", "",
           f"{c['dirs']} evidence directories, {c['images']} images, {c['ok']} with a current "
           f"sidecar. Generated by `tools/evidence_index.py`.", "",
           "| Issue | Directory | Title | Added | Images | Sidecars |", "|---|---|---|---|---|---|"]
    for e in entries:
        n_ok = sum(1 for i in e["images"] if i["state"] == "ok")
        out.append(f"| {e['issue'] or '-'} | `{e['dir']}` | {e['title'].replace('|', '/')} | "
                   f"{e['added'] or '-'} | {len(e['images'])} | {n_ok} |")
    broken = [(e, i) for e in entries for i in e["images"] if i["state"] in BROKEN]
    if broken:
        out += ["", "## Broken sidecars", ""]
        out += [f"- `{i['path']}`: {STATE_WORDS[i['state']]}" for _, i in broken]
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- html

def _e(text):
    return html.escape(text or "", quote=True)


def _blob(repo, sha, path, raw=False):
    if not (repo and sha):
        return ""
    if raw:
        return f"https://raw.githubusercontent.com/{repo}/{sha}/{path}"
    return f"https://github.com/{repo}/blob/{sha}/{path}"


def _commit_cell(repo, commit):
    sha = commit.split("-")[0]
    if repo and re.fullmatch(r"[0-9a-f]{7,40}", sha):
        return f'<a href="https://github.com/{_e(repo)}/commit/{_e(sha)}"><code>{_e(commit)}</code></a>'
    return f"<code>{_e(commit)}</code>" if commit else "-"


def _run_cell(run):
    if run.startswith("https://github.com/"):
        return f'<a href="{_e(run)}">CI run</a>'
    return f"<code>{_e(run)}</code>" if run else "-"


def render_html(entries, repo="", sha=""):
    c = counts(entries)
    gen = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    src = (f'<a href="https://github.com/{_e(repo)}/tree/{_e(sha)}/docs"><code>{_e(sha[:10])}</code></a>'
           if repo and sha else "this checkout")
    h = ["<!doctype html><html lang=en><head><meta charset=utf-8>",
         '<meta name=viewport content="width=device-width,initial-scale=1">',
         "<title>pyEfis evidence images</title>",
         f"<style>{CSS}img{{max-width:220px;max-height:140px;border:1px solid #d8dce3}}.nw{{white-space:nowrap}}</style>",
         "</head><body><main>",
         "<h1>pyEfis: evidence images</h1>",
         f"<p class=muted>Generated {_e(gen)} from the evidence directories in the repository at "
         f"{src}. Every row is read from the files; nothing here is written by hand. "
         'The test results are on the <a href="index.html">test evidence page</a>.</p>',
         f'<div class=notice id=standing-text><p>{_e(STANDING_TEXT)}</p></div>',
         "<h2 id=about>What this is</h2>",
         "<p>Each directory holds the screenshots and renders that were the evidence for one "
         "change, with a README saying what they show and how to make them again. An image "
         "with a sidecar names the commit that drew it, the run that produced it and the "
         "device it was drawn on. Images from before the sidecar convention have none; for "
         "those, the README and the commit that added the directory are all there is.</p>",
         f"<p class=muted>{c['dirs']} directories, {c['images']} images, {c['ok']} with a "
         f"current sidecar, {c['legacy']} with an older one, {c['broken']} with a broken one.</p>",
         "<h2 id=index>Directories</h2>",
         "<table><tr><th>Issue</th><th>Directory</th><th>What it shows (README title)</th>"
         "<th>Added in</th><th>Images</th></tr>"]
    for e in entries:
        n_ok = sum(1 for i in e["images"] if i["state"] == "ok")
        added = e["added"].split(" ")
        added_cell = (f"{_commit_cell(repo, added[0])} {_e(added[1]) if len(added) > 1 else ''}"
                      if e["added"] else "-")
        readme = _blob(repo, sha, e["readme"]) if e["readme"] else ""
        title = f'<a href="{_e(readme)}">{_e(e["title"] or e["dir"])}</a>' if readme else _e(e["title"])
        h.append(f'<tr><td class=nw>{_e(e["issue"]) or "-"}</td><td><a href="#{_e(e["dir"])}"><code>'
                 f'{_e(e["dir"])}</code></a></td><td>{title}</td><td>{added_cell}</td>'
                 f'<td>{len(e["images"])} ({n_ok} with sidecar)</td></tr>')
    h.append("</table>")
    for e in entries:
        h.append(f'<h3 id="{_e(e["dir"])}">{_e(e["issue"] or e["dir"])}: {_e(e["title"])}</h3>')
        if not e["images"]:
            h.append("<p class=empty>No images in this directory (text or data only).</p>")
            continue
        h.append("<table><tr><th>Image</th><th>File</th><th>Commit</th><th>Run</th>"
                 "<th>Device</th><th>Sidecar</th></tr>")
        for i in e["images"]:
            raw = _blob(repo, sha, i["path"], raw=True)
            thumb = (f'<a href="{_e(raw)}"><img loading=lazy src="{_e(raw)}" alt=""></a>' if raw else "")
            cls = "r-pass" if i["state"] == "ok" else "r-fail" if i["state"] in BROKEN else "r-none"
            h.append(f"<tr><td>{thumb}</td><td><code>{_e(i['path'].rsplit('/', 1)[-1])}</code></td>"
                     f"<td>{_commit_cell(repo, i['commit'])}</td><td>{_run_cell(i['run'])}</td>"
                     f"<td>{_e(i['device']) or '-'}</td><td class={cls}>{_e(STATE_WORDS[i['state']])}</td></tr>")
        h.append("</table>")
    h.append('<p class=muted style="margin-top:40px">Generator: <code>tools/evidence_index.py</code> '
             "in billmallard/pyEfis. Sidecar convention: <code>docs/evidence.md</code>.</p>")
    h.append("</main></body></html>")
    return "\n".join(h)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo-root", default=str(pathlib.Path(__file__).resolve().parent.parent))
    ap.add_argument("--repo", default="", help="owner/name, for links (CI: $GITHUB_REPOSITORY)")
    ap.add_argument("--sha", default="", help="commit the links pin to (CI: $GITHUB_SHA)")
    ap.add_argument("--html", help="write the HTML index here")
    ap.add_argument("--markdown", action="store_true", help="print the Markdown index")
    ap.add_argument("--check", action="store_true", help="exit 1 on a broken sidecar")
    args = ap.parse_args(argv)
    entries = scan(args.repo_root)
    if args.markdown:
        sys.stdout.write(render_markdown(entries))
    if args.html:
        text = render_html(entries, args.repo, args.sha)
        leaks = find_leaks(text)
        if leaks:
            sys.stderr.write(f"refusing to publish {args.html}: it still contains {sorted(set(leaks))[:5]}\n")
            return 2
        out = pathlib.Path(args.html)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    if args.check:
        broken = [i for e in entries for i in e["images"] if i["state"] in BROKEN]
        c = counts(entries)
        print(f"{c['images']} evidence images: {c['ok']} with a current sidecar, {c['legacy']} with an "
              f"older one, {c['broken']} broken, {c['images'] - c['ok'] - c['legacy'] - c['broken']} without one.")
        for i in broken:
            print(f"  {i['path']}: {STATE_WORDS[i['state']]}")
        return 1 if broken else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
