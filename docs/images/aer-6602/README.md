# AER-6602: the CAS marker on the alternative layouts

Renders of each portrait and left-buttons screen file after this change, with
the stock files beside them for reference. Every screen is built whole by the
real screen builder from the shipped config and preferences, with the mock FIX
db and the demo CAS list (`AP LINK LOST`, red, unacknowledged), so the marker
reads WARNING. It flashes, so a grab catches it filled or outlined.

- `sheet-portrait.png`: pfd, ems, ems2, radio portrait (600 x 1024 each).
- `sheet-left-buttons.png`: pfd, ems (top), ems2, radio (bottom) left-buttons
  (1024 x 600 each).
- `sheet-stock.png`: the stock pfd, ems (top), ems2, radio (bottom) for
  comparison.
- One PNG per file, and `stock/` for the stock files.

Software rendering (offscreen platform). The attitude display draws without
terrain, and values are the mock's, not live data.

## Regenerate

From the repo root, with DejaVu fonts reachable through fontconfig:

```sh
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. \
  python3 tools/render_cas_alternatives.py docs/images/aer-6602
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. \
  python3 tools/render_cas_alternatives.py docs/images/aer-6602/stock \
  pfd.yaml ems.yaml ems2.yaml radio.yaml
```

The sheets are the PNGs pasted side by side with a 12 px white gap (PIL).
