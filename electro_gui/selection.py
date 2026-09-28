"""Deterministic stable-population selection for the electro GUI.

The selector is deliberately a small, bounded heuristic.  It chooses a
population whose stable trial intersection is large enough to support the
population, while keeping the quality filter and stability calculation
separate from any neural or event analysis.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np

from imitation_phys.session_stability import get_session_stability


_QUALITIES = {"sua", "mua"}


def _json_safe(value: Any) -> Any:
    """Return ``value`` using only JSON-compatible scalar/container types."""
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.ndarray):
        return [_json_safe(item) for item in value.tolist()]
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, float):
        return value if np.isfinite(value) else None
    return str(value)


def _unit_id(value: Any) -> int:
    return int(value)


def _trial_id(value: Any) -> int:
    return int(value)


def _provenance(loaded: Any, stability: Any) -> dict[str, Any]:
    summary = getattr(stability, "summary", {}) or {}
    source = summary.get("source_nwb")
    if source is None:
        source = getattr(loaded, "_source", None)
    return {
        "cache_key": _json_safe(getattr(stability, "cache_key", None)),
        "source": _json_safe(source),
        "summary": _json_safe(summary),
    }


def select_stable_population(loaded: Any) -> dict[str, Any]:
    """Select SUA/MUA units with a large shared complete-trial support.

    Every nonempty stable-trial mask is used as a start, then the remaining
    candidate with the largest intersection is added while the product
    ``n_units * n_trials`` does not decrease.  This bounded multistart greedy
    search is a transparent heuristic and is not guaranteed to find the
    globally optimal population.
    """
    loaded._check()
    # Keep this as the one provider call for a request.  Apart from avoiding
    # redundant scoring, this preserves the provider's verified cache identity.
    stability = get_session_stability(loaded.session, cache_root=loaded.cache_dir)

    complete_trials = {
        _trial_id(trial["id"])
        for trial in loaded.trials
        if trial.get("complete") is True
    }
    roster = {}
    for unit in loaded.units:
        quality = str(unit.get("quality", "")).strip().lower()
        if quality not in _QUALITIES:
            continue
        uid = _unit_id(unit["id"])
        roster[uid] = unit

    raw_masks = getattr(stability, "stable_trials", {}) or {}
    trial_order = sorted(complete_trials)
    trial_bits = {trial: 1 << index for index, trial in enumerate(trial_order)}
    masks = {
        uid: sum(
            trial_bits[trial]
            for trial in (_trial_id(value) for value in raw_masks.get(uid, ()))
            if trial in trial_bits
        )
        for uid in sorted(roster)
    }
    candidate_unit_ids = sorted(roster)
    # Keep one deterministic seed per distinct mask.  All units remain
    # available during growth, including units whose mask is empty.
    seeds = []
    seen_masks = set()
    for uid in candidate_unit_ids:
        mask = masks[uid]
        if mask and mask not in seen_masks:
            seeds.append(uid)
            seen_masks.add(mask)

    def grow(seed: int) -> tuple[tuple[int, ...], int]:
        selected = [seed]
        shared = masks[seed]
        remaining = [uid for uid in candidate_unit_ids if uid != seed]
        score = len(selected) * shared.bit_count()
        while remaining:
            # IDs are already sorted, so max(..., key=...) gives the required
            # smallest-ID tie break when intersection counts are equal.
            best = max(remaining, key=lambda uid: ((shared & masks[uid]).bit_count(), -uid))
            proposed = shared & masks[best]
            proposed_score = (len(selected) + 1) * proposed.bit_count()
            if proposed_score < score:
                break
            selected.append(best)
            shared = proposed
            score = proposed_score
            remaining.remove(best)
        return tuple(sorted(selected)), shared

    options = [grow(seed) for seed in seeds]
    if options:
        unit_ids, shared_trials = max(
            options,
            key=lambda option: (
                len(option[0]) * option[1].bit_count(),
                option[1].bit_count(),
                len(option[0]),
                tuple(-uid for uid in option[0]),
            ),
        )
    else:
        unit_ids, shared_trials = (), 0

    trial_ids = [trial_order[index] for index in range(len(trial_order)) if shared_trials & (1 << index)]
    n_units, n_trials = len(unit_ids), len(trial_ids)
    coverage = n_units * n_trials
    return _json_safe({
        "kind": "stable_selection",
        "session_id": loaded.session_id,
        "unit_ids": list(unit_ids),
        "trial_ids": trial_ids,
        "n_units": n_units,
        "n_trials": n_trials,
        "coverage": coverage,
        "candidate_units": len(candidate_unit_ids),
        "candidate_unit_ids": candidate_unit_ids,
        "method": "bounded multistart greedy shared-trial intersection heuristic; not guaranteed globally optimal",
        "stability": _provenance(loaded, stability),
    })
