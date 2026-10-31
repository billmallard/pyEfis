#  Copyright (c) 2026 MakerPlane
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.

"""Install / update step: accept the software notice for this pyEfis version.

Run at a terminal after installing or updating pyEfis, before starting it::

    pyefis-accept-notice            # or: python -m pyefis.install_ack

If the notice is already accepted for the running pyEfis version this prints
when and exits 0. Otherwise it hands over to ``pyefis-data accept``, which
shows the full notice and requires the typed word ``accept``; the record is
written by pyefis-data (append-only, outside both config trees, schema in
makerplane-data ``docs/install_acknowledgment.md``). pyEfis never writes a
record of its own.

This is an install step only. It never runs at boot and nothing in the
startup path waits on it: the startup notice is a non-blocking banner.

Exit codes: 0 accepted (now or earlier), 3 not accepted (declined, no
terminal, or ``--check`` found none), 2 pyefis-data missing or failed.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

from pyefis import __version__

NOT_ACCEPTED_RC = 3
UPDATER_RC = 2

# Where the appliance guide installs the updater when ~/.local/bin is not on
# PATH (a systemd service, a fresh non-login shell).
_VENV_UPDATER = "~/pyefis-data-venv/bin/pyefis-data"


def find_updater(explicit=None):
    """The pyefis-data command to run, or None when it is not installed."""
    if explicit:
        return os.path.expanduser(explicit)
    env = os.environ.get("PYEFIS_DATA")
    if env:
        return os.path.expanduser(env)
    found = shutil.which("pyefis-data")
    if found:
        return found
    venv = os.path.expanduser(_VENV_UPDATER)
    return venv if os.access(venv, os.X_OK) else None


def read_notice(cmd):
    """``pyefis-data notice --json`` as a dict, or None if it cannot be read
    (the updater predates the notice, or failed)."""
    try:
        out = subprocess.run([cmd, "notice", "--json"], capture_output=True,
                             text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    try:
        doc = json.loads(out.stdout)
    except ValueError:
        return None
    if not isinstance(doc, dict) or not doc.get("notice") or not doc.get("notice_sha256"):
        return None
    return doc


def _records(doc):
    return [r for r in doc.get("records") or [] if isinstance(r, dict)
            and isinstance(r.get("software"), dict)]


def acceptance_for(doc, version):
    """The latest record accepting the CURRENT notice text for this pyEfis
    version, or None. A new pyEfis version or a changed notice needs a new
    accept; a pyefis-data accept that did not name pyEfis does not count."""
    for rec in reversed(_records(doc)):
        if (rec.get("notice_sha256") == doc["notice_sha256"]
                and rec["software"].get("pyefis") == version):
            return rec
    return None


def trigger_for(doc):
    """``pyefis-update`` when some earlier accept named a pyEfis version (so
    this box has had pyEfis before), else ``pyefis-install``."""
    if any(r["software"].get("pyefis") for r in _records(doc)):
        return "pyefis-update"
    return "pyefis-install"


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="pyefis-accept-notice",
        description="Accept the pyEfis software notice for this version "
                    "(install/update step; records through pyefis-data).")
    ap.add_argument("--pyefis-data", metavar="CMD",
                    help="the pyefis-data command (default: $PYEFIS_DATA, PATH, "
                         f"then {_VENV_UPDATER})")
    ap.add_argument("--check", action="store_true",
                    help="only report: exit 0 if accepted for this version, 3 if not")
    args = ap.parse_args(argv)

    cmd = find_updater(args.pyefis_data)
    if cmd is None:
        print("pyefis-data is not installed. Install the nav-data updater "
              "(makerplane-data) first; the notice is accepted and recorded "
              "through it.", file=sys.stderr)
        return UPDATER_RC
    doc = read_notice(cmd)
    if doc is None:
        print(f"could not read the notice from `{cmd} notice --json`; this "
              f"pyefis-data may predate the install notice. Update it first.",
              file=sys.stderr)
        return UPDATER_RC

    rec = acceptance_for(doc, __version__)
    if rec is not None:
        print(f"notice already accepted for pyEfis {__version__} on "
              f"{rec.get('timestamp')} by {rec.get('user')}@{rec.get('host')}")
        return 0
    if args.check:
        print(f"notice not accepted for pyEfis {__version__}")
        return NOT_ACCEPTED_RC
    if not sys.stdin.isatty():
        print(f"{doc['notice']}\n\nThis notice has not been accepted for pyEfis "
              f"{__version__}. Run pyefis-accept-notice at a terminal.",
              file=sys.stderr)
        return NOT_ACCEPTED_RC
    # pyefis-data shows the full text and asks for the typed word itself, so
    # the record says "via": "tty" -- the person at the terminal typed it.
    try:
        return subprocess.call([cmd, "accept", "--trigger", trigger_for(doc),
                                "--software", f"pyefis={__version__}"])
    except OSError as e:
        print(f"could not run {cmd}: {e}", file=sys.stderr)
        return UPDATER_RC


if __name__ == "__main__":
    sys.exit(main())
