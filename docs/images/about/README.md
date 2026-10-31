# About / System screen evidence (AER-4341, BACKLOG L4)

- `about_1024x600.png`: the bundled About screen. One pack carries the L1
  `notice`; the other (`water-na`) was published before the field existed and
  says so.
- `datastatus_1024x600.png`: the Data Status screen with the new About button
  between Continue and Update.

Both are offscreen Qt renders against a sample `status.json` (in the script),
not bench captures. Regenerate:

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src \
  RENDER_FONT_DIR=<dir of .ttf files, only on a host with no system fonts> \
  python3 docs/images/about/render.py
```

These were made with matplotlib's bundled DejaVu fonts, so glyph shapes may
differ slightly from the panel's DejaVu Sans Condensed.
