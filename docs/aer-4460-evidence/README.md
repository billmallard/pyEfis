# AER-4460 -- configurable map range rings (G13, billmallard/pyEfis#136)

Moving map at 800 x 480, range 10 NM, ownship at 30 % up, track 087, no data
packs loaded (so the only layer drawing anything is range rings, plus ownship
and the status chip). Offscreen QPainter render; the map is a plain QWidget, so
these are the pixels the panel draws. Font is DejaVu Sans, since the sandbox
that drew them has no DejaVu Sans Condensed; the panel's condensed face will
look slightly narrower.

| Image | Options |
|---|---|
| `before_default.png` | `origin/dev` @ eed5e72, before this change |
| `default.png` | this change, no ring options set: **byte-identical to `before_default.png`** (same sha256) |
| `four_rings_label_right.png` | `range_ring_fractions: "0.25,0.5,0.75,1"`, `range_ring_label_angle: 90` |
| `labels_off.png` | `range_ring_labels: false` (the "10 NM" range chip stays) |
| `styled.png` | `range_ring_fractions: "0.5,1,1.5"`, `range_ring_label_angle: 315`, `range_ring_color: "#00ffff"`, `range_ring_opacity: 80`, `range_ring_width: 2.5`, `range_ring_label_size: 16` |

Each image has a `.json` sidecar (docs/evidence.md) naming the commit that drew it.

## Regenerate

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src \
    python3 docs/aer-4460-evidence/render_range_rings.py docs/aer-4460-evidence

# baseline: the same script against a checkout of dev before the change
git worktree add --detach /tmp/dev eed5e72
mkdir -p /tmp/dev/docs/aer-4460-evidence
cp docs/aer-4460-evidence/render_range_rings.py /tmp/dev/docs/aer-4460-evidence/
QT_QPA_PLATFORM=offscreen python3 /tmp/dev/docs/aer-4460-evidence/render_range_rings.py /tmp/before default
cmp /tmp/before/default.png docs/aer-4460-evidence/default.png   # no output = identical
```
