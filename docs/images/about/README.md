# About / System screen evidence (AER-4341, BACKLOG L4)

- `about_1024x600.png`: the bundled About screen. One pack carries the L1
  `notice`; the other (`water-na`) was published before the field existed and
  says so.
- `about_history_1024x600.png`: the same screen scrolled to the L2 notice
  acknowledgment history, newest first, against a sample log of two records
  (a terminal accept at install, then a bench auto-accept labelled as not a
  person's accept).
- `datastatus_1024x600.png`: the Data Status screen with the new About button
  between Continue and Update.

- `bench_beelink_datastatus.png`, `bench_beelink_about.png`: live x11grab
  captures from the Beelink bench (1920x1080, X11): the real boot screen at
  `35f606c`, then the About screen after a tap on About at `a894867`. Every
  installed pack there predates the L1 field, so each says it has no notice.

- `bench_beelink_about_history.png`: an offscreen render of `284b9ec` ON the
  Beelink against that box's REAL files: its `status.json` (packs now carry
  the L1 notice) and its real acknowledgment log
  (`~/.local/state/makerplane/acknowledgments.jsonl`, two records written by
  `pyefis-data`), scrolled to the bottom. Not a capture of the live display.

The `*_1024x600.png` images are offscreen Qt renders against a sample
`status.json` and acknowledgment log (in the script), not bench captures.
Regenerate:

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src \
  RENDER_FONT_DIR=<dir of .ttf files, only on a host with no system fonts> \
  python3 docs/images/about/render.py
```

These were made with matplotlib's bundled DejaVu fonts, so glyph shapes may
differ slightly from the panel's DejaVu Sans Condensed.

The bench captures came from `bench-deploy.sh --ref aer-4341/about-system-screen`,
then a `pyefis.service` restart, `ffmpeg -f x11grab` of the boot frame,
`xdotool` click at (0.50w, 0.90h) on About, and a second grab.

`bench_beelink_about_history.png` came from a throwaway clone at
`~/bench-scratch/aer-4341-ackhist` on the Beelink (the live checkout was not
touched), run with `QT_QPA_PLATFORM=offscreen PYTHONPATH=src
~/pyefis-venv/bin/python` on a script that builds `about.AboutSystem(host)`
with its default paths in a black 1024x600 host, processes events, sets the
scroll area's vertical scrollbar to its maximum, and saves `host.grab()`.
