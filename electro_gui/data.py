"""Verified, JSON-safe data access for the electro_gui explorer."""
from __future__ import annotations

from collections import Counter, OrderedDict
from pathlib import Path
from typing import Any, Iterable, Mapping
import hashlib
import json
import math
import inspect

import numpy as np
import pandas as pd

from imitation_phys.session_file import read_session_file
from imitation_phys.derived_cache import SourceChangedError
from imitation_phys.session_stability import get_session_stability


_OUTCOMES = {"prey_capture", "prey_miss", "predator_contact", "predator_avoid"}
# Recorded events the explorer never offers as an alignment, marker or event
# list.  object_spawn is the task creating an object, not the object appearing:
# a trial the animal never initiates times out with every object spawned and
# none shown (sub-Ravel_ses-2026_09_15 trial 314), so a spawn-aligned row can
# belong to an object that was never presented and has no role outcome.
# object_visible_onset is the anchor for "the object is on screen".
HIDDEN_EVENTS = frozenset({"object_spawn"})
# Their value (info.tokens_at_contact) is the token count the trial pays out.
_GOAL_CONTACTS = {"goal_contact_rewarded", "goal_contact_empty"}
_UNAVAILABLE = {
    "joystick_direction": "the assembled session has no joystick_x series",
    "gaze_direction": "continuous gaze features are not part of GUI v0.1",
    "color_label": "color labels are not embedded in the assembled NWB",
    "color_epoch_experience": "derivation is not implemented in GUI v0.1",
    "pre_switch_position": "strategy switch position is not embedded in the assembled NWB",
}

# These are the values defined by the assembled-session contract, rather than
# the values that happened to occur in one session.  Keeping the domain here
# means a valid category with zero support is distinguishable from a typo.
_CANONICAL_VALUES = {
    "world": ("PP", "PM", "MM"),
    "intention": ("PP", "PM", "MM", "NA"),
    "role": ("prey", "predator"),
    "action": ("touch", "avoid"),
    "joystick_direction": ("left", "right"),
    "outcome": tuple(sorted(_OUTCOMES)),
}
_FIELD_INFO = {
    "event": ("common", "Recorded aligned event name.", "The event is the row's alignment anchor.", None),
    "world": ("task", "Task world/block rule.", "Recorded for the whole trial; this is not inferred from neural activity.", None),
    "intention": ("task", "Observed trial strategy.", "Classified from the completed trial after its object outcomes are known; NA is a literal incompatible/undecided value.", None),
    "role": ("object", "Object role.", "Recorded or resolved for the object; available at object timing.", None),
    "action": ("object", "Observed object action.", "Resolved from the object's outcome after the object response; post hoc timing.", None),
    "joystick_direction": ("object", "Dominant joystick direction before the object's outcome.", "Sign of the largest |joystick_x| excursion in the 1 s before the outcome (deadzone MOVE_THRESHOLD); post hoc timing, missing when the joystick never leaves the deadzone.", None),
    "outcome": ("object", "Object outcome.", "Resolved from the object's completed response; post hoc timing.", None),
    "order": ("object", "Object ordinal within trial.", "Known from the object's trial sequence.", None),
    "image_id": ("object", "Image identity.", "Identity of the displayed object at object timing.", None),
    "bar": ("object", "Whether the object is a bar.", "Recorded for the object.", None),
    "success": ("task", "Trial success.", "Resolved for the completed trial.", None),
    "reward_tokens": ("task", "Reward tokens held at goal contact, i.e. what the trial pays out.", "Read at goal contact (goal_contact_rewarded or goal_contact_empty); missing on a trial that never reached the goal.", "tokens"),
    "block_id": ("task", "Block identifier.", "Recorded for the trial.", None),
    "trial": ("task", "Trial index.", "Recorded for the trial.", None),
    "t": ("common", "Session time.", "The row's aligned time on the ephys clock.", "s"),
}
_ALIGNMENT_CATEGORIES = {
    "movement": ("movement", "Movement timing events."),
    "reward": ("reward", "Reward and outcome events."),
    "eye": ("eye", "Eye and gaze events."),
    "technical": ("technical", "Synchronization and diagnostic events."),
    "object": ("object", "Object lifecycle and response events."),
    "trial": ("trial", "Trial and task timing events."),
}


def _alignment_metadata(alignments):
    """Return grouped alignment choices without changing the legacy list."""
    result = []
    for key in alignments:
        text = str(key).lower()
        if "move" in text or "joystick" in text:
            category, description = _ALIGNMENT_CATEGORIES["movement"]
        elif "reward" in text or "outcome" in text or "capture" in text or "miss" in text or "contact" in text or "avoid" in text:
            category, description = _ALIGNMENT_CATEGORIES["reward"]
        elif "gaze" in text or "eye" in text:
            category, description = _ALIGNMENT_CATEGORIES["eye"]
        elif any(token in text for token in ("sync", "pulse", "diagnostic")):
            category, description = _ALIGNMENT_CATEGORIES["technical"]
        elif "object" in text or "spawn" in text or "display" in text:
            category, description = _ALIGNMENT_CATEGORIES["object"]
        else:
            category, description = _ALIGNMENT_CATEGORIES["trial"]
        result.append({"key": key, "label": str(key).replace("_", " ").title(), "category": category, "description": description})
    return result


def _value_counts(values, domain=()):
    def key(value):
        return str(value).lower() if isinstance(value, bool) else str(value)
    counts = {key(v): 0 for v in domain}
    counts.update({key(k): int(v) for k, v in Counter(values).items()})
    return counts


def _safe(value: Any) -> Any:
    """Convert scalars recursively, with every non-finite value becoming null."""
    if isinstance(value, Mapping):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if isinstance(value, (list, tuple, np.ndarray)):
        return [_safe(v) for v in list(value)]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (float, np.floating)):
        return float(value) if math.isfinite(float(value)) else None
    if value is pd.NA or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _missing(value: Any) -> bool:
    return value is None or value is pd.NA or value == "" or (isinstance(value, float) and not math.isfinite(value))


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _row_value(row: pd.Series, key: str, default: Any = None) -> Any:
    value = row.get(key, default)
    return default if _missing(value) else value


def _trial_id(value: Any) -> int | None:
    try:
        return int(value) if _finite(value) else None
    except (TypeError, ValueError):
        return None


def _object_info(row: pd.Series) -> dict[str, Any]:
    info = row.get("info")
    value = row.get("value")
    out = dict(info) if isinstance(info, dict) else {}
    if isinstance(value, dict):
        out.update(value)
    return out


def _action_outcome(event: str, role: Any) -> tuple[str | None, str | None]:
    if event == "prey_capture": return "touch", event
    if event == "prey_miss": return "avoid", event
    if event == "predator_contact": return "touch", event
    if event == "predator_avoid": return "avoid", event
    if event in {"object_touch", "touch"}: return "touch", None
    if event in {"object_avoid", "avoid"}: return "avoid", None
    return None, None


def _boolean(value):
    value = _safe(value)
    return bool(value) if value in (0, 1, False, True) else None


def _info(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except ValueError:
            pass
    return {}


def _joystick_directions(events: pd.DataFrame, joystick) -> dict:
    """(trial, object_uid) -> 'left'/'right' from the pre-outcome joystick window."""
    from imitation_phys.object_outcome_psth import pre_outcome_direction_epochs
    epochs, _ = pre_outcome_direction_epochs(events, joystick)
    return {(int(r.trial_index), str(r.object_uid)): r.direction for r in epochs.itertuples(index=False)}


def _enrich(trials: pd.DataFrame, events: pd.DataFrame, classify=None, joystick=None, report: dict | None = None):
    """Join the full chronology before selection; never fill missing worlds.

    Rows tied to an object that was never shown are left out (see ``unseen``
    below); ``report``, when given, is filled with what was left out."""
    from imitation_phys.decoding import object_outcomes
    canonical = object_outcomes(events)  # Validates bar flags against recorded assets.
    records = events.to_dict(orient="records")
    trials_by_id, trial_extras = {}, {}
    for tid, values in trials.to_dict(orient="index").items():
        tid = int(tid)
        values = _safe(values)
        trial_extras[tid] = {f"trial.{k}": v for k, v in values.items() if isinstance(v, (str, int, float, bool)) or v is None}
        # A trial the animal never initiated (a timeout on the start block, e.g.
        # sub-Ravel_ses-2026_09_15 trial 314, or a session's last trial) showed
        # no object.  It gets no world and is not complete, the rule of
        # TrialsTable.complete() and trial_world_from_nwb, so it is in no raster
        # or PSTH.  Its scheduled block_type stays readable as trial.block_type.
        # A table without the column carries no evidence and counts as initiated.
        initiated = _boolean(values.get("initiated"))
        trials_by_id[tid] = {
            "id": tid, "start": values.get("start_time"), "stop": values.get("stop_time"),
            "initiated": initiated,
            "complete": False if initiated is False else _boolean(values.get("complete")),
            "world": None if initiated is False else values.get("block_type"),
            "block_id": values.get("preset_block_id", values.get("block_id")),
            "success": _boolean(values.get("success")),
            # Filled from goal contact below.  The trial table's
            # reward_token_delta is the task's sound-cue variable (+/- a
            # per-trial counter of token-change cues), not a token count.
            "reward_tokens": None,
            "intention": None,
        }
    objects, releases, goal_contacts = {}, {}, {}
    # Gaze events also target the agent, starting point, and other scene items.
    # Only task object lifecycles may enter ordinal/history/trial-choice joins.
    task_keys = {(_trial_id(r.get("trial_index")), str(_safe(r.get("object_uid"))))
                 for r in records if str(r.get("event", "")).startswith("object_") or r.get("event") in _OUTCOMES}
    for row_id, record in enumerate(records):
        tid, t = _trial_id(record.get("trial_index")), _safe(record.get("t_ephys_s"))
        uid = _safe(record.get("object_uid"))
        info = _info(record.get("info"))
        record["info"] = info
        if record.get("event") == "goal_release" and tid is not None and _finite(t):
            releases[tid] = min(t, releases.get(tid, t))
        if record.get("event") in _GOAL_CONTACTS and tid is not None and _finite(t):
            tokens = info.get("tokens_at_contact")
            tokens = _safe(record.get("value")) if tokens is None else tokens
            if _finite(tokens) and (tid not in goal_contacts or t < goal_contacts[tid][0]):
                goal_contacts[tid] = (t, int(round(float(tokens))))
        if tid is None or uid is None:
            continue
        key = (tid, str(uid))
        if key not in task_keys:
            continue
        obj = objects.setdefault(key, {"trial": tid, "uid": str(uid), "first_t": t, "first_row": row_id,
                                       "order": None, "role": None, "action": None, "bar": None,
                                       "image_id": None, "outcome": None, "outcome_t": None, "visible_onset_t": None, "info": {}})
        # Only object metadata are joined; outcome-only observations remain
        # retrospective and are labeled as such in the field registry.
        for k, v in info.items():
            if v is not None and isinstance(v, (str, int, float, bool)):
                obj["info"][f"object.{k}"] = _safe(v)
        if _finite(t) and (not _finite(obj["first_t"]) or t < obj["first_t"]):
            obj["first_t"] = t
        if record.get("event") == "object_visible_onset" and _finite(t):
            obj["visible_onset_t"] = min(t, obj["visible_onset_t"]) if obj["visible_onset_t"] is not None else t
        if info.get("ordinal") is not None:
            obj["order"] = _safe(info["ordinal"])
        if info.get("image_id"):
            obj["image_id"] = str(info["image_id"])
        if "is_bar" in info and info["is_bar"] is not None:
            obj["bar"] = _boolean(info["is_bar"])
        role = {"+": "prey", "-": "predator", "prey": "prey", "predator": "predator"}.get(record.get("kind"))
        role = role or {"prey": "prey", "predator": "predator"}.get(info.get("behavior"))
        if role:
            obj["role"] = role
    # A trial that never reached the goal paid nothing but has no count either;
    # it stays missing rather than becoming 0.
    for tid, (_, tokens) in goal_contacts.items():
        if tid in trials_by_id:
            trials_by_id[tid]["reward_tokens"] = tokens
    for item in canonical.to_dict(orient="records"):
        tid, uid = _trial_id(item["trial_index"]), _safe(item["object_uid"])
        obj = objects.get((tid, str(uid)))
        if obj is None:
            continue
        outcome = ("predator_contact" if item["touched"] else "predator_avoid") if item["is_predator"] else ("prey_capture" if item["touched"] else "prey_miss")
        if obj["outcome"] is not None and (obj["outcome"] != outcome or obj["outcome_t"] != float(item["t_outcome_s"])):
            raise ValueError(f"Conflicting outcomes for trial {tid}, object {uid}")
        obj.update(role="predator" if item["is_predator"] else "prey", action="touch" if item["touched"] else "avoid",
                   bar=bool(item["is_bar"]), image_id=_safe(item["image_id"]), outcome=outcome,
                   outcome_t=float(item["t_outcome_s"]))
        if obj["order"] is None:
            obj["order"] = int(item["order"]) + 1
    directions = _joystick_directions(events, joystick) if joystick is not None else {}
    for key, obj in objects.items():
        obj["direction"] = directions.get(key)
    # An object that was spawned but neither shown nor resolved (the animal never
    # initiated the trial and it ended in episode_timeout) has no behaviour to
    # label, and the gaze and saccade events tied to it are not about anything
    # that appeared.  Its rows are dropped below.  The object itself stays in
    # `objects`, so trial-level fields (complete_objects, intention) are still
    # computed over every spawned object rather than over a partial set.
    unseen = {key for key, obj in objects.items() if obj["visible_onset_t"] is None and obj["outcome"] is None}
    dropped = 0
    by_trial = {}
    for obj in objects.values():
        by_trial.setdefault(obj["trial"], []).append(obj)
    for tid, items in by_trial.items():
        items.sort(key=lambda o: (o["order"] is None, o["order"] if o["order"] is not None else o["first_t"] or 0, o["first_row"]))
        for i, obj in enumerate(items):
            obj.update(position=i, total=len(items), previous=items[i-1] if i else None,
                       next=items[i+1] if i+1 < len(items) else None)
        trial = trials_by_id.get(tid)
        if trial is None:
            continue
        nonbar = [o for o in items if o["bar"] is False]
        complete_objects = (trial["complete"] is True and bool(nonbar) and
                            all(o["bar"] is not None for o in items) and
                            all(o["outcome"] is not None and o["role"] is not None for o in nonbar))
        touch = any(o["outcome"] == "predator_contact" for o in nonbar)
        miss = any(o["outcome"] == "prey_miss" for o in nonbar)
        trial.update(trial_has_predator_touch=True if touch else False if complete_objects else None,
                     trial_has_prey_miss=True if miss else False if complete_objects else None,
                     trial_error_free=False if touch or miss else True if complete_objects else None)
        if complete_objects and classify is not None:
            # Same adapter inputs as decoding.trial_intentions, on resolved
            # non-bar objects only. Missing empirical evidence stays unavailable.
            trial["intention"] = classify({
                "successes": [int(o["outcome"] in ("prey_capture", "predator_avoid")) for o in nonbar],
                "is_predator": [int(o["role"] == "predator") for o in nonbar],
                "object_is_bar": [False] * len(nonbar),
                "prey_visual_ids": [o["image_id"] for o in nonbar if o["role"] == "prey" and o["image_id"]],
                "pred_visual_ids": [o["image_id"] for o in nonbar if o["role"] == "predator" and o["image_id"]],
            }, include_bars=False)
    ordered = sorted(trials_by_id.values(), key=lambda t: (t["start"] is None, t["start"] or 0, t["id"]))
    for i, trial in enumerate(ordered):
        prior = ordered[i-1].get("intention") if i and ordered[i-1]["complete"] is True else None
        next_ = ordered[i+1].get("intention") if i+1 < len(ordered) and ordered[i+1]["complete"] is True else None
        trial.update(previous_trial_intention=prior, next_trial_intention=next_,
                     trial_changed_strategy=trial["intention"] != prior if trial["intention"] is not None and prior is not None else None)
    outcomes = {tid: sorted((o for o in items if o["outcome_t"] is not None), key=lambda o: o["outcome_t"]) for tid, items in by_trial.items()}
    # All objects can be spawned before initiation; only recorded visibility
    # establishes when an upcoming object enters the displayed sequence.
    object_starts = {tid: sorted((o for o in items if _finite(o["visible_onset_t"])),
                                 key=lambda o: (o["visible_onset_t"], o["position"]))
                     for tid, items in by_trial.items()}
    first_errors = {tid: min((o["outcome_t"] for o in items if o["bar"] is False and o["outcome"] in ("prey_miss", "predator_contact")), default=None) for tid, items in by_trial.items()}
    rows = []
    for row_id, record in enumerate(records):
        tid, t = _trial_id(record.get("trial_index")), _safe(record.get("t_ephys_s"))
        trial = trials_by_id.get(tid, {})
        uid = _safe(record.get("object_uid"))
        if uid is not None and (tid, str(uid)) in unseen:
            dropped += 1
            continue
        obj = objects.get((tid, str(uid))) if uid is not None else None
        sequence = outcomes.get(tid, [])
        prior = obj["previous"] if obj else next((o for o in reversed(sequence) if _finite(t) and o["outcome_t"] <= t), None)
        if prior and (prior["outcome_t"] is None or not _finite(t) or prior["outcome_t"] > t):
            prior = None
        # Trial/other non-object anchors have no ordinal neighbour. Resolve the
        # first upcoming object in this trial, including a simultaneous onset.
        # Do not require an outcome: its recorded role can still be available.
        next_obj = obj["next"] if obj else next(
            (o for o in object_starts.get(tid, []) if _finite(t) and o["visible_onset_t"] >= t), None)
        next_outcome = next((o for o in sequence if _finite(t) and o["outcome_t"] > t), None)
        r = {**trial_extras.get(tid, {}), **(obj["info"] if obj else {}),
             "row_id": row_id, "t": t, "session_time": t, "trial": tid, "trial_index": tid,
             "event": str(record.get("event", "")), "object_uid": uid,
             "within_ephys_recording": _boolean(record.get("within_ephys_recording")),
             "within_sync_fit_window": _boolean(record.get("within_sync_fit_window")),
             "next_outcome_t": next_outcome["outcome_t"] if next_outcome else None,
             "next_outcome_row_object_uid": next_outcome["uid"] if next_outcome else None,
             "trial_end_t": trial.get("stop"), "goal_release_t": releases.get(tid),
             "object_outcome_t": obj["outcome_t"] if obj else None,
             "is_first_object": obj["position"] == 0 if obj else None,
             "is_last_object": obj["position"] == obj["total"]-1 if obj and trial.get("complete") is True else None,
             "correct": obj["outcome"] in ("prey_capture", "predator_avoid") if obj and obj["outcome"] else None,
             "previous_correct": prior["outcome"] in ("prey_capture", "predator_avoid") if prior and prior["outcome"] else None}
        for k in ("world", "intention", "block_id", "complete", "success", "reward_tokens", "previous_trial_intention", "next_trial_intention", "trial_changed_strategy", "trial_has_predator_touch", "trial_has_prey_miss", "trial_error_free"):
            r[k] = trial.get(k)
        for k in ("role", "action", "outcome", "image_id", "bar", "order"):
            r[k] = obj.get(k) if obj else None
        r["joystick_direction"] = obj.get("direction") if obj else None
        for prefix, other in (("previous", prior), ("next", next_obj)):
            for k in ("role", "action", "outcome"):
                r[f"{prefix}_{k}"] = other[k] if other else None
        first_error = first_errors.get(tid)
        r["before_first_error"] = t < first_error if _finite(t) and first_error is not None else True if trial.get("trial_error_free") is True else None
        rows.append(r)
    if report is not None:
        report.update(unseen_objects=len(unseen), unseen_rows=dropped,
                      unseen_trials=sorted({tid for tid, _ in unseen if tid is not None}))
    return ordered, rows

def _registry(trials: pd.DataFrame, rows: list[dict]) -> list[dict]:
    fields: dict[str, dict] = {}
    for key, label, typ, timing in [("event", "Alignment event", "category", "anchor"), ("world", "Task world", "category", "trial"), ("intention", "Observed trial strategy", "category", "full_trial_posthoc"), ("role", "Object role", "category", "object"), ("action", "Object action", "category", "object_outcome_posthoc"), ("joystick_direction", "Joystick direction", "category", "object_outcome_posthoc"), ("outcome", "Object outcome", "category", "object_outcome_posthoc"), ("order", "Object ordinal", "number", "object"), ("image_id", "Image identity", "category", "object"), ("bar", "Bar object", "boolean", "object"), ("success", "Trial success", "boolean", "full_trial_posthoc"), ("reward_tokens", "Trial reward tokens", "number", "full_trial_posthoc"), ("block_id", "Block ID", "number", "trial"), ("trial", "Trial index", "number", "trial"), ("t", "Session time (seconds)", "number", "anchor")]:
        vals = [r.get(key) for r in rows if not _missing(r.get(key))]
        available = bool(vals) or key in {"event", "trial", "t"}
        info = _FIELD_INFO.get(key, ("advanced", label, "Recorded field.", None))
        domain = _CANONICAL_VALUES.get(key, (False, True) if typ == "boolean" else ())
        grouping_eligible = typ != "number"
        entry = {"key": key, "label": label, "type": typ, "timing": timing, "timing_description": info[2], "description": info[1], "category": info[0], "availability": "available" if available else "unavailable", "value_counts": _value_counts(vals, domain) if typ != "number" else {}, "missing_count": len(rows) - len(vals), "cardinality": len(set(vals)), "units": info[3], "grouping_eligible": grouping_eligible, "grouping_requires_bins": typ == "number", "grouping_reason": "numeric fields require explicit bins" if typ == "number" else None}
        if typ == "category": entry["values"] = list(_CANONICAL_VALUES.get(key, tuple(sorted({str(v) for v in vals}))))
        elif typ == "boolean": entry["values"] = [False, True]
        if typ == "number" and vals: entry["range"] = [min(vals), max(vals)]
        fields[key] = entry
    extras = {k for row in rows for k in row if k not in fields}
    for key in sorted(extras):
        if key.startswith("trial."): label, timing = key, "full_trial_posthoc"
        elif key.startswith("object."): label, timing = key, "full_object_posthoc"
        else: label, timing = key.replace("_", " ").title(), "derived"
        if key.startswith("previous_"):
            timing = "previous_trial" if key == "previous_trial_intention" else "resolved_by_anchor"
        elif key.startswith("next_"):
            timing = "future_trial_posthoc" if key == "next_trial_intention" else "future_object_posthoc"
        elif key in {"complete", "is_last_object", "trial_has_predator_touch", "trial_has_prey_miss", "trial_error_free", "trial_changed_strategy", "before_first_error", "trial_end_t", "goal_release_t"}:
            timing = "full_trial_posthoc"
        elif key in {"correct", "object_outcome_t"}:
            timing = "object_outcome_posthoc"
        vals = [r.get(key) for r in rows if r.get(key) is not None]
        typ = "boolean" if vals and all(isinstance(v, bool) for v in vals) else "number" if vals and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals) else "category"
        category = "history" if key.startswith(("previous_", "next_")) else "advanced"
        canonical_key = "intention" if key in {"previous_trial_intention", "next_trial_intention"} else next((suffix for suffix in ("role", "action", "outcome") if key.endswith("_" + suffix)), None)
        domain = _CANONICAL_VALUES.get(canonical_key, ()) if canonical_key else ()
        grouping_eligible = typ != "number"
        fields[key] = {"key": key, "label": label, "type": typ, "timing": timing, "timing_description": "Derived relative to the aligned row.", "description": f"Derived field {label}.", "category": category, "availability": "available" if vals else "unavailable", "value_counts": _value_counts(vals, domain) if typ != "number" else {}, "missing_count": len(rows) - len(vals), "cardinality": len(set(vals)), "units": "s" if key.endswith("_t") else None, "grouping_eligible": grouping_eligible, "grouping_requires_bins": typ == "number", "grouping_reason": "numeric fields require explicit bins" if typ == "number" else None, **({"values": list(domain) if domain else sorted({str(v) for v in vals})} if typ == "category" else {})}
        if typ == "number" and vals: fields[key]["range"] = [min(vals), max(vals)]
    for key, alias in (("trial_index", "trial"), ("session_time", "t")):
        fields[key] = {"key": key, "label": key.replace("_", " ").title(), "type": "number", "timing": "trial" if key == "trial_index" else "anchor", "timing_description": "Recorded trial or aligned session time.", "description": "Imported alias retained for recipe compatibility.", "category": "advanced", "availability": "available", "alias_of": alias, "value_counts": {}, "missing_count": sum(_missing(r.get(key)) for r in rows), "cardinality": 0, "units": "s" if key == "session_time" else None, "grouping_eligible": False, "grouping_requires_bins": True, "grouping_reason": "numeric fields require explicit bins"}
    for key, reason in _UNAVAILABLE.items():
        if fields.get(key, {}).get("availability") == "available": continue
        fields[key] = {"key": key, "label": key.replace("_", " ").title(), "type": "category", "timing": "unavailable", "timing_description": "No producer is available in this assembled session.", "description": reason, "category": "advanced", "availability": "unavailable", "reason": reason, "values": [], "value_counts": {}, "missing_count": len(rows), "cardinality": 0, "units": None, "grouping_eligible": False, "grouping_requires_bins": False, "grouping_reason": reason}
    return [fields[key] for key in sorted(fields)]


def alignment_keys(rows: Iterable[Mapping[str, Any]]) -> list[str]:
    """Every recorded event the explorer offers as an alignment, plus the outcome union."""
    return sorted(({r["event"] for r in rows} - HIDDEN_EVENTS) | {"object_outcome"})


class LoadedSession:
    def __init__(self, session, cache_dir: Path):
        self.session = session; self.session_id = session.session_id; self.cache_dir = cache_dir
        self.duration_s = session.recording_duration_s
        self.code_paths = [Path(__file__).resolve()]
        self.notices = []
        try:
            from imitation_phys.decoding import load_trial_intention_classifier
            classify = load_trial_intention_classifier()
            self.code_paths.append(Path(inspect.getfile(classify)).resolve())
        except (ImportError, FileNotFoundError, RuntimeError) as exc:
            classify = None
            self.notices.append(f"Observed trial strategy unavailable: {exc}")
        self._code_stats = {p: (p.stat().st_size, p.stat().st_mtime_ns, p.stat().st_ctime_ns) for p in self.code_paths}
        joystick = session.behavioral_series("joystick_x") if session.has_behavioral_series("joystick_x") else None
        report: dict = {}
        self.trials, self.rows = _enrich(session.trials().table, session.events(), classify, joystick, report)
        if report.get("unseen_objects"):
            ids = report["unseen_trials"]
            where = (f"trial {ids[0]}" if len(ids) == 1 else "trials " + ", ".join(map(str, ids)) if len(ids) <= 5
                     else f"{len(ids)} trials, {ids[0]}–{ids[-1]}")
            self.notices.append(f"Hid {report['unseen_rows']} event rows on {report['unseen_objects']} objects that were never shown ({where}).")
        self.fields = _registry(session.trials().table, self.rows)
        units = session.units(); peaks = units.metadata.get("peak_channel")
        # Peak channel survives a re-sort; unit IDs do not, so every label carries both.
        self.units = [{"id": int(uid), "area": units.area_of(i), "quality": units.quality(i), "n_spikes": int(len(units.spike_times_s[i])),
                       "peak_channel": int(peaks[i]) if peaks is not None and _finite(peaks[i]) else None} for i, uid in enumerate(units.unit_ids)]
        if not self.trials or not self.rows or not self.units:
            raise ValueError("Assembled session must contain nonempty unit, trial, and event tables.")
        self.alignments = alignment_keys(self.rows)
        self._source = session.source_identity()

    def _check(self):
        self.session.source_identity()
        for path, signature in self._code_stats.items():
            stat = path.stat()
            if (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns) != signature:
                raise RuntimeError("Session preparation code changed; restart electro_gui before loading results.")

    def spikes(self, unit_id):
        self._check(); units = self.session.units(); return np.asarray(units.spike_times_s[units.index_of(int(unit_id))], dtype=float)

    def eligibility(self, unit_ids: Iterable[int], policy: str):
        self._check(); requested = [int(x) for x in unit_ids]; complete = {int(t["id"]) for t in self.trials if t.get("complete") is True}
        unknown = set(requested) - {u["id"] for u in self.units}
        if unknown:
            raise ValueError(f"Unknown unit IDs: {sorted(unknown)}")
        if policy == "all_complete": return complete, {"policy": policy, "source": self._source, "stability": None}
        if policy != "verified_stable": raise ValueError("policy must be verified_stable or all_complete")
        stability = get_session_stability(self.session, cache_root=self.cache_dir)
        pairs = getattr(stability, "stable_trials", {}) or {}
        common = set(complete)
        for uid in requested: common &= set(int(x) for x in pairs.get(uid, ()))
        identity = stability.cache_key
        return common, {"policy": policy, "source": self._source, "cache_key": identity, "requested_unit_ids": requested}

    def metadata(self):
        self._check(); return _safe({"source": {**self._source, "path": str(self.session.path)}, "session_id": self.session_id, "duration_s": self.duration_s, "units": self.units, "fields": self.fields, "alignments": self.alignments, "alignment_fields": _alignment_metadata(self.alignments), "notices": self.notices, "counts": {"trials": len(self.trials), "complete_trials": sum(t["complete"] is True for t in self.trials), "rows": len(self.rows), "units": len(self.units)}})


class SessionStore:
    def __init__(self, roots: Iterable[str | Path] = (), session_files: Mapping[str, str | Path] | Iterable[str | Path] = (), cache_dir: str | Path | None = None):
        self.roots = [Path(x).expanduser() for x in roots]
        self.cache_dir = Path(cache_dir).expanduser() if cache_dir is not None else Path.home() / ".cache" / "imitation_phys"
        if isinstance(session_files, Mapping): self.session_files = {str(k): Path(v).expanduser() for k, v in session_files.items()}
        else: self.session_files = {Path(p).name[:-len("_session.nwb")]: Path(p).expanduser() for p in session_files}
        self._loaded: OrderedDict[str, LoadedSession] = OrderedDict()

    def catalog(self):
        found: dict[str, Path] = dict(self.session_files)
        for root in self.roots:
            if not root.is_dir(): continue
            for path in root.glob("*/analysis/nwb/*_session.nwb"):
                if path.name.startswith(".") or path.parent.parent.parent.name.startswith("."): continue
                sid = path.name[:-len("_session.nwb")]
                if path.parent.parent.parent.name != sid: continue
                found.setdefault(sid, path.resolve())
        return [{"id": sid, "path": str(path.resolve())} for sid, path in sorted(found.items(), reverse=True) if path.is_file() and not path.name.startswith(".") and path.name == f"{sid}_session.nwb"]

    def get(self, session_id: str) -> LoadedSession:
        sid = str(session_id); path = next((Path(e["path"]) for e in self.catalog() if e["id"] == sid), None)
        if path is None: raise KeyError(f"unknown session {sid}")
        if sid in self._loaded:
            loaded = self._loaded.pop(sid)
            try: loaded._check()
            except SourceChangedError: loaded = None
            if loaded is not None: self._loaded[sid] = loaded; return loaded
        session = read_session_file(path)
        if session.session_id != sid: raise ValueError(f"session identity {session.session_id!r} does not match filename {sid!r}")
        loaded = LoadedSession(session, self.cache_dir); self._loaded[sid] = loaded
        while len(self._loaded) > 2: self._loaded.popitem(last=False)
        return loaded
