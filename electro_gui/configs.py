"""Config files: JSON view states kept in the repository, listed for the Views menu.

A config is one JSON file holding an explorer view state (the plain object the
page keeps as ``S``) plus a title, so a figure can be reproduced from a file
that is reviewed and versioned with the analysis instead of a link or a
server-side saved view.  Three shapes are accepted; anything else is reported
in ``errors`` and never stops the scan:

* a config: ``{"electro_gui_config": 1, "title": str, "hint": str, "group": str,
  "slide": int | str, "note": str, "state": {...}}`` (hint, group, slide and
  note are optional);
* a GUI settings export: an object with a ``state`` object and a ``tool``
  string (the page's own "Settings & provenance" JSON), titled by its file name;
* a bare state: an object with an ``align`` or ``unit`` key and no ``state``.

The page applies ``state`` through its own ``sanitize()``; this module only
finds and labels the files.  ``static/explorer.js`` (``readConfigObject``)
mirrors the three shapes for "Open config file...", so change both together.
"""
from __future__ import annotations

from pathlib import Path
import json

MAX_BYTES = 256 * 1024
CONFIG_VERSION = 1
NESTED = "electro_gui_configs"


def _reject_constant(name):
    raise ValueError(f"{name} is not valid JSON")


def _optional_text(obj, key):
    value = obj.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f'"{key}" must be a string')
    return value.strip()


def parse_config(obj, stem):
    """One parsed JSON value -> the listing entry (without id/file); ValueError when it is none of the three shapes."""
    if not isinstance(obj, dict):
        raise ValueError("the top level is not a JSON object")
    if "electro_gui_config" in obj:
        version = obj["electro_gui_config"]
        if isinstance(version, bool) or version != CONFIG_VERSION:
            raise ValueError(f"unsupported electro_gui_config version {json.dumps(version)[:40]} (expected {CONFIG_VERSION})")
        if not isinstance(obj.get("state"), dict):
            raise ValueError('"state" must be an object')
        slide = obj.get("slide")
        if slide is not None and (isinstance(slide, bool) or not isinstance(slide, (int, str))):
            raise ValueError('"slide" must be an integer or a string')
        return {"title": _optional_text(obj, "title") or stem, "hint": _optional_text(obj, "hint"),
                "group": _optional_text(obj, "group"), "slide": slide, "note": _optional_text(obj, "note"),
                "state": obj["state"]}
    if "state" in obj:
        if not isinstance(obj["state"], dict) or not isinstance(obj.get("tool"), str):
            raise ValueError('has a "state" key but is neither a config ("electro_gui_config": 1) '
                             'nor a GUI settings export (a state object plus a "tool" string)')
        return {"title": stem, "hint": obj["tool"].strip(), "group": "", "slide": None, "note": "", "state": obj["state"]}
    if "align" in obj or "unit" in obj:
        return {"title": stem, "hint": "", "group": "", "slide": None, "note": "", "state": obj}
    raise ValueError("not an electro_gui config, GUI settings export or bare view state")


def _slide_key(slide):
    if isinstance(slide, int):
        return (0, slide, "")
    if isinstance(slide, str):
        return (1, 0, slide.casefold())
    return (2, 0, "")


def _sort_key(entry):
    # Sections named by a deck first, then loose files; within one: slide, title.
    return (entry["group"] == "", entry["group"].casefold(), _slide_key(entry["slide"]), entry["title"].casefold(), entry["file"])


def _candidates(root):
    """Sorted ``D/*.json`` then ``D/*/electro_gui_configs/*.json``, no dotfiles or dot-directories."""
    found = [p for p in root.glob("*.json")]
    found += [p for p in root.glob(f"*/{NESTED}/*.json") if not p.parent.parent.name.startswith(".")]
    return sorted((p for p in found if not p.name.startswith(".")), key=lambda p: p.relative_to(root).as_posix())


def discover_configs(dirs):
    """Scan each directory in ``dirs`` -> ``{"configs": [...], "errors": [...]}``.

    A directory that does not exist is silently empty.  Files are read only when
    they resolve inside the directory they were found under, so a symlink cannot
    lead the scan (or the page) anywhere else.
    """
    configs, errors = [], []
    for given in dirs or ():
        root = Path(given).expanduser()
        if not root.is_dir():
            continue
        try:
            resolved = root.resolve()
            paths = _candidates(root)
        except OSError as exc:
            errors.append({"file": str(given), "error": f"cannot list directory: {exc.strerror or exc}"})
            continue
        for path in paths:
            rel = path.relative_to(root).as_posix()
            try:
                if not path.resolve().is_relative_to(resolved):
                    raise ValueError("resolves outside the config directory")
                if not path.is_file():
                    continue
                with path.open("rb") as handle:
                    raw = handle.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES:
                    raise ValueError(f"larger than {MAX_BYTES // 1024} KiB")
                try:
                    value = json.loads(raw.decode("utf-8-sig"), parse_constant=_reject_constant)
                except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
                    raise ValueError(f"invalid JSON: {exc}") from None
                entry = parse_config(value, path.stem)
            except ValueError as exc:
                errors.append({"file": rel, "error": str(exc)})
                continue
            except OSError as exc:
                errors.append({"file": rel, "error": f"cannot read: {exc.strerror or exc}"})
                continue
            configs.append({"id": rel, "file": rel, **entry})
    configs.sort(key=_sort_key)
    return {"configs": configs, "errors": errors}
