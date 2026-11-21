# SVSSHADE1 mock-ups (AER-6140)

Mock-ups for `docs/svs_terrain_shading_brief.md`. Every image here is produced
by `tools/svs_shading_mockups.py`. That script's docstring describes what each
column is: the map uses the real `TerrainLayer`; the SVS uses a CPU port of the
GL terrain shader.

| File | What it shows |
|---|---|
| `<scene>_sheet.png` | Three rows: A today, B solid, C tint. Left column: SVS at 800x480. Right column: map, track-up, 15 NM to the edge. |
| `<scene>_A_today_map_relief.png` | Today's map in `relief` mode at the same pose: the base that B uses. |
| `port_validation_coastal.png` | The CPU port (bottom) against the real on-device GL capture of the AER-1203 coastal pose (top). |
| `mockups.json` | The poses, the hazard-vs-base colour separation table, and the pyEfis revision the images were rendered from. |

## Regenerate

You need GLO-30 tiles for the four poses: N33-N39 at W106-W109 and W118-W121.
Pull them from the published pack. `fetch_terrain_tiles.py` range-reads single
tiles out of the pack:

```bash
python3 fetch_terrain_tiles.py --pack terrain-us-west-2024edr4 --dest <TILES> \
    --tiles N39W107 N39W108 N38W107 N38W108 N37W106 N37W107 N37W108 N37W109 \
            N38W106 N38W109 N39W106 N36W106 N36W107 N36W108 \
            N34W120 N34W121 N35W120 N35W121 N36W120 N36W121 N35W119 N34W119 \
            N36W119 N33W119 N33W120 N33W118 N34W118 N35W118
```

Then, from the repository root:

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src \
    python3 tools/svs_shading_mockups.py --tiles <TILES> --out docs/images/svsshade1
```

It needs numpy, Pillow and PyQt6. The map layer imports QtGui.

The images committed here were rendered in the agent sandbox at pyEfis `dev`
`f7fc078e`; `mockups.json` records the revision. A full run takes about 90
seconds.
