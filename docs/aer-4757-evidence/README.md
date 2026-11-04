# AER-4757 -- one-finger zoom rail on the moving map (G22, billmallard/pyEfis#205)

The moving map at 650 x 1000 (about the Map tab's pane on the Beelink's
1920 x 1080 PFD screen), north up, 10 NM, over Aspen (KASE, 12,500 ft) with
the bench's real terrain, water, roads, airports and navaids. Busy relief is
the hard case for reading a thin rail. These are offscreen QPainter renders;
the map is a plain QWidget, so they are the pixels the panel draws.

The offscreen platform reports about 100 DPI, so the touch column here is
79 px (20 mm at 3.94 px/mm). On the panel it is sized from the display's
own DPI, so its pixel width there will differ. The bench stage shows the
real size.

| Image | What it shows |
|---|---|
| `rail_10nm.png` | `zoom_rail: true`, at rest, 10 NM: thumb on the third detent of the default ladder 2-5-10-20-40-80-160 |
| `rail_10nm_x3.png` | the rail region of `rail_10nm.png`, 3x nearest-neighbour: halo, ticks, caps, thumb |
| `rail_10nm_touched.png` | the same with a finger on the track: full white, range label beside the thumb |
| `rail_between_rungs.png` | 13.7 NM after a free pinch: thumb between the 10 and 20 detents |
| `rail_right.png` | `zoom_rail_side: right` |
| `rail_bench_ladder.png` | the bench screen's own ladder `2,10,50,200,500,2000`: six detents |
| `no_rail.png` | `zoom_rail: false` (the default): no rail |
| `live_beelink_map.png` | the live Beelink panel (x11grab of the glass, Map tab cropped) with the branch staged and `zoom_rail: true` in the active config: the real panel DPI and the bench ladder's six detents |

Each image has a `.json` sidecar (docs/evidence.md) naming the commit that
drew it. The render ran from a `git archive` copy with no `.git`, so the
sidecars were written afterwards with `tools/evidence_sidecar.py --commit`.

## Regenerate

On the Beelink, where the data packs and fonts are:

```bash
git archive HEAD src tools tests/mock_db tests/__init__.py docs/aer-4757-evidence \
  | ssh pyefis@<beelink> 'mkdir -p ~/bench-scratch/aer-4757 && cd ~/bench-scratch/aer-4757 && tar xf -'
ssh pyefis@<beelink> 'cd ~/bench-scratch/aer-4757 && QT_QPA_PLATFORM=offscreen \
  ~/pyefis-venv/bin/python docs/aer-4757-evidence/render_zoom_rail.py out'
```
