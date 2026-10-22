"""Where electro_gui keeps its cache and findings, and where it finds figure configs.

They live in Dropbox, so every machine that runs the explorer shares them:

* ``<Dropbox>/projects/electro_gui/output/cache``    the verified stability cache
* ``<Dropbox>/projects/electro_gui/output/findings`` saved findings (JSON + PNG each)
* ``<Dropbox>/projects/analysis_imitation/data/output/presentation``
  figure configs, which the presentation decks write as ``*/electro_gui_configs/*.json``

The Dropbox root is found the way the thread-handoff kit finds it, so it is the
same folder on every Mac whatever its mount point: ``DROPBOX_ROOT``, else the
business (then personal) path in ``~/.dropbox/info.json``.  ``ELECTRO_GUI_OUTPUT``
replaces the output folder outright; ``--cache-dir``, ``--findings-dir`` and
``--config-dir`` replace one folder each.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

OUTPUT_ENV = "ELECTRO_GUI_OUTPUT"


def dropbox_root() -> Path | None:
    """``DROPBOX_ROOT``, else the business (then personal) Dropbox path in ``~/.dropbox/info.json``."""
    configured = os.environ.get("DROPBOX_ROOT")
    if configured:
        return Path(configured).expanduser()
    try:
        info = json.loads((Path.home() / ".dropbox" / "info.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    for account in ("business", "personal"):
        path = (info.get(account) or {}).get("path")
        if path:
            return Path(path)
    return None


def output_root() -> Path | None:
    """``ELECTRO_GUI_OUTPUT``, else ``<Dropbox>/projects/electro_gui/output``; None without either."""
    configured = os.environ.get(OUTPUT_ENV)
    if configured:
        return Path(configured).expanduser()
    root = dropbox_root()
    return root / "projects" / "electro_gui" / "output" if root else None


def presentation_dir() -> Path | None:
    """The presentation decks' folder in analysis_imitation's Dropbox output; None without Dropbox."""
    root = dropbox_root()
    return root / "projects" / "analysis_imitation" / "data" / "output" / "presentation" if root else None


def unit_notes_dir() -> Path | None:
    """Result Viewer's read-only notebooks; honor its data-folder override."""
    configured = os.environ.get("RESULT_VIEWER_DATA")
    if configured:
        return Path(configured).expanduser() / "notes"
    root = dropbox_root()
    return root / "projects" / "result-viewer" / "data" / "notes" if root else None
