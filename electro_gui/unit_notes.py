"""Read Result Viewer notebooks without importing its app or changing its data."""
from __future__ import annotations

import json
from pathlib import Path
import re


def read_unit_notes(folder, session_id, units):
    """Match saved NWB unit IDs in this session; report snapshot differences.

    A shared channel alone cannot identify a unit after a re-sort. Never remap
    IDs by channel, and keep differences visible beside the saved note.
    """
    result = {"units": {}, "available": False, "notices": []}
    if not isinstance(session_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}", session_id):
        raise ValueError("Invalid unit-notes session ID.")
    if folder is None:
        result["notices"].append("Result Viewer notes are not configured; set --unit-notes-dir.")
        return result
    folder = Path(folder)
    try:
        if not folder.is_dir():
            result["notices"].append("Result Viewer notes folder is unavailable.")
            return result
        path = folder / f"{session_id}.json"
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            result["available"] = True  # this session has no notebook yet
            return result
        if (not isinstance(raw, dict) or raw.get("schema") != "result-viewer.notebook/1"
                or raw.get("session_id") != session_id or not isinstance(raw.get("units"), dict)):
            raise ValueError("Notebook schema or session does not match.")
    except (OSError, ValueError) as exc:
        # A broken notebook must not prevent the session or unit picker loading.
        result["notices"].append(f"Could not read Result Viewer notes: {exc}")
        return result

    current = {str(u["id"]): u for u in units}
    absent, invalid = 0, 0
    for key, entry in raw["units"].items():
        if (not isinstance(entry, dict) or type(entry.get("unit_id")) is not int
                or str(entry["unit_id"]) != key
                or not isinstance(entry.get("note", ""), str)
                or not isinstance(entry.get("tags", []), list)
                or not all(isinstance(t, str) for t in entry.get("tags", []))
                or type(entry.get("flag", False)) is not bool):
            invalid += 1
            continue
        note, tags, flag = entry.get("note", ""), entry.get("tags", []), entry.get("flag", False)
        if not (note.strip() or tags or flag):
            continue
        unit = current.get(key)
        if unit is None:
            absent += 1
            continue
        warnings = []
        for field in ("peak_channel", "area", "quality"):
            saved, now = entry.get(field), unit.get(field)
            if saved is None or now is None or saved == "" or now == "":
                continue
            if str(saved).casefold() != str(now).casefold():
                warnings.append(f"{field.replace('_', ' ')}: saved {saved}, current {now}")
        result["units"][key] = {"note": note, "tags": tags, "flag": flag, "identity_warnings": warnings}
    result["available"] = True
    if absent:
        result["notices"].append(f"{absent} noted unit(s) are absent from this NWB; IDs were not remapped.")
    if invalid:
        result["notices"].append(f"Skipped {invalid} invalid notebook entry/entries.")
    return result
