# About / System screen evidence (AER-4341, BACKLOG L4)

- `about_1024x600.png`: the bundled About screen. One pack carries the L1
  `notice`; the other (`water-na`) was published before the field existed and
  says so.
- `datastatus_1024x600.png`: the Data Status screen with the new About button
  between Continue and Update.

- `bench_beelink_datastatus.png`, `bench_beelink_about.png`: live x11grab
  captures from the Beelink bench (1920x1080, X11): the real boot screen at
  `35f606c`, then the About screen after a tap on About at `a894867`. Every
  installed pack there predates the L1 field, so each says it has no notice.

The first two are offscreen Qt renders against a sample `status.json` (in the script),
not bench captures. Regenerate:

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
