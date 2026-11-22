# CERT20a -- example sidecar with a `platform` record

`pi5_example.png` and its sidecar `pi5_example.png.json` were made on the Pi 5
bench on 2026-11-22, with the pyEfis service running, from a scratch directory
(the live checkout was not touched). The image is the `describe_platform()`
record drawn as text; the sidecar's `platform` object is the same read, so the
two agree.

The Pi had capped its clock, throttled and hit the soft temperature limit at
some point since boot (`get_throttled` 0xe0000), and none of the three was
active when the record was taken (`now` is empty).

Regenerate (on the board you want described; QPainter on a QImage only, no
window and no GL):

```bash
QT_QPA_PLATFORM=offscreen EVIDENCE_RUN="local: tools/render_platform_example.py on the Pi 5 bench, pyEfis service live, AER-6324" \
  ~/pyEfis/.venv/bin/python tools/render_platform_example.py out/pi5_example.png <commit>
```
