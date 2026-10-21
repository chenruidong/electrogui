"""Compact raster data for the interactive explorer (electro_gui 0.2).

The explorer does its display computations in the browser -- filtering,
grouping, sorting, binning, smoothing, markers and count-window rates -- so
that every knob redraws instantly.  This module supplies only what the
browser cannot compute from the session:

* ``alignment_table``: every candidate row of one alignment with its joined
  trial/object/history fields, in a dictionary-encoded columnar layout;
* ``unit_raster``: one unit's spike times around each row of that table, and
  each row's eligible span under a stability policy;
* ``event_times``: the times of one recorded event, for per-row markers;
* ``spike_train``: one unit's whole spike train, for the behavior timeline.

Row candidacy and eligibility follow :func:`electro_gui.analysis.prepare_rows`
exactly: complete trials only, finite times inside the ephys recording and
the sync-fit window, and a display window that, padded by the same fixed
0.4 s guard, lies inside the run of consecutive eligible trials that
contains the event.  The browser applies the window part of that rule from
the returned span, so moving the window never needs a server round trip.

The rows, spans, time grid, rates and basis fit themselves live in
:mod:`imitation_phys.explorer_core`, which the world-axis stages call to
reproduce an exported population view; this module imports them.
"""
from __future__ import annotations

import json
import math
from collections import Counter, OrderedDict
from typing import Any, Mapping

import numpy as np

from imitation_phys.explorer_core import (GUARD_S, OUTCOMES, UNION_ALIGNMENTS, alignment_rows, checked_unit_ids,
                                         eligible_spans, explorer_cache, fit_basis, grid, group_means, is_candidate,
                                         row_rates)
from imitation_phys.session_store import HIDDEN_EVENTS

from .conditions import missing

MAX_WINDOW_S = 10.0    # analysis._validate_settings display limit
MAX_COMPONENTS = 50    # population fit; static/explorer.js MAX_NCOMP
SPIKE_DECIMALS = 5     # 10 us; well below a 30 kHz sample
SPIKE_TRAIN_TICK_S = 1e-4  # behavior timeline lane: far below one pixel at its tightest zoom

# Fields that identify rows rather than describe them, aliases, and fields that
# are constant by construction in a table of complete, in-recording rows.
_SKIP = {"row_id", "t", "session_time", "trial_index", "object_uid", "event", "complete",
         "within_ephys_recording", "within_sync_fit_window", "next_outcome_row_object_uid",
         "trial.start_time", "trial.stop_time", "trial.complete", "trial.preset_manifest_path",
         "trial.preset_session_id", "trial.preset_schema_version"}
_MAX_LEVELS = 400      # free-text columns (paths, sequences) are not useful to group by


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def alignment_counts(loaded: Any) -> dict[str, int]:
    """Candidate rows per alignment, including the four-outcome union."""
    cache = explorer_cache(loaded)
    if "counts" not in cache:
        complete = {t["id"] for t in loaded.trials if t.get("complete") is True}
        counts = Counter(r["event"] for r in loaded.rows if is_candidate(r, complete))
        for name, members in UNION_ALIGNMENTS.items():
            counts[name] = sum(counts.get(k, 0) for k in members)
        cache["counts"] = dict(counts)
    return cache["counts"]


def _column(key: str, values: list, info: Mapping[str, Any], anchors: list[float]) -> dict | None:
    present = [v for v in values if not missing(v)]
    if not present:
        return None
    typ = info.get("type", "category")
    if typ == "number" and all(_finite(v) for v in present):
        relative = key.endswith("_t")
        data = [None if missing(v) else round(float(v) - (a if relative else 0.0), 6) for v, a in zip(values, anchors)]
        if len({d for d in data if d is not None}) < 2:
            return None
        return {"kind": "num", "data": data, "relative": relative}
    if typ == "boolean" or all(isinstance(v, bool) for v in present):
        levels = [False, True]
    else:
        levels = sorted({str(v) for v in present}, key=_natural)
        if len(levels) > _MAX_LEVELS:
            return None
    if len(levels) < 2 and len(present) == len(values):
        return None  # constant and never missing: nothing to filter, group or sort by
    index = {level: i for i, level in enumerate(levels)}
    codes = [-1 if missing(v) else index[v if isinstance(v, bool) and levels == [False, True] else str(v)] for v in values]
    return {"kind": "cat", "levels": levels, "codes": codes}


def _natural(text: str):
    try:
        return (0, float(text), text)
    except ValueError:
        return (1, 0.0, text)


def alignment_table(loaded: Any, alignment: str) -> dict:
    """Columnar joined fields for one alignment; the order defines row indices."""
    cache = explorer_cache(loaded).setdefault("tables", {})
    if alignment in cache:
        return cache[alignment]
    rows = alignment_rows(loaded, alignment)
    anchors = [float(r["t"]) for r in rows]
    trials = {t["id"]: t for t in loaded.trials}
    registry = {f["key"]: f for f in getattr(loaded, "fields", [])}
    keys = sorted({k for r in rows for k in r} | set(registry))
    columns = []
    for key in keys:
        info = registry.get(key, {})
        if key in _SKIP or info.get("alias_of") or info.get("availability") == "unavailable":
            continue
        column = _column(key, [r.get(key) for r in rows], info, anchors)
        if column is None:
            continue
        column.update(key=key, label=info.get("label", key), category=info.get("category", "advanced"),
                      timing=info.get("timing"), description=info.get("description"))
        columns.append(column)
    # Within-trial time is often the most useful sorting key and is not a registry field.
    since_start = [round(a - float(trials[r["trial"]]["start"]), 6) if _finite(trials.get(r["trial"], {}).get("start")) else None
                   for a, r in zip(anchors, rows)]
    if any(v is not None for v in since_start):
        columns.append({"key": "since_trial_start", "label": "Time since trial start", "kind": "num", "data": since_start,
                        "relative": False, "category": "task", "timing": "anchor",
                        "description": "Seconds from the trial's start to this event."})
    uids = sorted({str(r.get("object_uid")) for r in rows if not missing(r.get("object_uid"))})
    uid_index = {u: i for i, u in enumerate(uids)}
    table = {"session_id": loaded.session_id, "alignment": alignment, "n": len(rows),
             "row_id": [int(r["row_id"]) for r in rows], "t": [round(a, 6) for a in anchors],
             "trial": [int(r["trial"]) for r in rows],
             "event": [str(r.get("event")) for r in rows] if alignment in UNION_ALIGNMENTS else None,
             "object": {"levels": uids, "codes": [uid_index.get(str(r.get("object_uid")), -1) for r in rows]},
             "columns": columns}
    cache[alignment] = table
    return table


def _window(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number") from None
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def unit_raster(loaded: Any, alignment: str, unit_id: int, policy: str, lo: float, hi: float) -> dict:
    """Spike times in ``[t+lo, t+hi)`` for every table row, plus eligibility.

    ``span`` is the row's eligible run relative to its event, clipped to the
    recording: a row may be displayed over ``[pre, post]`` only when
    ``pre - GUARD_S >= span[0]`` and ``post + GUARD_S <= span[1]``.  Rows whose
    trial is ineligible, or whose event lies outside every eligible run, get
    ``None`` and a status code.
    """
    lo, hi = _window(lo, "lo"), _window(hi, "hi")
    if not -MAX_WINDOW_S - 1 <= lo < hi <= MAX_WINDOW_S + 1:
        raise ValueError("Spike window must increase and lie within [-11, 11] s.")
    if isinstance(unit_id, bool) or int(unit_id) not in {int(u["id"]) for u in loaded.units}:
        raise ValueError(f"Unknown unit ID: {unit_id!r}")
    unit_id = int(unit_id)
    rows = alignment_rows(loaded, alignment)
    eligible, provenance = loaded.eligibility([unit_id], policy)
    spans, status = eligible_spans(loaded, rows, set(eligible))
    spikes = np.sort(np.asarray(loaded.spikes(unit_id), dtype=float))
    anchors = np.array([float(r["t"]) for r in rows])
    starts = np.searchsorted(spikes, anchors + lo, side="left")
    stops = np.searchsorted(spikes, anchors + hi, side="left")
    out_spikes = [np.round(spikes[a:b] - t, SPIKE_DECIMALS).tolist() for a, b, t in zip(starts, stops, anchors)]
    unit = next(u for u in loaded.units if int(u["id"]) == unit_id)
    return {"session_id": loaded.session_id, "alignment": alignment, "unit": unit, "policy": policy,
            "window": [lo, hi], "guard_s": GUARD_S, "n": len(rows), "row_id": [int(r["row_id"]) for r in rows],
            "spikes": out_spikes, "span": spans, "status": status,
            "status_labels": {"0": "eligible", "1": "trial not eligible under this policy", "2": "event outside an eligible run"},
            "eligible_trials": len(eligible),
            "eligibility": {k: v for k, v in (provenance or {}).items() if k != "source"}}


def spike_train(loaded: Any, unit_id: int) -> dict:
    """One unit's whole spike train, for the behavior timeline's spike lane.

    Times are on the session (ephys) clock, rounded to ``SPIKE_TRAIN_TICK_S``
    and sent as integer tick differences, ``t[i] = tick_s * (dt[0] + ... +
    dt[i])``: a few characters per spike, so a 570 000-spike unit is about a
    megabyte gzipped.  No eligibility rule applies; the lane shows every spike.
    """
    if isinstance(unit_id, bool) or int(unit_id) not in {int(u["id"]) for u in loaded.units}:
        raise ValueError(f"Unknown unit ID: {unit_id!r}")
    unit_id = int(unit_id)
    spikes = np.sort(np.asarray(loaded.spikes(unit_id), dtype=float))
    ticks = np.rint(spikes[np.isfinite(spikes)] / SPIKE_TRAIN_TICK_S).astype(np.int64)
    unit = next(u for u in loaded.units if int(u["id"]) == unit_id)
    return {"session_id": loaded.session_id, "unit": unit, "n": int(len(ticks)), "tick_s": SPIKE_TRAIN_TICK_S,
            "dt": np.diff(ticks, prepend=0).tolist()}


def event_times(loaded: Any, event: str) -> dict:
    """All valid occurrences of one recorded event (or the outcome union)."""
    cache = explorer_cache(loaded).setdefault("events", {})
    if event not in cache:
        known = {r.get("event") for r in loaded.rows} - HIDDEN_EVENTS
        if event not in UNION_ALIGNMENTS and event not in known:
            raise KeyError(f"Unknown event: {event}")
        names = UNION_ALIGNMENTS.get(event, {event})
        rows = [r for r in loaded.rows if r.get("event") in names and r.get("trial") is not None and _finite(r.get("t"))
                and r.get("within_ephys_recording", True) is not False and r.get("within_sync_fit_window", True) is not False]
        rows.sort(key=lambda r: float(r["t"]))
        cache[event] = {"event": event, "n": len(rows), "trial": [int(r["trial"]) for r in rows],
                        "t": [round(float(r["t"]), 6) for r in rows],
                        "object": [None if missing(r.get("object_uid")) else str(r.get("object_uid")) for r in rows]}
    return cache[event]


def behavior_timeline(loaded: Any) -> dict:
    """Every trial's span and every resolved object's outcome, for the behavior timeline.

    One entry per object with a recorded outcome (bars included and flagged),
    at its outcome time; ``onset`` is its recorded ``object_visible_onset``.
    Times follow :func:`event_times`: finite, inside the ephys recording and
    the sync-fit window.  Objects without an outcome (an aborted trial) are
    not listed.  Nothing here is inferred: role, action, correctness, bar and
    image identity are the joined fields every explorer row already carries.
    """
    cache = explorer_cache(loaded)
    if "behavior" in cache:
        return cache["behavior"]

    def valid(r):
        return (r.get("trial") is not None and _finite(r.get("t")) and not missing(r.get("object_uid"))
                and r.get("within_ephys_recording", True) is not False and r.get("within_sync_fit_window", True) is not False)

    onsets: dict = {}
    for r in loaded.rows:
        if r.get("event") == "object_visible_onset" and valid(r):
            key = (int(r["trial"]), str(r["object_uid"]))
            onsets[key] = min(float(r["t"]), onsets.get(key, math.inf))
    objects, seen = [], set()
    for r in sorted((r for r in loaded.rows if r.get("event") in OUTCOMES and valid(r)), key=lambda r: (float(r["t"]), int(r["row_id"]))):
        key = (int(r["trial"]), str(r["object_uid"]))
        if key in seen:
            continue
        seen.add(key)
        objects.append((key, r))
    trials = [t for t in loaded.trials if _finite(t.get("start")) and _finite(t.get("stop"))]
    trials.sort(key=lambda t: (float(t["start"]), int(t["id"])))
    text = lambda v: None if missing(v) else str(v)
    flag = lambda v: v if isinstance(v, bool) else None
    out = {
        "session_id": loaded.session_id, "duration_s": getattr(loaded, "duration_s", None),
        "trials": {"id": [int(t["id"]) for t in trials], "start": [round(float(t["start"]), 6) for t in trials],
                   "stop": [round(float(t["stop"]), 6) for t in trials], "complete": [flag(t.get("complete")) for t in trials],
                   "initiated": [flag(t.get("initiated")) for t in trials],
                   "world": [text(t.get("world")) for t in trials], "intention": [text(t.get("intention")) for t in trials],
                   "success": [flag(t.get("success")) for t in trials]},
        "objects": {"trial": [k[0] for k, _ in objects], "uid": [k[1] for k, _ in objects],
                    "row_id": [int(r["row_id"]) for _, r in objects], "t": [round(float(r["t"]), 6) for _, r in objects],
                    "onset": [round(onsets[k], 6) if k in onsets else None for k, _ in objects],
                    "role": [text(r.get("role")) for _, r in objects], "action": [text(r.get("action")) for _, r in objects],
                    "outcome": [str(r["event"]) for _, r in objects], "correct": [flag(r.get("correct")) for _, r in objects],
                    "bar": [flag(r.get("bar")) for _, r in objects], "image_id": [text(r.get("image_id")) for _, r in objects],
                    "order": [int(r["order"]) if _finite(r.get("order")) else None for _, r in objects]},
    }
    cache["behavior"] = out
    return out


def session_summary(loaded: Any) -> dict:
    """What the explorer needs to populate its pickers."""
    counts = alignment_counts(loaded)
    meta = loaded.metadata()
    return {"session_id": loaded.session_id, "source": meta["source"], "duration_s": meta["duration_s"],
            "counts": meta["counts"], "notices": meta.get("notices", []), "units": meta["units"],
            "alignments": [{"key": a, "n": int(counts.get(a, 0))} for a in loaded.alignments],
            "events": sorted({r.get("event") for r in loaded.rows if r.get("event")} - HIDDEN_EVENTS)}


# --------------------------------------------------------------------------- #
# Population workspace
# --------------------------------------------------------------------------- #

def stability_masks(loaded: Any) -> dict:
    """Verified-stable trials of every unit as base64 bitmasks over complete trials."""
    import base64
    from imitation_phys.session_stability import get_session_stability
    loaded._check()
    stability = get_session_stability(loaded.session, cache_root=loaded.cache_dir)
    trials = sorted(int(t["id"]) for t in loaded.trials if t.get("complete") is True)
    index = {t: i for i, t in enumerate(trials)}
    pairs = getattr(stability, "stable_trials", {}) or {}
    masks = {}
    for unit in loaded.units:
        bits = bytearray((len(trials) + 7) // 8)
        for t in pairs.get(int(unit["id"]), ()):
            i = index.get(int(t))
            if i is not None:
                bits[i >> 3] |= 1 << (i & 7)
        masks[str(unit["id"])] = base64.b64encode(bytes(bits)).decode()
    return {"session_id": loaded.session_id, "trials": trials, "units": masks, "cache_key": getattr(stability, "cache_key", None),
            "bit_order": "trial i (index into trials) is bit (i & 7) of byte (i >> 3)"}


_FIT_FIELDS = ("unit_ids", "alignment", "policy", "method", "scaling", "weight", "components", "pre", "post", "bin", "sigma", "groups", "factors", "tdr_window", "world_coding", "fit_group_keys", "fit_split", "fit_trial_ids")
TDR_DEFAULT_FACTORS = ("world", "action", "joystick_direction")


def _fit_inputs(loaded: Any, request: Mapping[str, Any]) -> dict:
    """Validate a population request and resolve its groups to eligible rows."""
    ids = checked_unit_ids(loaded, request.get("unit_ids"), minimum=2)
    alignment = request.get("alignment")
    policy = request.get("policy", "verified_stable")
    if policy not in ("verified_stable", "all_complete"):
        raise ValueError("policy must be verified_stable or all_complete")
    method, scaling, weight = request.get("method", "pca"), request.get("scaling", "zscore"), request.get("weight", "trial")
    if method not in ("pca", "ica", "fa", "tdr"):
        raise ValueError("method must be pca, ica, fa or tdr")
    if scaling not in ("center", "zscore"):
        raise ValueError("scaling must be center or zscore")
    if weight not in ("trial", "event"):
        raise ValueError("weight must be trial or event")
    components = request.get("components", 3)
    factors, world_coding = request.get("factors"), "linear"
    if method == "tdr":
        factors = list(TDR_DEFAULT_FACTORS) if factors is None else factors
        registry = {f["key"]: f for f in getattr(loaded, "fields", [])}
        if (not isinstance(factors, list) or not 2 <= len(factors) <= 10 or len(set(factors)) != len(factors)
                or any(not isinstance(f, str) for f in factors)):
            raise ValueError("Choose 2-10 distinct TDR factors.")
        for f in factors:
            if registry.get(f, {}).get("availability") != "available":
                raise ValueError(f"TDR factor {f!r} is not available in this session.")
        world_coding = request.get("world_coding", "linear")
        if world_coding not in ("linear", "steps"):
            raise ValueError("world_coding must be linear or steps")
        components = len(factors) + (1 if world_coding == "steps" and "world" in factors else 0)
    elif isinstance(components, bool) or not isinstance(components, int) or not 2 <= components <= MAX_COMPONENTS:
        raise ValueError(f"Choose 2-{MAX_COMPONENTS} components.")
    pre, post = _window(request.get("pre"), "pre"), _window(request.get("post"), "post")
    bin_s, sigma = _window(request.get("bin"), "bin"), _window(request.get("sigma", 0), "sigma")
    if not (-MAX_WINDOW_S <= pre < post <= MAX_WINDOW_S) or not 0.005 <= bin_s <= 0.2 or not 0 <= sigma <= 0.1:
        raise ValueError("Window must lie in [-10, 10] s, bin in [5, 200] ms and sigma in [0, 100] ms.")
    tdr_window = None
    if method == "tdr":
        win = request.get("tdr_window")
        lo, hi = (pre, post) if win is None else (_window(win[0], "tdr_window"), _window(win[1], "tdr_window")) if isinstance(win, list) and len(win) == 2 else (None, None)
        if lo is None or not pre - 1e-9 <= lo < hi <= post + 1e-9:
            raise ValueError("The TDR window must lie inside the display window.")
        tdr_window = [lo, hi]
    groups = request.get("groups")
    if not isinstance(groups, list) or not 1 <= len(groups) <= 24:
        raise ValueError("Send 1-24 groups.")
    rows = alignment_rows(loaded, alignment)
    by_id = {int(r["row_id"]): (i, r) for i, r in enumerate(rows)}
    eligible, provenance = loaded.eligibility(ids, policy)
    spans, _ = eligible_spans(loaded, rows, set(eligible))
    members, seen = [], set()
    for g in groups:
        row_ids = g.get("row_ids") if isinstance(g, Mapping) else None
        if not isinstance(row_ids, list) or not row_ids or any(isinstance(r, bool) or not isinstance(r, int) for r in row_ids):
            raise ValueError("Every group needs a nonempty list of integer row_ids.")
        picked = []
        for rid in row_ids:
            if rid not in by_id:
                raise ValueError(f"Row {rid} is not an event of alignment {alignment!r}.")
            if rid in seen:
                raise ValueError(f"Row {rid} belongs to more than one group.")
            seen.add(rid)
            i, row = by_id[rid]
            span = spans[i]
            if not span or pre - GUARD_S < span[0] - 1e-9 or post + GUARD_S > span[1] + 1e-9:
                raise ValueError(f"Row {rid} is not eligible for every roster unit over [{pre}, {post}] s (0.4 s guard).")
            picked.append(row)
        members.append(picked)
    n, radius, kernel, times = grid(pre, post, bin_s, sigma)
    flat = [row for picked in members for row in picked]
    if len(flat) * (n + 2 * radius) > 20_000_000:
        raise ValueError("Event x time matrix is too large; narrow the selection or widen the bins.")
    keys = [g.get("key", str(i)) for i, g in enumerate(groups)]
    if any(not isinstance(k, str) for k in keys) or len(set(keys)) != len(keys):
        raise ValueError("Group keys must be distinct strings.")
    fit_keys = request.get("fit_group_keys")
    if fit_keys is None:
        fit_keys = keys
    if (not isinstance(fit_keys, list) or not fit_keys or any(not isinstance(k, str) or k not in keys for k in fit_keys)
            or len(set(fit_keys)) != len(fit_keys)):
        raise ValueError("fit_group_keys must select existing distinct group keys.")
    split = request.get("fit_split", "all")
    if split not in ("all", "odd", "even"):
        raise ValueError("fit_split must be all, odd or even (trial IDs).")
    trial_ids = request.get("fit_trial_ids")
    selected_trials = {int(r["trial"]) for r in flat}
    if trial_ids is not None:
        if (split != "all" or not isinstance(trial_ids, list) or not trial_ids
                or any(isinstance(t, bool) or not isinstance(t, int) or t not in selected_trials for t in trial_ids)
                or len(set(trial_ids)) != len(trial_ids)):
            raise ValueError("fit_trial_ids must select distinct eligible trial IDs and cannot be combined with fit_split.")
        train_trials = set(trial_ids)
    else:
        train_trials = {t for t in selected_trials if split == "all" or t % 2 == (1 if split == "odd" else 0)}
    split_trials = split != "all" or trial_ids is not None
    train_members = [[r for r in picked if int(r["trial"]) in train_trials]
                     for k, picked in zip(keys, members) if k in fit_keys]
    if any(not picked for picked in train_members):
        raise ValueError("A selected training group has no training events; widen the selection or change the split.")
    if split_trials:
        members = [[r for r in picked if int(r["trial"]) not in train_trials] for picked in members]
        if any(not picked for picked in members):
            raise ValueError("A display group has no held-out events; widen the selection or change the split.")
        flat = [r for picked in members for r in picked]
        # Whole trial IDs alone do not prevent the same spikes entering both sets:
        # long event windows can cross trial boundaries. Include the smoothing pad.
        train_times = np.sort([float(r["t"]) for picked in train_members for r in picked])
        support_width = (n + 2 * radius) * bin_s
        for row in flat:
            t = float(row["t"])
            j = int(np.searchsorted(train_times, t))
            if any(abs(t - train_times[k]) < support_width - 1e-9 for k in (j - 1, j) if 0 <= k < len(train_times)):
                raise ValueError("Training and held-out spike windows overlap (including smoothing); narrow the window or change the trial subset.")
    key = json.dumps({k: request.get(k) for k in _FIT_FIELDS}, sort_keys=True, default=str)
    return {"ids": ids, "alignment": alignment, "policy": policy, "method": method, "scaling": scaling, "weight": weight,
            "components": components, "factors": factors, "world_coding": world_coding, "tdr_window": tdr_window, "pre": pre, "post": post, "bin": bin_s, "sigma": sigma, "groups": groups,
            "members": members, "flat": flat, "train_members": train_members, "fit_keys": fit_keys, "split_trials": split_trials,
            "eligible": eligible, "provenance": provenance,
            "n": n, "radius": radius, "kernel": kernel, "times": times, "key": key}


def population_fit(loaded: Any, request: Mapping[str, Any]) -> dict:
    """Condition means and one jointly fitted basis for explorer-defined groups.

    All normalization, active-unit selection and fitting use only the requested
    training groups/trials. Split mode displays complementary trials.
    The browser defines the groups (filters x colour x line style) and sends their
    row IDs; every row is re-checked here against the common-trial eligibility
    rule for this roster and window, so the fit never sees an ineligible event.
    The fitted transform is linear; its operator is cached so single-trial
    projections (:func:`population_probe`) never need a refit.
    """
    inp = _fit_inputs(loaded, request)
    ids, members, flat, weight = inp["ids"], inp["members"], inp["flat"], inp["weight"]
    method, scaling, components = inp["method"], inp["scaling"], inp["components"]
    pre, post, bin_s, sigma = inp["pre"], inp["post"], inp["bin"], inp["sigma"]
    n, radius, kernel, times = inp["n"], inp["radius"], inp["kernel"], inp["times"]
    groups, eligible, provenance, alignment, policy = inp["groups"], inp["eligible"], inp["provenance"], inp["alignment"], inp["policy"]
    train_members = inp["train_members"]
    train_flat = [r for picked in train_members for r in picked]
    anchors = np.array([float(r["t"]) for r in train_flat])
    def calculate_means(picks):
        rows = [r for picked in picks for r in picked]
        a = np.array([float(r["t"]) for r in rows])
        weights = np.zeros((len(picks), len(rows)))
        offset = 0
        for g, picked in enumerate(picks):
            per_trial = Counter(r["trial"] for r in picked)
            for j, r in enumerate(picked):
                weights[g, offset + j] = (1.0 / len(picked) if weight == "event" else
                                         1.0 / (len(per_trial) * per_trial[r["trial"]]))
            offset += len(picked)
        out = np.empty((len(picks), n, len(ids)))
        for u, uid in enumerate(ids):
            out[:, :, u] = group_means(np.sort(np.asarray(loaded.spikes(uid), dtype=float)), a, weights,
                                       pre, bin_s, n, radius, kernel)
        return out
    means = calculate_means(train_members)
    tdr = None
    if method == "tdr":
        from .tdr import design, fit_axes
        registry = {f["key"]: f for f in getattr(loaded, "fields", [])}
        X, used, described = design(train_flat, inp["factors"], registry, inp["world_coding"])
        if used.sum() * n * len(ids) > 60_000_000:
            raise ValueError("TDR event x time x neuron array is too large; narrow the selection, the TDR window or the roster.")
        lo, hi = inp["tdr_window"]
        bins = np.flatnonzero((times >= lo - 1e-9) & (times <= hi + 1e-9))
        if not len(bins):
            raise ValueError("The TDR window contains no time bin.")
        used_anchors = anchors[used]
        rates = np.stack([row_rates(np.sort(np.asarray(loaded.spikes(uid), dtype=float)), used_anchors, pre, bin_s, n, radius, kernel)[:, bins]
                          for uid in ids], axis=2)
        fit = fit_axes(means, ids, rates, X, described, bins, scaling, world_coding=inp["world_coding"])
        tdr = fit["tdr"]
        tdr.update(window=[lo, hi], bins=[int(bins[0]), int(bins[-1])], events_without_factor=int((~used).sum()),
                   factor_keys=list(inp["factors"]), world_coding=inp["world_coding"])
        for f in tdr["factors"]:
            f["peak_time"] = float(times[f["peak_bin"]])
        coords, loadings = np.array(fit["coordinates"], dtype=float), np.array(fit["loadings"], dtype=float)
        operator, offset_b = fit["operator"], fit["offset"]
        single, cumulative = fit["component_r2"], fit["cumulative_r2"]
        x = fit["x"]
    else:
        fit = fit_basis(means, ids, method, scaling, components)
        coords, loadings = np.array(fit["coordinates"], dtype=float), np.array(fit["loadings"], dtype=float)
        # The transform is linear: coords = x @ P + b, with x the centred/scaled rates.
        estimator, n_active = fit["estimator"], len(fit["active_ids"])
        offset_b = estimator.transform(np.zeros((1, n_active)))[0]
        operator = estimator.transform(np.eye(n_active)) - offset_b
        # Component signs are arbitrary; make each component's largest loading positive so
        # small knob changes do not flip trajectories.
        for k in range(components):
            j = int(np.argmax(np.abs(loadings[:, k])))
            if loadings[j, k] < 0:
                loadings[:, k] *= -1
                coords[:, k] *= -1
                operator[:, k] *= -1
                offset_b[k] *= -1
        x = fit["x"]
        xc = x - x.mean(axis=0)
        total = float(np.sum(xc ** 2)) or 1.0
        single = [1 - float(np.sum((xc - np.outer(coords[:, k] - coords[:, k].mean(), loadings[:, k])) ** 2)) / total
                  for k in range(components)]
        if method != "pca":
            # ICA/FA components have no natural order; list them by variance explained.
            order = sorted(range(components), key=lambda k: -single[k])
            coords, loadings, single = coords[:, order], loadings[:, order], [single[k] for k in order]
            operator, offset_b = operator[:, order], offset_b[order]
        # Components 1..k together, in the order shown, from the partial reconstruction
        # rather than summed: it equals the running sum of the single-component R^2 only
        # while the scores are uncorrelated (PCA, ICA; FA once converged), and it ends
        # at reconstruction_r2.
        resid, cumulative = xc.copy(), []
        for k in range(components):
            resid -= np.outer(coords[:, k] - coords[:, k].mean(), loadings[:, k])
            cumulative.append(1 - float(np.sum(resid ** 2)) / total)
    fits = explorer_cache(loaded).setdefault("fits", OrderedDict())
    fits[inp["key"]] = {"active_ids": list(fit["active_ids"]), "center": fit["center"][fit["varying"]], "scale": fit["scale"],
                        "operator": operator, "offset": offset_b}
    while len(fits) > 8:
        fits.popitem(last=False)
    # Apply the exact training affine transform to display means. Never refit,
    # re-center, re-scale or choose active units using projected observations.
    display_means = means if train_members == members else calculate_means(members)
    keep_mask = fit["varying"]
    display_x = (display_means[:, :, keep_mask] - fit["center"][keep_mask]) / fit["scale"]
    traj = display_x @ operator + offset_b
    train_trials = {int(r["trial"]) for r in train_flat}
    display_trials = {int(r["trial"]) for r in flat}
    training = {"group_keys": list(inp["fit_keys"]), "events": len(train_flat), "trials": len(train_trials),
                "trial_ids": sorted(train_trials), "row_ids": [int(r["row_id"]) for r in train_flat],
                "display_events": len(flat), "display_trials": len(display_trials),
                "display_trial_ids": sorted(display_trials), "shared_trials": len(train_trials & display_trials),
                "split": request.get("fit_split", "all"), "held_out_trials": inp["split_trials"],
                "groups": [{"key": k, "events": len(p), "trials": len({r["trial"] for r in p})}
                           for k, p in zip([g.get("key", str(i)) for i, g in enumerate(groups) if g.get("key", str(i)) in inp["fit_keys"]], train_members)]}
    train_raw = means.reshape(-1, len(ids))[:, keep_mask]
    normalization = {"center": fit["center"][keep_mask].tolist(), "scale": fit["scale"].tolist(),
                     "operator": np.asarray(operator).tolist(), "offset": np.asarray(offset_b).tolist(),
                     "heat_sd": train_raw.std(axis=0).tolist(), "heat_peak": train_raw.max(axis=0).tolist()}

    active = fit["active_ids"]
    keep = [ids.index(u) for u in active]
    out_groups = []
    for g, picked in enumerate(members):
        spec = groups[g]
        out_groups.append({"key": spec.get("key", str(g)), "label": spec.get("label", str(g)), "events": len(picked),
                           "trials": len({r["trial"] for r in picked}), "row_ids": [int(r["row_id"]) for r in picked],
                           "coords": np.round(traj[g], 6).tolist(),
                           "means": np.round(display_means[g][:, keep], 4).tolist(),
                           "sample": "held-out trials" if inp["split_trials"] else ("fit" if spec.get("key", str(g)) in inp["fit_keys"] else "projected group")})
    evr = None if tdr else fit["operators"].get("explained_variance_ratio")
    return {"kind": "population_fit", "session_id": loaded.session_id, "alignment": alignment, "policy": policy,
            "unit_ids": ids, "active_unit_ids": active, "dropped_constant_units": fit["dropped_ids"],
            "times": np.round(times, 6).tolist(), "groups": out_groups, "components": components,
            "loadings": np.round(loadings, 6).tolist(), "component_r2": [round(v, 6) for v in single],
            "cumulative_r2": [round(v, 6) for v in cumulative],
            "explained_variance_ratio": evr, "reconstruction_r2": fit["reconstruction_r2"], "rank": fit["rank"],
            "fit_rows": int(x.shape[0]), "training": training, "normalization": normalization, "converged": fit["converged"], "warnings": fit["warnings"],
            "method": method, "scaling": scaling, "weight": weight, "window": [pre, post],
            **({"tdr": tdr, "axis_names": [f["label"] for f in tdr["factors"]]} if tdr else {}), "bin": bin_s, "sigma": sigma,
            "common_trials": len(eligible), "guard_s": GUARD_S,
            "scope": ("Exploratory projection of complementary held-out trial IDs; odd/even trials may be autocorrelated. "
                      if inp["split_trials"] else "Descriptive fit to selected groups; projected groups may share training trials. ")
                     + "Normalization, active units and basis use training data only. R² describes training means; no significance test.",
            "weighting": ("equal trials within group, events averaged within trial" if weight == "trial" else "equal events within group")
                         + "; equal condition-time rows in the fit",
            "provenance": {"source": loaded.metadata()["source"], "eligibility": {k: v for k, v in (provenance or {}).items() if k != "source"}}}


def population_probe(loaded: Any, request: Mapping[str, Any]) -> dict:
    """Every trial's (or event's) projection at a few times, with the fitted basis.

    Rates use the fit's own grid, kernel and normalisation, and the weighting unit
    of its group means (a trial = its events averaged; an event = one row), so each
    group's cloud is centred exactly on its trajectory point at that bin.
    """
    inp = _fit_inputs(loaded, request)
    fits = explorer_cache(loaded).setdefault("fits", OrderedDict())
    if inp["key"] not in fits:
        population_fit(loaded, request)
    op = fits[inp["key"]]
    fits.move_to_end(inp["key"])
    probes = request.get("probe_times")
    if not isinstance(probes, list) or not 1 <= len(probes) <= 12:
        raise ValueError("probe_times must list 1-12 times.")
    pre, post, bin_s, n, radius, kernel = inp["pre"], inp["post"], inp["bin"], inp["n"], inp["radius"], inp["kernel"]
    probe_bins = []
    for t in probes:
        t = _window(t, "probe time")
        if not pre <= t <= post:
            raise ValueError(f"Probe time {t} s lies outside the window [{pre}, {post}] s.")
        probe_bins.append((t, min(n - 1, max(0, int(math.floor((t - pre) / bin_s + 1e-9))))))
    flat, members = inp["flat"], inp["members"]
    anchors = np.array([float(r["t"]) for r in flat])
    spikes = {uid: np.sort(np.asarray(loaded.spikes(uid), dtype=float)) for uid in op["active_ids"]}
    out = []
    for t, j in probe_bins:
        # Padded bins j..j+2r of the fit's grid feed the smoothed rate at bin j.
        edges = pre + (j - radius + np.arange(2 * radius + 2)) * bin_s
        x = np.empty((len(flat), len(op["active_ids"])))
        for u, uid in enumerate(op["active_ids"]):
            counts = np.diff(np.searchsorted(spikes[uid], anchors[:, None] + edges[None, :], side="left"), axis=1)
            x[:, u] = counts @ kernel / bin_s
        groups, offset = [], 0
        for spec, picked in zip(inp["groups"], members):
            block = x[offset:offset + len(picked)]
            offset += len(picked)
            if inp["weight"] == "trial":
                order = list(dict.fromkeys(r["trial"] for r in picked))
                block = np.array([block[[k for k, r in enumerate(picked) if r["trial"] == tid]].mean(axis=0) for tid in order])
                ids = [int(tid) for tid in order]
            else:
                ids = [int(r["row_id"]) for r in picked]
            z = ((block - op["center"]) / op["scale"]) @ op["operator"] + op["offset"]
            groups.append({"key": spec.get("key"), "ids": ids, "points": np.round(z, 5).tolist()})
        out.append({"t": t, "bin_index": j, "bin_centre": round(float(inp["times"][j]), 6), "groups": groups})
    return {"kind": "population_probe", "unit": inp["weight"], "probes": out,
            "note": "centroid of each group's points equals its trajectory point at that bin"}
