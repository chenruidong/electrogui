# electro_gui 0.1

Promoted from the reviewed unit/population explorer design. A loopback HTTP
application serves a local interface and computes from an exact assembled NWB.
No experimental data are shipped in this package. Original design fixtures and
reports remain unchanged under `output/unit_explorer_design/`.

## Internal interfaces

The session loader and the arithmetic the world-axis stages share live in the
pipeline package, and electro_gui imports them: `imitation_phys.session_store`
(the loader below) and `imitation_phys.explorer_core` (alignment rows, eligible
spans, the time grid, rates, the basis fit and the stable roster).  No
`imitation_phys` module imports `electro_gui`.

`imitation_phys.session_store.SessionStore(roots, session_files, cache_dir)` discovers only exact
`<sid>/analysis/nwb/<sid>_session.nwb` products (explicit session files are also
accepted). `catalog()` returns `{id, path}` entries. `get(session_id)` loads and
validates the source lazily and returns a `LoadedSession`. Its interface is:

- `session`: repository SessionFile, `session_id`, `duration_s`.
- `trials`: list of JSON-safe `{id, start, stop, complete, world, intention,
  block_id, success, reward_tokens, ...}` rows.
- `rows`: JSON-safe event dictionaries with `row_id` (original source row),
  `t`, `trial`, `event`, validity flags, object and enriched relationship fields.
  Histories are derived before filtering, using actual outcome timestamps.
- `fields`: registry dictionaries `{key, label, type, availability, timing,
  values?, description, timing_description, category, value_counts,
  missing_count, cardinality, units, range?, grouping_requires_bins}`.
  Canonical category domains include valid zero-support values. Unsupported
  fields carry a reason and cannot be used silently. Numeric fields omit
  per-value counts to bound metadata size.
- `units`: dictionaries `{id, area, quality, n_spikes}` for every current unit.
- `alignments`: strings of available events plus `object_outcome` union.
- `alignment_fields`: corresponding `{key,label,category,description}` records.
- `spikes(unit_id)`: sorted numpy array from the current NWB.
- `eligibility(unit_ids, policy)`: `(set_of_common_trial_ids, provenance_dict)`.
  Policy `verified_stable` recomputes/reuses content-bound stability; policy
  `all_complete` deliberately performs no stability filtering.
- `metadata()`: source, units, fields, alignments, counts and provenance for UI.

`analysis.compute_unit(loaded, request)` and `population.compute_population`
accept the same request: `{session_id, unit_id, alignment, pre, post, bin,
sigma, count_window:[lo,hi], stability, recipe, test}`. Seconds throughout.
Recipe has `shared:{mode,rules}`, `cohorts:[{id,name,mode,rules}]`, `facet`,
`group_by`, `split_by`, `overlap`, `strata`, `gate`, and optional `group_bins`.
`group_bins` maps numeric field names to finite strictly ascending edges.
Bins are left-inclusive and right-exclusive except the final upper edge;
out-of-range and missing values receive no numeric bin label. Raw fields and
filter comparisons remain unchanged. Predicates use the reviewed
typed operators. One or more explicitly named cohorts are allowed; tests use
two. Default recipe compares world PP/PM/MM. Empty support is reported.

`analysis.prepare_rows(loaded, request, unit_ids)` returns
`(selected_rows, support, provenance)` and is shared by unit and population.
Rows include cohort/facet/group identities and style metadata. Full display
window plus a fixed 0.4 s support guard must fit in a contiguous eligible trial
run and recording bounds; sigma is at most 0.1 s. Event count intervals are
half-open. Unit result `{kind:'unit', session_id, unit, settings, times, edges,
groups, rows, support, provenance, statistics}`. A group has `{name,label,
color_key,line_dashed,facet_key,facet_value,trials,blocks,mean,sem}`. Rows include
`count`, `rate`, `spikes` (relative display-window times), `group`, `trial`,
`cohort`, `t`, `row_id`. PSTHs average events within trial then trials equally.

Population request adds `unit_ids`, `method` (`pca`, `ica`, `fa`), `scaling`
(`center`, `zscore`), `components` (2–10). Common eligible trials and exactly
the same selected rows are used for every unit. Fit one basis to all displayed
condition means jointly; this is descriptive in-sample analysis. Result has
`kind:'population', times, groups:[{name,label,color_key,line_dashed,coordinates}],
unit_ids, components, loadings, diagnostics, model, support, provenance,
settings`. Coordinates are time × component. Export includes preprocessing,
model operators, raw input condition means and exact membership.

## HTTP interface

- `GET /api/catalog`: `{version,sessions,default_session}`.
- `POST /api/jobs`: `{action:'load'|'unit'|'population'|'preview'|'annotate',
  ...request}` → `{id}`.
- `GET /api/jobs/<id>`: `{id,status:'queued'|'running'|'done'|'error',message,
  result?,error?}`. UI polls and ignores superseded jobs.
- `GET /api/jobs/<id>/export?format=json|csv|svg|membership|stats`: completed result download.
  CSV is long-form unit PSTH or population coordinates; JSON is the complete
  result including exact membership, statistics, source identity and recipe.

Previews use the same selection engine, without fitting or counting spikes.
Their records are stored separately so frequent previews cannot evict completed
analysis exports. Population previews report each selected unit's eligibility
and the common trial intersection. Pending eligibility is not final support.

Annotation layers use `{id,kind,name,source,visible,color,time?,event?,onset?,
offset?,match,occurrence}`. Kinds are `reference`, `event`, and `interval`;
the supported source is `recorded_events`. Matching is `same_object` or
`same_trial`, occurrence is `first`, `last`, or `all`. Completed results retain
per-row timings, endpoint identities, clipping and pairing diagnostics, and
labeled distribution/occupancy summaries. An `annotate` job derives an exportable
display result from a completed job without refitting or changing membership.

The browser stores separate Unit and Population draft settings, revisions,
pending work and completed results. Session identity remains shared. Copying
settings creates an independent snapshot. Editing a draft labels its previous
result explicitly; a failed computation preserves that result and its exports.
Setup files store the complete active workspace and source identity; a separate
conditions-only import leaves other controls unchanged.

Static assets are local; no CDN, remote data or cluster. All exports describe
the actual completed job, including the annotation definitions applied to it.


## Usability implementation details

The condition registry is shared by the strict backend validator and guided UI.
Categorical sets use multi-selection, numeric ranges have separate bounds, and
missingness needs no value. Session-wide category counts are labeled as such;
selection support comes from debounced `prepare_rows` previews. Numeric grouping
requires explicit finite ascending edges. Previews report per-group event, trial
and block support, missing-rule events, exclusions, overlap, and per-test
applicability. Population previews identify neurons that reduce the common trial
intersection without dropping them.

Each workspace owns an independent numerical revision and annotation revision.
Async display updates check the source-load sequence, base result job and display
revision before committing. A source reload clears both workspaces' source-bound
plots and export handles. Preview polling coalesces edits; display-only annotation
jobs retain the original computation identity and add a separate annotation
identity. Completed plot annotations come from the completed result, not live
draft definitions. Raster ticks and bands occupy their own event rows; a separate
pooled strip shows event times or equal-anchor interval occupancy. Exact endpoints
and diagnostics remain inspectable/exportable. Recorded joystick edges are not
continuous-signal movement-bout detections.

Version-2 setup imports are source-bound and validated atomically before restoring
controls. Conditions-only import is intentionally separate. Question templates
keep the current session and unit, and Population starts with an empty roster.
Area/quality filters, replace/add selection, selected-only inspection, grouping
disclosures, collapsible settings and a sticky Compute/support bar bound long
forms at desktop and narrow widths.

## Explorer training subsets

`POST /api/explorer/popfit` and `/popprobe` include `fit_group_keys`,
`fit_split` and `fit_trial_ids` in the fit cache identity. `_fit_inputs`
resolves training and display memberships separately, checking empty groups
and overlap of padded spike windows for trial splits. All fitting helpers
receive only training means/events; display means and probe points use the
training affine operator. The response carries `training`, `normalization`
and display `row_ids`/`sample` per group. The client filters its display model
to those rows for counts, medians, clouds, findings and exports. The default
all-group fit retains the shared world-axis numerical contract. Classic
routes, inference, export/annotation jobs and executors remain unchanged.

The client rejects restricted fits with adaptive continuous numeric grouping:
its all-row quantile thresholds are not a training-only selection operator.
Result/probe caches use complete serialized request identities. A population
model signature binds redraws, exports/findings and row navigation to the
current model/fit inputs, including quantile bins and hidden groups; only a
fresh result publishes a stepping order. Error/empty views invalidate that fit
and clear/disable heatmap selectors.
