# AER-1790: FPM in real operation (Beelink bench, live fix-gateway feed)

Diagnostic evidence for AER-1790 question (1a) -- whether the flight path
marker actually draws in real operation, not just whether it was missing
from `tools/svs_capture.py` harness frames. Captured 2026-09-20 against the
Beelink bench's already-running `pyefis.service` / `fixgw` (X11, no
simulator attached -- values are the gateway's last-held state, flagged
"old" but not "fail").

## Files

- `beelink_pfd_live.png` -- full 1920x1080 X11 grab of the live display
  (PFD + moving map), taken with the display server's own screen grab
  (bypasses the app's SIGUSR1 handler, which is known-broken for the
  SVS/AI widget -- see repo CLAUDE.md).
- `beelink_fpm_zoom_3x.png` -- 3x nearest-neighbour crop of the region
  around the flight-path marker (the green circle-and-wings symbol sitting
  on the horizon left of the yellow aircraft-reference chevron).

## Commands

Read live FIX values over the Net-FIX ASCII read command (`@r<ID>`) to
confirm what the FPM's required inputs actually were at capture time:

```
ssh pyefis@10.110.10.241 "python3 - <<'EOF'
import socket
s = socket.create_connection(('localhost', 3490), timeout=5)
s.settimeout(2)
for k in ('VS','GS','TRACK','HEAD','VPATH','PITCH','ROLL'):
    s.sendall(f'@r{k}\n'.encode())
buf = b''
try:
    while True:
        chunk = s.recv(65536)
        if not chunk: break
        buf += chunk
except socket.timeout:
    pass
print(buf.decode(errors='replace'))
EOF
"
```

Result at capture time: `VS=79.8 GS=178.7kt TRACK=96.1 HEAD=91.7 VPATH=0.37`,
all with the fail flag clear (`...;01000` -- flags are `aobfs`; only `o`
(old) is set, not `f`). `_fpm_solution_valid()` (`ai_widget.py`) only gates
on `VS/GS/TRACK/HEAD` fail state and a groundspeed floor -- both satisfied.

Screen grab (run on the bench itself, where `DISPLAY=:0` is the live X11
session pyefis renders into):

```
DISPLAY=:0 ~/pyefis-venv/bin/python3 -c "
from PyQt6.QtWidgets import QApplication
app = QApplication([])
screen = app.primaryScreen()
pix = screen.grabWindow(0)
pix.save('/tmp/aer1790_bench_live.png')
"
```

Then `scp`'d off the bench. The zoom crop was produced locally:

```python
from PIL import Image
img = Image.open("beelink_pfd_live.png").convert("RGB")
crop = img.crop((420, 220, 720, 420))
crop.resize((crop.width * 3, crop.height * 3), Image.NEAREST).save("beelink_fpm_zoom_3x.png")
```
