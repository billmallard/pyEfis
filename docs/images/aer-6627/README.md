# AER-6627: the CAS marker on the Android screens

Renders of `android.yaml`, `android-portrait.yaml` and `android-left-buttons.yaml`
after this change, with the `dev` versions in `before/`. Each screen is built
whole by the real screen builder from the shipped config and preferences, with
the mock FIX db and the demo CAS list (`AP LINK LOST`, red, unacknowledged), so
the marker reads WARNING. It flashes, so a grab catches it filled or outlined.

The weston (Android) surface needs an X server, weston and waydroid, so the
render draws a grey stand-in box over its rectangle instead. The box shows
where the Android app sits; it is not the app.

- `sheet-android.png`: before, after (1024 x 600 each).
- `sheet-android-left-buttons.png`: before, after (1024 x 600 each).
- `sheet-android-portrait.png`: before, after (600 x 1024 each).
- One PNG per file, and `before/` for the `dev` files.

Software rendering (offscreen platform), shipped preferences (`BUTTONS: true`,
`DEMO_TESTING_TEXT: false`), display state 1. Values are the mock's.

## Regenerate

From the repo root, with DejaVu fonts reachable through fontconfig:

```sh
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. \
  python3 tools/render_cas_alternatives.py docs/images/aer-6627 \
  android.yaml android-portrait.yaml android-left-buttons.yaml
```

For `before/`, check out the three screen files from the base commit first and
render into `docs/images/aer-6627/before`. The sheets are the PNGs pasted side
by side with a 12 px white gap (PIL).
