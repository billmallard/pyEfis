# Headless Linux Appliance (boot-to-EFIS)

Field notes for turning a headless **x86-64 Linux** box (no desktop
environment) into a **boot-to-EFIS appliance** that auto-starts pyEFIS +
FIX-Gateway on power-on and drives an HDMI/touchscreen. Verified on an Intel
N150 mini-PC, Ubuntu Server 24.04, Python 3.12, running the development branches
from source.

This is the deployment/appliance companion to [Running from Source](Running-from-Source)
(which covers running from a checkout on a normal **desktop with a display**).
Read that first for the basics of clone / venv / `[qt,svs]` extras; this page
covers everything that's different when there's **no display server** and you
want it to come up as an EFIS by itself.

The single biggest surprise: **Qt's `eglfs` platform does not work with the
PyQt6 pip wheel.** If that's all you're chasing, jump to
[Display backend](#display-backend-the-big-one).

---

## What installs cleanly (don't over-prepare)

- **The "Raspberry-Pi-only" dependencies install fine on x86.** FIX-Gateway pins
  `rpi-lgpio`, `smbus`, and `tables` (PyTables); all three resolve from PyPI
  wheels on `x86_64` with **no workaround** (`rpi-lgpio` pulls `lgpio`, which has
  x86 wheels; `tables` ships a manylinux wheel). Installing `libhdf5-dev` /
  `libi2c-dev` first is belt-and-suspenders for the rare source build. Don't
  bother pre-patching the pin list.
- **PyQt6 (6.8.0), pyavtools (from git), numpy, PyOpenGL** all come from wheels.

### Harmless dependency conflict
pyEFIS pins `PyYAML==6.0.1`, FIX-Gateway pins `pyyaml==6.0.2`. In one shared
venv pip warns about the mismatch; **6.0.1 runs both fine.** Ignore it, or give
each package its own venv.

### Ubuntu 24.04 / PEP 668
The system Python is *externally managed* — `pip install` outside a venv is
refused. **Use virtualenvs**; don't reach for `--break-system-packages`.

### System packages
```bash
sudo apt install build-essential git python3-venv python3-dev pkg-config \
     libhdf5-dev libi2c-dev \
     libgl1 libegl1 libgles2 libglib2.0-0t64 libdbus-1-3 libxkbcommon0 \
     libfontconfig1 libfreetype6
```
(`libglib2.0-0t64` is the Ubuntu 24.04 name; older releases use `libglib2.0-0`.)

### Install
```bash
mkdir -p ~/src && cd ~/src
git clone --single-branch -b dev <fork>/FIX-Gateway.git fix-gateway
git clone --single-branch -b dev <fork>/pyEfis.git
python3 -m venv ~/pyefis-venv && source ~/pyefis-venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -e ~/src/fix-gateway            # the server; [qt] not needed
pip install -e ~/src/pyEfis[qt,svs]
```
On first run each app auto-seeds its config under `$HOME`
(`~/makerplane/fixgw/config`, `~/makerplane/pyefis/config`) — see
[Running from Source](Running-from-Source#first-run-behavior-and-file-locations).
`fixgw` binds `0.0.0.0:3490`; verify with `ss -ltn | grep :3490`.

---

## Display backend (the big one)

pyEFIS is a Qt app; a headless server has no display server. On a Raspberry Pi
the supported path is Qt's **`eglfs`** platform (fullscreen on KMS/DRM, no X).
**This does not work with the PyQt6 installed from the pip wheel**, and the
failure is opaque:

```
$ QT_QPA_PLATFORM=eglfs pyefis
qt.qpa.plugin: Could not load the Qt platform plugin "eglfs" ... even though it was found.
This application failed to start because no Qt platform plugin could be initialized.
```

Root cause: the **PyQt6-Qt6 wheel ships the eglfs *plugin* stubs but omits the
backing Qt eglfs KMS support libraries.** Confirm with `ldd`:

```bash
P=~/pyefis-venv/lib/python3.12/site-packages/PyQt6/Qt6/plugins
ldd $P/platforms/libqeglfs.so | grep 'not found'
# => libQt6EglFSDeviceIntegration.so.6, libQt6EglFsKmsSupport.so.6,
#    libQt6EglFsKmsGbmSupport.so.6   (absent from the wheel and the system)
```

The system EGL/GLES/GBM/DRM (`libEGL`, `libGLESv2`, `libgbm`, `libdrm`) are all
fine — it's Qt's own private eglfs libs that are missing, and you can't borrow
the distro's because they're a different Qt version than the wheel.

**Why the Pi "just works" and your x86 box doesn't:** the Pi image uses the
**distro** PyQt6 (`apt install python3-pyqt6`), whose system Qt6 *was* built with
eglfs. The convenience of `pip install PyQt6` is exactly what costs you eglfs.
Two ways out:

- **Option A — distro PyQt6 (keeps eglfs).** `sudo apt install python3-pyqt6
  python3-pyqt6.qtopengl`, create the venv with `--system-site-packages`, and
  install pyEFIS **without** the `[qt]` extra. Caveat: you inherit Ubuntu's Qt
  (6.4.x on 24.04), older than pyEFIS's 6.8.0 target — verify the SVS/GL paths.
- **Option B — minimal X + `xcb` (documented below).** Keeps the tested pip
  PyQt6 6.8.0 and full GL/SVS; adds a small X server. Reliable x86 kiosk path.

### Option B: minimal X server + xcb

```bash
sudo apt install xserver-xorg-core xserver-xorg-legacy xinit x11-xserver-utils
# let a service (not just a logged-in seat) start X on the console:
printf 'allowed_users=anybody\nneeds_root_rights=yes\n' | sudo tee /etc/X11/Xwrapper.config
```

The `xcb` plugin needs a set of xcb runtime libs a *minimal* server image lacks.
Qt only names `xcb-cursor0` in its error; find the rest with `ldd`:

```bash
ldd $P/platforms/libqxcb.so | grep 'not found'
sudo apt install libxcb-cursor0 libxkbcommon-x11-0 \
     libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libxcb-xkb1 \
     libxcb-image0 libxcb-render-util0 libxcb-util1
```

Launch script `~/start-pyefis.sh`:
```bash
#!/bin/bash
source /home/USER/pyefis-venv/bin/activate
export QT_QPA_PLATFORM=xcb
exec pyefis
```

Smoke test on the physical monitor (vt1):
```bash
xinit /home/USER/start-pyefis.sh -- :0 vt1 -nolisten tcp
```

---

## GPU / DRM access

- The iGPU exposes `/dev/dri/card0` (owned `root:video`). **Add the run user to
  `video` and `render`** (and `input` for touch/encoders):
  `sudo usermod -aG video,render,input USER` — effective on next login/service
  start.
- Mesa DRI/EGL/GBM (`libgl1-mesa-dri`, `libegl-mesa0`, `libgbm1`, `libdrm2`) were
  already present on Ubuntu Server; install if missing.

---

## Boot-to-EFIS: systemd services

Two system services, both `WantedBy=multi-user.target`. Mask the console getty
so the EFIS owns the screen: `sudo systemctl mask getty@tty1.service`.

`/etc/systemd/system/fixgw.service`:
```ini
[Unit]
Description=FIX Gateway (CAN-FIX bus)
After=network-online.target
Wants=network-online.target

[Service]
User=USER
ExecStart=/home/USER/pyefis-venv/bin/fixgw
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/pyefis.service` (X/xcb kiosk):
```ini
[Unit]
Description=pyEFIS display (X/xcb kiosk)
After=fixgw.service systemd-user-sessions.service
Wants=fixgw.service
Conflicts=getty@tty1.service

[Service]
User=USER
SupplementaryGroups=video render input tty
PAMName=login
WorkingDirectory=/home/USER
ExecStart=/usr/bin/xinit /home/USER/start-pyefis.sh -- :0 vt1 -nolisten tcp
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now fixgw.service pyefis.service
```

Notes:
- `PAMName=login` gives the service a real logind session on seat0 (lets X grab
  DRM master); with `Xwrapper allowed_users=anybody` the setuid Xorg handles the
  VT.
- The harmless `PAM unable to dlopen(pam_lastlog.so)` line is just newer PAM
  having dropped `pam_lastlog` — ignore it.
- A one-off `Failed with result 'exit-code'` can appear when you `systemctl
  restart` the kiosk (X releasing vt1); systemd restarts it and it settles. Cold
  boot is clean (`NRestarts=0`).

### Which screen it boots to
The boot screen is the **first entry in `screens/default_list.yaml`**, *not* the
`defaultScreen:` key in `main/default.yaml` (setting `defaultScreen` alone did
not change it). Reorder `default_list.yaml` (put `SCREEN_PFD` first) to boot
straight to the PFD instead of the nav-data screen. See
[Preferences & Styling](Preferences-and-Styling).

---

## The nav-data updater is a separate package

The "Update" button on pyEFIS's data-status screen and the `pyefis-data` CLI
(`status | catalog | update | pair | config-pull | …`) are **not** part of
pyEFIS — they live in the **makerplane-data** repo (`pyefis_data/` package). If
it's missing you get *"Updater unavailable on this device"* on screen and
`pyefis-data: command not found` on the shell.

```bash
python3 -m venv ~/pyefis-data-venv                     # its own venv
~/pyefis-data-venv/bin/pip install -e ~/src/makerplane-data
ln -sf ~/pyefis-data-venv/bin/pyefis-data ~/.local/bin/pyefis-data
```

- pyEFIS checks for the updater **at startup** — restart pyEFIS after installing
  it, or the screen keeps saying "unavailable".
- Environment selection lives in `~/.makerplane/pyefis/data.yaml`
  (`configurator_url:` for device pairing / panel pull; `base_url:` for the
  nav-data packs, defaulting to production).
- `~/.local/bin` is only on `PATH` for a login shell that sourced `~/.profile`
  *after* that directory existed — re-login if `pyefis-data` isn't found.

---

## Debugging aids

- **`ldd <plugin>.so | grep 'not found'`** is the fastest way to diagnose
  "plugin found but could not load" — it's almost always a missing shared lib.
- List available Qt platforms by running with `QT_QPA_PLATFORM=bogus` (the fatal
  error prints the list), or `QT_LOGGING_RULES="qt.qpa.*=true"` for verbose init.
- The `SIGUSR1 → /tmp/pyefis_screenshot.png` handler is **unreliable** for
  verification — it grabs a fixed window, not necessarily the live screen. Trust
  the monitor.

---

## Verification checklist

- [ ] `fixgw` running, `ss -ltn | grep :3490` shows a listener
- [ ] `ldd $P/platforms/libqxcb.so | grep 'not found'` → empty
- [ ] `xinit ~/start-pyefis.sh -- :0 vt1` paints the EFIS on the monitor
- [ ] `systemctl is-active fixgw pyefis` → active/active; `NRestarts=0` after a
      cold reboot
- [ ] `pyefis-data status` lists the pack catalog (`sources` shows `network: yes`)
- [ ] instruments come alive once a FIX source is pointed at `fixgw:3490` — until
      then they read stale / `XXX`, which is expected (see
      [Concepts](Concepts#1-the-fix-database-the-data-bus))
