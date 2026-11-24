# ANN1 annunciator evidence (AER-6347)

- `sheet.png`: the 2x3 block cropped from ten captures of the composed PFD, 2x
  nearest-neighbour. In order: before first data, all keys fresh and off (NAVSRC
  2 = GPS), AP on (boxed, flash on phase), YD on (AP's flash still running, off
  phase: heavy box, caption hidden), ALT CAP on, NAVSRC 0 (VLOC1; NAVSRC is 0 NAV1,
  1 NAV2, 2 GPS), ALTSEL `annunciate` set (caution, amber), VS 2000 against a
  local `VS gt 1500` condition that asks for `warning` (drawn at advisory, white,
  by Bill's level rule), APENG old (stale), NAVSRC failed (stale).
- `pfd_state7.png`: the whole PFD at state 7, half size, so the block is seen in
  place (row 70, column 94, 16 x 35 cells of the 110 x 200 grid).
- `palette_demo_2x.png`: the offscreen palette render
  (`tools/render_instrument.py annunciator`), 2x.

Frame 0 is not empty: NAVSRC and ALTSEL have `tol` 0, so the gateway's init
values count as fresh from boot. See the spec's open items.

## How it was made

On the Beelink bench (`pyefis@10.110.10.241`), touching nothing live. The kit is
in `kit/`:

- a private fix-gateway (`kit/fgw.yaml`): the bench's own database, netfix only,
  on port 3497;
- a private `Xvfb :47 +extension GLX` at 1920x1080 (without GLX the window never
  reaches the root and x11grab reads black);
- this branch's `src/` on `PYTHONPATH`, with a scratch copy of the bench's live
  pyEfis config (`screens/managed.yaml`, the served PFD) pointed at port 3497
  and the block added (`kit/edit_cfg.py`);
- `kit/drive.py` writes a steady background (attitude, air data) at 2 Hz, steps
  each tile key, and x11grabs `:47` after each step.

```
scp -r src.tgz kit/* pyefis@10.110.10.241:bench-scratch/aer6347/
ssh pyefis@10.110.10.241 'cd ~/bench-scratch/aer6347 && tar xzf src.tgz && sh session.sh'
```

The tile keys (APENG, YDENG, APALTCAP, NAVSRC, ALTSEL, VS) are the keys the
bench's X-Plane adapter feeds. They were driven synthetically on the private
gateway so the live bus and sim stayed untouched. Fonts: B612 as configured.
SVS terrain renders through llvmpipe on the Xvfb (Santa Barbara, from the
driver's LAT/LONG).
