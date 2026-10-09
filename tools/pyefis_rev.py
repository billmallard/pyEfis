"""Live pyEfis checkout-identity resolution (AER-1675, AER-2627).

Shared by ``svs_capture.py`` (the per-frame ``pyefis_rev`` sidecar key) and
``capture_service.py`` (the ``/health`` ``service_ref`` key). Both questions
are really the same question -- "which pyEfis checkout is answering right
now" -- so there is exactly one function that answers it, read live off git
each time. A constant, or a value written once at deploy time and read back
later, is a value that can go stale the moment the checkout moves without
whatever wrote it noticing.

No heavy imports here on purpose: ``capture_service.py`` is a small,
dependency-light HTTP service by design (see its module docstring), and must
not pull in Qt/OpenGL/pyefis just to answer ``/health``.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent


def resolve_pyefis_rev(repo_root=None):
    """Identify the pyEfis checkout actually running right now (AER-1675).

    A cross-renderer differential (Beelink vs Pi) only localises a defect if
    a disagreement can be attributed to *different code* vs *different GPU*
    -- which needs the rendering identity read from the checkout that is
    live right now, not a constant someone has to remember to bump (a
    constant is a lie waiting to happen). Dirty is reported rather than
    silently collapsed into the clean SHA: a frame rendered from uncommitted
    changes is not reproducible from that SHA alone.

    Never raises -- this is metadata for archival/attribution, not something
    a caller should fail over. Returns "unknown" if this isn't a git
    checkout or git is unavailable.
    """
    root = repo_root or _REPO
    try:
        sha = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        if sha.returncode != 0:
            return "unknown"
        rev = sha.stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True, text=True, timeout=10,
        )
        if dirty.returncode == 0 and dirty.stdout.strip():
            rev += "-dirty"
        return rev
    except (OSError, subprocess.SubprocessError):
        return "unknown"
