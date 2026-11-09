# G69 evidence: the terrain palette reaches the glass (pyEfis #394, AER-5141)

Real OpenGL renders on the Beelink (Intel ADL-N, `tools/svs_capture.py
--offscreen`, 800x600, terrain only). Off Santa Barbara at 3,000 ft MSL,
heading 010, pitch -4, looking at the Santa Ynez range across the coast.
All five bands are in frame: water (foreground), safe green, caution amber,
warning red, conflict magenta (ridgeline above the aircraft).

| Image | What it is |
|---|---|
| `sba_palettes_strip.png` | Horizon band (rows 225-335) of the three branch renders, top to bottom clearance / subdued / high_contrast, scaled 2x nearest-neighbour. |
| `sba_palettes_full.png` | The three full branch frames side by side, left to right clearance / subdued / high_contrast, scaled 0.5x. |
| `sba_<palette>.png` | Each branch frame at 1:1, with its capture sidecar. |
| `dev_sba_any_palette.png` | `dev` (de037c4b), same pose. All three palettes produced this byte-identical file (sha256 `8bdd182c...df063`). That is the defect. |

Pixel samples (branch, after shading and haze):

| Palette | water (400,500) | safe (400,300) | conflict (420,243) |
|---|---|---|---|
| clearance | (36, 93, 159) | (42, 100, 35) | (168, 58, 187) |
| subdued | (40, 75, 118) | (53, 83, 49) | (148, 58, 167) |
| high_contrast | (18, 128, 217) | (42, 140, 35) | (201, 58, 220) |

The stock `clearance` render differs from `dev` by at most 1 LSB on 1,487
terrain pixels. That is rounding: the old shader constants were 3-decimal
approximations (0.392) of the same colours, the uniforms are exact (100/255).

Not palette-driven, by design of `_PALETTES`: the olive low end of the graded
safe band (`COLOR_SAFE_LOW`), visible as the brownish strip below the amber.
It blends into each palette's safe green.

## Provenance

The sidecars say `pyefis_rev: unknown` because the renders ran from a tar of
the working tree, not a checkout. The tree's `svs.py` / `svs_gl.py` sha256
(`4098c661...c8f9` / `9ba7eaff...13ba`) matched on the bench and locally,
and match commit d3de5e3b.

## Regenerate

On the Beelink, in a scratch tree that is a tar of
`src tools tests/mock_db tests/__init__.py` plus `palcap.py` from this
directory (it sets the SVS `palette` option from `$SVS_PALETTE`, which
`svs_capture.py` has no flag for):

```bash
D=/data/makerplane-data
for pal in clearance subdued high_contrast; do
  DISPLAY=:0 SVS_PALETTE=$pal PYTHONPATH=$PWD/src ~/pyefis-venv/bin/python palcap.py \
    --offscreen --out out/sba_$pal.png \
    --lat 34.33 --lon -119.90 --alt 3000 --heading 10 --pitch -4 --range 20 --timeout 150 \
    --tiles $D/terrain/tiles --water $D/water/current/water.sqlite --terrain-only
done
```

Composites (Pillow):

```python
from PIL import Image
names = ["clearance", "subdued", "high_contrast"]
ims = [Image.open(f"sba_{n}.png").convert("RGB") for n in names]
strip = Image.new("RGB", (800, 220 * 3 + 8))
for i, im in enumerate(ims):
    strip.paste(im.crop((0, 225, 800, 335)).resize((800, 220), Image.NEAREST), (0, i * 224))
strip.save("sba_palettes_strip.png")
full = Image.new("RGB", (800 * 3 + 16, 600))
for i, im in enumerate(ims):
    full.paste(im, (i * 808, 0))
full.resize((1200, 300)).save("sba_palettes_full.png")
```
