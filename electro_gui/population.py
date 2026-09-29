"""Descriptive population transforms fitted jointly to selected condition means."""
from __future__ import annotations

import warnings

import numpy as np
from sklearn.decomposition import FactorAnalysis, FastICA, PCA
from sklearn.exceptions import ConvergenceWarning

from .analysis import prepare_rows


def _rates(spikes, anchors, pre, post, bin_s, sigma):
    n_bins = int(round((post - pre) / bin_s))
    radius = int(np.ceil(4 * sigma / bin_s))
    edges = pre + np.arange(-radius, n_bins + radius + 1) * bin_s
    counts = np.diff(np.searchsorted(spikes, anchors[:, None] + edges[None, :], side="left"), axis=1)
    rates = counts / bin_s
    if radius:
        kernel = np.exp(-.5 * (np.arange(-radius, radius + 1) * bin_s / sigma) ** 2)
        kernel /= kernel.sum()
        rates = np.apply_along_axis(lambda a: np.convolve(a, kernel, mode="valid"), 1, rates)
    return rates


def fit_basis(means, ids, method, scaling, components):
    """Fit one basis jointly to condition means shaped (groups, times, units).

    Constant units are dropped and reported.  Rows of the fit matrix are the
    condition-time points, each weighted equally.
    """
    raw = means.reshape(-1, len(ids))
    center = raw.mean(axis=0)
    std = raw.std(axis=0, ddof=0)
    varying = std > max(1e-12, float(std.max()) * 1e-12)
    active_ids = [uid for uid, keep in zip(ids, varying) if keep]
    dropped = [uid for uid, keep in zip(ids, varying) if not keep]
    if len(active_ids) < components:
        raise ValueError(f"Only {len(active_ids)} nonconstant units support this selection; reduce component count or change the roster/recipe.")
    scale = std[varying] if scaling == "zscore" else np.ones(varying.sum())
    x = (raw[:, varying] - center[varying]) / scale
    rank = int(np.linalg.matrix_rank(x))
    if components > rank:
        raise ValueError(f"Requested {components} components but the selected condition matrix has rank {rank}.")
    if method == "pca":
        estimator = PCA(n_components=components, svd_solver="full")
    elif method == "ica":
        estimator = FastICA(n_components=components, whiten="unit-variance", random_state=0, max_iter=2000, tol=1e-5)
    else:
        estimator = FactorAnalysis(n_components=components, svd_method="lapack", random_state=0, max_iter=2000, tol=1e-4)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ConvergenceWarning)
        coordinates = estimator.fit_transform(x)
    notices = [str(w.message) for w in caught]
    converged = not any(issubclass(w.category, ConvergenceWarning) for w in caught)
    # Mixing/loadings express a one-component reconstruction in normalized units.
    if method == "ica":
        loadings = estimator.mixing_
        reconstruction = estimator.inverse_transform(coordinates)
    else:
        loadings = estimator.components_.T
        reconstruction = coordinates @ estimator.components_ + estimator.mean_
    denom = float(np.sum((x - x.mean(axis=0)) ** 2))
    reconstruction_r2 = 1 - float(np.sum((x - reconstruction) ** 2)) / denom
    models = {"components": estimator.components_.tolist(), "mean": estimator.mean_.tolist()}
    for attr in ("mixing_", "whitening_", "noise_variance_", "explained_variance_", "explained_variance_ratio_", "singular_values_"):
        if hasattr(estimator, attr):
            models[attr.rstrip("_")] = getattr(estimator, attr).tolist()
    return {"coordinates": coordinates, "loadings": loadings, "operators": models, "active_ids": active_ids,
            "dropped_ids": dropped, "rank": rank, "converged": converged, "warnings": notices, "estimator": estimator,
            "center": center, "varying": varying, "scale": scale, "x": x, "reconstruction_r2": reconstruction_r2}


def grid(pre, post, bin_s, sigma):
    """The explorer's time grid (static/core.js psthGrid): bins, kernel radius, kernel, centres."""
    n = int(round((post - pre) / bin_s))
    if abs(n * bin_s - (post - pre)) > 1e-9:
        n = int(np.ceil((post - pre) / bin_s - 1e-9))
    n = max(1, n)
    radius = int(np.ceil(4 * sigma / bin_s - 1e-9)) if sigma > 0 else 0
    kernel = np.exp(-.5 * (np.arange(-radius, radius + 1) * bin_s / sigma) ** 2) if radius else np.ones(1)
    return n, radius, kernel / kernel.sum(), pre + (np.arange(n) + .5) * bin_s


def group_means(spikes, anchors, weights, pre, bin_s, n, radius, kernel):
    """Weighted group means of smoothed rates, shaped (groups, n).

    ``weights`` (groups x rows) holds each row's share of its group mean.  Averaging
    the binned counts before smoothing equals smoothing each row first, because the
    kernel is linear, and it is much cheaper for large rosters.
    """
    edges = pre + np.arange(-radius, n + radius + 1) * bin_s
    counts = np.diff(np.searchsorted(spikes, anchors[:, None] + edges[None, :], side="left"), axis=1)
    means = (weights @ counts) / bin_s
    if not radius:
        return means
    out = np.zeros((means.shape[0], n))
    for k, w in enumerate(kernel):
        out += w * means[:, k:k + n]
    return out


def row_rates(spikes, anchors, pre, bin_s, n, radius, kernel):
    """Smoothed rate of every event, shaped (events, n); the per-row twin of :func:`group_means`."""
    edges = pre + np.arange(-radius, n + radius + 1) * bin_s
    counts = np.diff(np.searchsorted(spikes, anchors[:, None] + edges[None, :], side="left"), axis=1) / bin_s
    if not radius:
        return counts
    out = np.zeros((len(anchors), n))
    for k, w in enumerate(kernel):
        out += w * counts[:, k:k + n]
    return out


def compute_population(loaded, request):
    """Fit a single within-session basis to the exact selected membership.

    Condition means first average events within trial and then trials equally.
    No pseudopopulation, condition-specific basis, predictive validation or
    inference is implied. Every output retains the fit matrix and operators.
    """
    ids = request.get("unit_ids")
    if not isinstance(ids, list) or len(ids) < 2:
        raise ValueError("Population analysis requires at least two explicit unit IDs.")
    if any(isinstance(i, bool) or not isinstance(i, int) for i in ids):
        raise ValueError("Population unit IDs must be integers.")
    if len(set(ids)) != len(ids):
        raise ValueError("Population unit roster contains duplicates.")
    unit_map = {int(u["id"]): u for u in loaded.units}
    if set(ids) - set(unit_map):
        raise ValueError(f"Unknown population units: {sorted(set(ids) - set(unit_map))}")
    method = request.get("method", "pca")
    if method not in ("pca", "ica", "fa"):
        raise ValueError("Population method must be pca, ica, or fa.")
    scaling = request.get("scaling", "center")
    if scaling not in ("center", "zscore"):
        raise ValueError("Population scaling must be center or zscore.")
    components = request.get("components", 3)
    if isinstance(components, bool) or not isinstance(components, int) or not 2 <= components <= 10:
        raise ValueError("Choose 2–10 population components.")
    rows, support, provenance = prepare_rows(loaded, request, ids)
    if not rows:
        raise ValueError("No common eligible events for the selected population and recipe.")
    pre, post = float(request.get("pre", -1)), float(request.get("post", 1))
    bin_s, sigma = float(request.get("bin", .05)), float(request.get("sigma", .05))
    n_bins = int(round((post - pre) / bin_s))
    times = pre + (np.arange(n_bins) + .5) * bin_s
    names = list(dict.fromkeys(row["group"] for row in rows))
    anchors = np.array([r["t"] for r in rows], dtype=float)
    # Bound the temporary event × time matrix, without limiting the unit roster.
    if len(rows) * (n_bins + 2 * int(np.ceil(4 * sigma / bin_s))) > 20_000_000:
        raise ValueError("Population event × time matrix is too large; narrow the event/window selection or increase bin width.")
    group_trials = []
    for name in names:
        idx = [i for i, row in enumerate(rows) if row["group"] == name]
        trials = list(dict.fromkeys(rows[i]["trial"] for i in idx))
        group_trials.append([np.array([i for i in idx if rows[i]["trial"] == t]) for t in trials])
    means = np.empty((len(names), n_bins, len(ids)), dtype=float)
    for u, unit_id in enumerate(ids):
        rates = _rates(loaded.spikes(unit_id), anchors, pre, post, bin_s, sigma)
        for g, trial_indices in enumerate(group_trials):
            means[g, :, u] = np.mean([rates[ix].mean(axis=0) for ix in trial_indices], axis=0)
    fit = fit_basis(means, ids, method, scaling, components)
    coordinates, loadings, models = fit["coordinates"], fit["loadings"], fit["operators"]
    active_ids, dropped, rank = fit["active_ids"], fit["dropped_ids"], fit["rank"]
    converged, notices, estimator = fit["converged"], fit["warnings"], fit["estimator"]
    center, varying, scale, x = fit["center"], fit["varying"], fit["scale"], fit["x"]
    reconstruction_r2 = fit["reconstruction_r2"]
    trajectories = coordinates.reshape(len(names), n_bins, components)
    groups = []
    for g, name in enumerate(names):
        selected = [r for r in rows if r["group"] == name]
        first = selected[0]
        groups.append({"name": name, "label": first.get("group_label", name),
                       "color_key": first.get("color_key", first.get("cohort", name)),
                       "line_dashed": bool(first.get("line_dashed", False)),
                       "facet_key": first.get("facet_key", "all"), "facet_value": first.get("facet_value"),
                       "trials": len(group_trials[g]), "events": len(selected),
                       "coordinates": trajectories[g].tolist(), "input_means": means[g].tolist()})
    result = {"kind": "population", "session_id": loaded.session_id, "settings": request,
            "times": times.tolist(), "groups": groups, "rows": rows,
            "unit_ids": ids, "active_unit_ids": active_ids, "dropped_constant_units": dropped,
            "units": [dict(unit_map[i]) for i in ids],
            "components": components, "loadings": loadings.tolist(),
            "support": support, "provenance": provenance,
            "diagnostics": {"method": method, "scaling": scaling, "fit_rows": len(x), "rank": rank,
                            "converged": converged, "warnings": notices,
                            "iterations": int(getattr(estimator, "n_iter_", 0)),
                            "reconstruction_r2": reconstruction_r2,
                            "explained_variance_ratio": models.get("explained_variance_ratio"),
                            "scope": "Descriptive, in-sample fit to all displayed condition means jointly; no held-out prediction or significance test."},
            "model": {"method": method, "unit_order": active_ids, "fit_group_order": names,
                      "center": center[varying].tolist(), "scale": scale.tolist(),
                      "weighting": "Equal events within trial, equal trials within condition; equal condition-time rows in the transform fit.",
                      "operators": models, "random_seed": 0}}
    if request.get("annotations"):
        from .annotations import annotate_result
        result = annotate_result(result, loaded, request["annotations"])
    return result
