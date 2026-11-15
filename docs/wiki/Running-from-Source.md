# Running from Source

This page is for working on pyEFIS itself: a development checkout on a desktop
or laptop, with the test tools. To set up a device to fly, follow
[Setting Up a Device](Setting-Up-a-Device) instead.

## Prerequisites

- Python 3.9 or later. CI runs 3.12. (`pyproject.toml` still says 3.8, but the
  code needs 3.9.)
- `git` (one dependency installs from a git URL) and `make`.
- A display: pyEFIS is a Qt application and needs one, even for a quick look.
  The tests run offscreen.
- fix-gateway for live data; see [Setting Up a Device](Setting-Up-a-Device#3-first-start).

## Check out and build the environment

```bash
git clone -b dev https://github.com/billmallard/pyEfis.git
cd pyEfis
make init
source venv/bin/activate
```

- `make venv` creates `venv/` with the development tools: flake8, black,
  pytest, pytest-qt, pytest-env and pytest-cov.
- `make init` does that, then installs pyEFIS editable with PyQt6 6.8.0 (the
  `qt` extra).
- On a Raspberry Pi running Bookworm, both use the system's PyQt6 instead
  (`sudo apt install python3-pyqt6 x11-utils` first), and the venv sees the
  system packages.

Neither installs synthetic vision's dependencies. Add them with:

```bash
pip install -e '.[qt,svs]'
```

| Extra | Installs | For |
|---|---|---|
| `qt` | PyQt6 6.8.0 | Running pyEFIS. |
| `svs` | numpy, PyOpenGL | Synthetic vision. Without it the attitude display shows `SVS UNAVAIL`. |
| `build` | build | `make wheel`. |

## Run it

```bash
python pyEfis.py          # or the installed entry point: pyefis
```

| Flag | What it does |
|---|---|
| `--debug` | Debug logging. |
| `-v`, `--verbose` | More logging. |
| `--config-file <path>` | Use this configuration file. Nothing is copied; `preferences.yaml` must sit beside it. |
| `-m`, `--mode` | `normal` (default) or `test`. |
| `--log-config <path>` | A logging configuration file. |

Without `--config-file`, every start copies the shipped configuration to
`~/makerplane/pyefis/config/` and loads `default.yaml` from there. Files you
have not edited are replaced; edited ones are kept, with the new version beside
them as `.dist`. See
[Customizing Beyond the Configurator](Customizing-Beyond-the-Configurator#the-files-on-the-device).

Started by systemd, pyEFIS exits unless `AUTO_START` is on under `enabled:` in
the preferences. It is on in the shipped `preferences.yaml.custom`.

The other entry point is `pyefis-accept-notice`; see
[Setting Up a Device](Setting-Up-a-Device#2-accept-the-software-notice).

## Synthetic vision data on a desktop

The stock screens' synthetic-vision include
(`config/includes/ahrs/svs.yaml`) ships with synthetic vision off, and its paths
point at `/data/makerplane-data/...`, where `pyefis-data` installs packs on a
device. To try it on a desktop:

1. Install the `svs` extra.
2. Install packs somewhere you can write, with `pyefis-data`
   ([Setting Up a Device](Setting-Up-a-Device#6-install-navigation-data)).
3. In `~/makerplane/pyefis/config/includes/ahrs/svs.yaml`, set `enabled: true`
   and point `tile_path` and the database paths at your packs.

A configurator panel sets these on the instrument instead; see
[Attitude & SVS](Widgets-Attitude-and-SVS#how-the-terrain-options-reach-the-renderer).

## Tests and checks

```bash
make test        # flake8 (errors only, then a full report), then pytest
pytest tests/    # just the tests
```

pytest runs with coverage, so pytest-cov must be installed (`make venv` does).
`make wheel` builds a wheel.

The instrument reference tables are generated from the code; after changing an
instrument's options, refresh them with
`docs/images/reference/gen_reference.py --update docs/wiki` (see its README).

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError: No module named 'PyQt6'` | Install the `qt` extra, or on a Pi `python3-pyqt6`. |
| The attitude display shows `SVS UNAVAIL` | Expected without the `svs` extra, a usable GPU, or position data. |
| No live values | fix-gateway is not running, or `FixServer`/`FixPort` in `main/default.yaml` do not point at it. |
| Display errors from a terminal | Set `DISPLAY=:0`. |
