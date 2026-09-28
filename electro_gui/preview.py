"""Selection-only previews for Unit and Population workspaces."""
from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence

from .analysis import prepare_rows
from .conditions import missing


def _base(request, workspace):
    return {"kind": "preview", "workspace": workspace, "session_id": request.get("session_id"),
            "settings": dict(request), "rows": [], "support": {"selected_events": 0, "selected_trials": 0,
            "selected_blocks": 0, "cohorts": [], "excluded": {}, "valid_zero": False},
            "eligibility": {"status": "pending", "policy": request.get("stability", "verified_stable")},
            "significance": {"status": "not_requested"}, "provenance": {"selection_only": True,
            "spike_counts": False, "fitting": False}}


def _missing_by_group(rows):
    out = {}
    for group in sorted({str(r.get("cohort", "all")) for r in rows}):
        members = [r for r in rows if str(r.get("cohort", "all")) == group]
        keys = sorted({k for r in members for k in r if k not in {"curve", "spikes"}})
        out[group] = {key: sum(missing(r.get(key)) for r in members) for key in keys if any(missing(r.get(key)) for r in members)}
    return out


def _significance(request, rows, support):
    test = request.get("test", "none")
    if test == "none":
        return {"status": "not_requested", "reason": "No significance test selected; preview does not compute statistics."}
    if test not in {"paired_permutation", "block_permutation"}:
        return {"status": "blocked", "reason": f"Unknown significance design {test!r}; choose a supported design before Compute."}
    recipe = request.get("recipe") or {}
    cohorts = recipe.get("cohorts", [])
    if len(cohorts) != 2:
        return {"status": "blocked", "reason": "Significance requires exactly two declared cohorts."}
    if recipe.get("facet", "none") != "none" or recipe.get("split_by", "none") != "none" or recipe.get("group_by", "cohort") != "cohort":
        return {"status": "blocked", "reason": "Significance requires cohort-only grouping without facets or subdivisions."}
    if recipe.get("overlap", "exclude") == "allow" and support.get("overlap_events_before_policy", 0):
        return {"status": "blocked", "reason": "Overlapping cohort memberships must be excluded before testing."}
    counts = {c["id"]: sum(r.get("cohort") == c["id"] for r in rows) for c in cohorts}
    if any(v == 0 for v in counts.values()):
        return {"status": "blocked", "reason": "Both cohorts need nonzero event support.", "cohort_events": counts}
    trial_blocks = {}
    for row in rows:
        block, trial = row.get("block_id"), row.get("trial")
        if missing(block):
            return {"status": "blocked", "reason": "Recorded block IDs are required for every selected trial."}
        if trial in trial_blocks and trial_blocks[trial] != block:
            return {"status": "blocked", "reason": "A selected trial has contradictory block IDs."}
        trial_blocks[trial] = block
    if test == "paired_permutation":
        paired = {r.get("trial") for r in rows if r.get("cohort") == cohorts[0]["id"]} & {r.get("trial") for r in rows if r.get("cohort") == cohorts[1]["id"]}
        trial_blocks = {}
        for row in rows:
            if row.get("trial") in paired:
                block = row.get("block_id")
                if missing(block):
                    return {"status": "blocked", "reason": "Recorded block IDs are required before a paired permutation can run."}
                if row.get("trial") in trial_blocks and trial_blocks[row.get("trial")] != block:
                    return {"status": "blocked", "reason": "A paired trial has contradictory block IDs."}
                trial_blocks[row.get("trial")] = block
        blocks = {r.get("block_id") for r in rows if r.get("trial") in paired and not missing(r.get("block_id"))}
        if len(blocks) < 3:
            return {"status": "blocked", "reason": "At least three paired blocks are required before a paired permutation can run.", "paired_trials": len(paired), "blocks": len(blocks)}
    elif test == "block_permutation":
        by_block = {}
        for row in rows:
            block = row.get("block_id")
            if missing(block):
                return {"status": "blocked", "reason": "Recorded block IDs are required before a block permutation can run."}
            by_block.setdefault(block, set()).add(row.get("cohort"))
        if any(len(groups) != 1 for groups in by_block.values()):
            return {"status": "blocked", "reason": "Independent block permutation requires disjoint blocks between cohorts."}
        if sum(next(iter(groups)) == cohorts[0]["id"] for groups in by_block.values()) < 2 or sum(next(iter(groups)) == cohorts[1]["id"] for groups in by_block.values()) < 2:
            return {"status": "blocked", "reason": "At least two disjoint blocks per cohort are required."}
    return {"status": "applicable", "reason": "The design is eligible; Compute will perform the requested test after preview."}


def _eligibility_for_unit(loaded, unit_id, policy):
    try:
        value = loaded.eligibility([unit_id], policy)
        if isinstance(value, tuple):
            trials, provenance = value
        else:
            trials, provenance = value, {}
        if isinstance(provenance, Mapping) and provenance.get("status") == "pending":
            return {"status": "pending", "unit_id": unit_id, "trials": [], "provenance": dict(provenance)}
        return {"status": "ready", "unit_id": unit_id, "trials": sorted(trials), "provenance": dict(provenance or {})}
    except Exception as exc:
        return {"status": "error", "unit_id": unit_id, "trials": [], "error": f"{type(exc).__name__}: {exc}"}


def _decorate(rows, support, request, workspace, eligibility, roster=None):
    copied = [{k: v for k, v in row.items() if k not in {"count", "rate", "curve", "spikes"}} for row in rows]
    support = dict(support)
    support["missing_by_cohort"] = _missing_by_group(copied)
    support["valid_zero"] = bool(not copied and not support.get("excluded", {}).get("error"))
    result = _base(request, workspace)
    result.update(rows=copied, support=support, eligibility=eligibility)
    result["significance"] = _significance(request, copied, support)
    result["test_options"] = {test: _significance({**request, "test": test}, copied, support)
                              for test in ("paired_permutation", "block_permutation")}
    if roster is not None:
        result["roster"] = roster
    return result


def preview_unit(loaded: Any, request: Mapping[str, Any]) -> dict[str, Any]:
    result = _base(request, "unit")
    unit_id = request.get("unit_id")
    try:
        rows, support, provenance = prepare_rows(loaded, request, [unit_id])
    except Exception as exc:
        result["status"] = "error"
        result["errors"] = [f"{type(exc).__name__}: {exc}"]
        result["eligibility"] = {"status": "error", "policy": request.get("stability", "verified_stable")}
        return result
    eligibility = {"status": "ready", "policy": request.get("stability", "verified_stable"),
                   "unit_ids": [unit_id], "eligible_trials": support.get("eligible_trials", 0),
                   "provenance": provenance.get("eligibility", {})}
    result = _decorate(rows, support, request, "unit", eligibility)
    result["provenance"].update(selection=provenance, unit_ids=[unit_id])
    result["status"] = "ready"
    return result


def preview_population(loaded: Any, request: Mapping[str, Any]) -> dict[str, Any]:
    result = _base(request, "population")
    ids = request.get("unit_ids")
    if not isinstance(ids, list) or not ids:
        result.update(status="error", errors=["Population preview requires an explicit nonempty unit roster."], eligibility={"status": "error"})
        return result
    if len(set(ids)) != len(ids):
        result.update(status="error", errors=["Population unit roster contains duplicate IDs."], eligibility={"status": "error"})
        return result
    if any(isinstance(i, bool) or not isinstance(i, int) for i in ids):
        result.update(status="error", errors=["Population unit roster IDs must be integers."], eligibility={"status": "error"})
        return result
    components = request.get("components", 3)
    if isinstance(components, bool) or not isinstance(components, int) or components < 2 or components > min(10, len(ids)):
        result.update(status="error", errors=["Population components must be an integer between 2 and the roster size."], eligibility={"status": "error"})
        return result
    by_id = {int(u["id"]): u for u in loaded.units}
    missing_ids = [i for i in ids if i not in by_id or isinstance(i, bool)]
    if missing_ids:
        result.update(status="error", errors=[f"Unknown population units: {missing_ids}"], eligibility={"status": "error"})
        return result
    roster_info = [dict(by_id[i], requested=True) for i in ids]
    policy = request.get("stability", "verified_stable")
    per_unit = [_eligibility_for_unit(loaded, i, policy) for i in ids]
    pending = any(e["status"] == "pending" for e in per_unit)
    errors = [e for e in per_unit if e["status"] == "error"]
    if pending:
        result.update(status="ready", roster=roster_info, eligibility={"status": "pending", "policy": policy, "per_unit": per_unit}, errors=["Eligibility is still pending; support is not final."])
        return result
    if errors:
        result.update(status="error", roster=roster_info, eligibility={"status": "error", "policy": policy, "per_unit": per_unit}, errors=[e["error"] for e in errors])
        return result
    common_trials = set(per_unit[0]["trials"]) if per_unit else set()
    for entry in per_unit[1:]: common_trials &= set(entry["trials"])
    roster = []
    for entry, unit in zip(per_unit, roster_info):
        others = [set(other["trials"]) for other in per_unit if other["unit_id"] != entry["unit_id"]]
        without = set.intersection(*others) if others else set(entry["trials"])
        roster.append({**unit, "eligible_trials": len(entry["trials"]), "common_trials": len(common_trials & set(entry["trials"])),
                       "lost_trials": len(set(entry["trials"]) - common_trials),
                       "marginal_common_without_unit": len(without), "marginal_trials_removed": len(without - common_trials),
                       "limiting_unit": len(without - common_trials) > 0})
    try:
        rows, support, provenance = prepare_rows(loaded, request, ids)
    except Exception as exc:
        result.update(status="error", roster=roster, eligibility={"status": "ready", "policy": policy, "common_trials": len(common_trials), "per_unit": per_unit}, errors=[f"{type(exc).__name__}: {exc}"])
        return result
    support["common_eligible_trials"] = len(common_trials)
    support["mixed_quality"] = len({str(u.get("quality")) for u in roster_info}) > 1
    result = _decorate(rows, support, request, "population", {"status": "ready", "policy": policy, "common_trials": len(common_trials), "per_unit": per_unit}, roster)
    result["provenance"].update(selection=provenance, unit_ids=ids, common_trial_ids=sorted(common_trials))
    result["status"] = "ready"
    return result


def preview(loaded: Any, request: Mapping[str, Any]) -> dict[str, Any]:
    workspace = request.get("workspace", "unit")
    if workspace == "unit":
        return preview_unit(loaded, request)
    if workspace == "population":
        return preview_population(loaded, request)
    raise ValueError("Preview workspace must be unit or population.")
